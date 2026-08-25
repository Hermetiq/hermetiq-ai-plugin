#!/usr/bin/env python3
"""Run the Hermetiq skill eval suite through Claude Code and a real MCP server."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = REPO_ROOT / "plugins" / "hermetiq" / "skills" / "hermetiq" / "evals" / "evals.json"
DEFAULT_PLUGIN = REPO_ROOT / "plugins" / "hermetiq"
MUTATION_TOOLS = {"import_config_map_yaml", "save_config_set", "create_config_set_pull_request"}
LEGACY_TOOL = re.compile(r"^(?:bep_query_v1_|project_v1_|config_v1_)|^[A-Z]")
PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evals", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--plugin-dir", type=Path, default=DEFAULT_PLUGIN)
    parser.add_argument("--endpoint", default=os.getenv("HERMETIQ_MCP_EVAL_URL", "http://127.0.0.1:5150/mcp"))
    parser.add_argument("--server-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", dest="cases", help="run only this case ID; repeatable")
    parser.add_argument("--model", help="override suite model")
    parser.add_argument("--max-budget-per-case", type=float, default=0.10)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def substitute(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables or not variables[name]:
                raise ValueError(f"required eval placeholder {name} is not set")
            return variables[name]
        return PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, variables) for key, item in value.items()}
    return value


def iter_content_blocks(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        return [block for block in message["content"] if isinstance(block, dict)]
    content = event.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return json.dumps(content, sort_keys=True)


def parse_stream(stdout: str) -> tuple[list[dict[str, Any]], str, float | None]:
    calls: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    final = ""
    cost: float | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            if isinstance(event.get("result"), str):
                final = event["result"]
            if isinstance(event.get("total_cost_usd"), (int, float)):
                cost = float(event["total_cost_usd"])
        for block in iter_content_blocks(event):
            block_type = block.get("type")
            if block_type == "tool_use" and isinstance(block.get("name"), str):
                raw_name = block["name"]
                prefix = "mcp__hermetiq__"
                if not raw_name.startswith(prefix):
                    continue
                call_id = str(block.get("id", f"call-{len(calls)}"))
                call = {
                    "id": call_id,
                    "name": raw_name[len(prefix):],
                    "arguments": block.get("input", {}),
                    "isError": None,
                    "result": "",
                }
                calls.append(call)
                by_id[call_id] = call
            elif block_type == "tool_result":
                call = by_id.get(str(block.get("tool_use_id", "")))
                if call is not None:
                    call["isError"] = bool(block.get("is_error", False))
                    call["result"] = result_text(block.get("content", ""))
    return calls, final, cost


def json_type_matches(value: Any, expected: Any) -> bool:
    kinds = expected if isinstance(expected, list) else [expected]
    for kind in kinds:
        if kind == "null" and value is None:
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "array" and isinstance(value, list):
            return True
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "boolean" and isinstance(value, bool):
            return True
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
    return False


def validate_input(arguments: Any, schema: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(arguments, dict):
        return False, "arguments are not an object"
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if schema.get("additionalProperties") is False and unknown:
        return False, f"unknown fields {sorted(unknown)}"
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        return False, f"missing required fields {sorted(missing)}"
    for key, value in arguments.items():
        expected = properties.get(key, {}).get("type")
        if expected is not None and not json_type_matches(value, expected):
            return False, f"{key} has wrong type"
    return True, "schema-valid"


def run_case(
    case: dict[str, Any],
    args: argparse.Namespace,
    model: str,
    config_path: Path,
    schema_by_tool: dict[str, dict[str, Any]],
    skill_command: str,
) -> dict[str, Any]:
    command = [
        "claude",
        "--bare",
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--plugin-dir",
        str(args.plugin_dir),
        "--mcp-config",
        str(config_path),
        "--strict-mcp-config",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "Skill",
        "--allowedTools",
        "Skill",
        "mcp__hermetiq__*",
        "--model",
        model,
        "--max-budget-usd",
        str(args.max_budget_per_case),
        f"{skill_command}\n\n{case['prompt']}",
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, "NO_COLOR": "1"},
        text=True,
        capture_output=True,
        timeout=args.timeout_seconds,
        check=False,
    )
    duration = time.monotonic() - started
    calls, final, cost = parse_stream(completed.stdout)
    actual_sequence = [call["name"] for call in calls]
    expected_sequence = case["expectedMcpSequence"]
    tool_selection = actual_sequence == expected_sequence
    legacy_calls = [name for name in actual_sequence if LEGACY_TOOL.search(name)]
    lower_camel_aliases = {
        name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:])
        for name in schema_by_tool
        if "_" in name
    }
    legacy_final_names = sorted(
        alias for alias in lower_camel_aliases
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])", final)
    )

    first_valid = True
    first_reason = "no tool call expected"
    if calls:
        schema = schema_by_tool.get(calls[0]["name"])
        if schema is None:
            first_valid, first_reason = False, "tool absent from server catalog"
        else:
            first_valid, first_reason = validate_input(calls[0]["arguments"], schema)
    elif expected_sequence:
        first_valid, first_reason = False, "expected a first tool call"

    expected_first = case.get("expectedFirstCall")
    first_matches = expected_first is None and not calls
    if expected_first is not None and calls:
        required_arguments = expected_first["arguments"]
        first_matches = calls[0]["name"] == expected_first["tool"] and all(
            calls[0]["arguments"].get(key) == value for key, value in required_arguments.items()
        )

    unnecessary = max(0, len(actual_sequence) - len(expected_sequence))
    if not tool_selection and unnecessary == 0:
        unnecessary = len([name for index, name in enumerate(actual_sequence) if index >= len(expected_sequence) or name != expected_sequence[index]])
    unnecessary_ok = unnecessary <= case.get("maximumUnnecessaryCalls", 0)

    requires_recovery = bool(case.get("requiresToolErrorRecovery"))
    recovery_passed = True
    if requires_recovery:
        recovery_passed = (
            len(calls) == 1
            and calls[0].get("isError") is True
            and bool(final.strip())
        )

    mutation_expectation = case.get("mutationExpectation")
    mutation_calls = [call for call in calls if call["name"] in MUTATION_TOOLS]
    mutation_passed = True
    if mutation_expectation == "refuse":
        mutation_passed = not mutation_calls
    elif mutation_expectation == "execute_once":
        mutation_passed = (
            len(mutation_calls) == 1
            and mutation_calls[0]["arguments"].get("confirmMutation") is True
        )

    missing_patterns = [
        pattern for pattern in case.get("expectedFinalPatterns", [])
        if re.search(pattern, final, flags=re.IGNORECASE | re.DOTALL) is None
    ]
    evidence_passed = bool(final.strip()) and not missing_patterns
    passed = all(
        [
            completed.returncode == 0,
            tool_selection,
            not legacy_calls,
            not legacy_final_names,
            first_valid,
            first_matches,
            unnecessary_ok,
            recovery_passed,
            mutation_passed,
            evidence_passed,
        ]
    )
    return {
        "id": case["id"],
        "category": case["category"],
        "prompt": case["prompt"],
        "expectedMcpSequence": expected_sequence,
        "actualMcpSequence": actual_sequence,
        "calls": calls,
        "final": final,
        "processExitCode": completed.returncode,
        "stderr": completed.stderr,
        "durationSeconds": round(duration, 3),
        "costUsd": cost,
        "scores": {
            "toolSelection": tool_selection,
            "validFirstArguments": first_valid and first_matches,
            "firstArgumentReason": first_reason,
            "unnecessaryCalls": unnecessary,
            "errorRecovery": recovery_passed,
            "mutationSafety": mutation_passed,
            "evidenceQuality": evidence_passed,
            "missingEvidencePatterns": missing_patterns,
            "legacyToolNameCalls": legacy_calls,
            "legacyToolNameMentions": legacy_final_names,
        },
        "status": "pass" if passed else "fail",
        "rawStream": completed.stdout,
    }


def rate(results: list[dict[str, Any]], field: str, selected: Any = None) -> float:
    applicable = results if selected is None else [result for result in results if selected(result)]
    if not applicable:
        return 1.0
    return sum(bool(result["scores"][field]) for result in applicable) / len(applicable)


def main() -> int:
    args = parse_args()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is required; load it from pass without writing it to disk", file=sys.stderr)
        return 2
    suite = load_json(args.evals)
    server_catalog = load_json(args.server_catalog)
    schemas = {tool["name"]: tool.get("inputSchema", {}) for tool in server_catalog["tools"]}
    variables = {name: os.getenv(name, "") for name in suite["runtime"]["placeholders"]}
    selected = set(args.cases or [])
    cases = [case for case in suite["evals"] if not selected or case["id"] in selected]
    if selected - {case["id"] for case in cases}:
        print(f"unknown case IDs: {sorted(selected - {case['id'] for case in cases})}", file=sys.stderr)
        return 2
    try:
        cases = [substitute(case, variables) for case in cases]
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    config = {"mcpServers": {"hermetiq": {"type": "http", "url": args.endpoint}}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as config_file:
        json.dump(config, config_file)
        config_file.flush()
        model = args.model or suite["runtime"]["model"]
        results = []
        for case in cases:
            print(f"RUN {case['id']}", flush=True)
            try:
                result = run_case(
                    case,
                    args,
                    model,
                    Path(config_file.name),
                    schemas,
                    suite["runtime"]["skillCommand"],
                )
            except subprocess.TimeoutExpired as error:
                result = {
                    "id": case["id"], "category": case["category"], "status": "fail",
                    "error": f"Claude timed out after {error.timeout} seconds", "scores": {},
                }
            results.append(result)
            (args.output / f"{case['id']}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"{result['status'].upper()} {case['id']}", flush=True)

    complete = [result for result in results if result.get("scores")]
    summary = {
        "cases": len(results),
        "passed": sum(result["status"] == "pass" for result in results),
        "toolSelectionAccuracy": rate(complete, "toolSelection"),
        "validFirstArgumentRate": rate(complete, "validFirstArguments", lambda result: bool(result.get("expectedMcpSequence"))),
        "maximumUnnecessaryCalls": max((result["scores"]["unnecessaryCalls"] for result in complete), default=0),
        "errorRecoveryRate": rate(complete, "errorRecovery", lambda result: result["id"] == "invalid-id-recovery"),
        "mutationSafetyRate": rate(complete, "mutationSafety", lambda result: result["category"].startswith("mutation_")),
        "evidenceQualityRate": rate(complete, "evidenceQuality"),
        "legacyToolNameCalls": sum(
            len(result["scores"]["legacyToolNameCalls"]) + len(result["scores"]["legacyToolNameMentions"])
            for result in complete
        ),
        "costUsd": round(sum(result.get("costUsd") or 0 for result in complete), 6),
    }
    thresholds = suite["thresholds"]
    gates = {
        "allCasesPassed": summary["passed"] == summary["cases"],
        "toolSelectionAccuracy": summary["toolSelectionAccuracy"] >= thresholds["toolSelectionAccuracy"],
        "validFirstArgumentRate": summary["validFirstArgumentRate"] >= thresholds["validFirstArgumentRate"],
        "maximumUnnecessaryCalls": summary["maximumUnnecessaryCalls"] <= thresholds["maximumUnnecessaryCallsPerCase"],
        "errorRecoveryRate": summary["errorRecoveryRate"] >= thresholds["errorRecoveryRate"],
        "mutationSafetyRate": summary["mutationSafetyRate"] >= thresholds["mutationSafetyRate"],
        "evidenceQualityRate": summary["evidenceQualityRate"] >= thresholds["evidenceQualityRate"],
        "legacyToolNameCalls": summary["legacyToolNameCalls"] == 0,
    }
    run = {
        "runDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "client": subprocess.run(["claude", "--version"], text=True, capture_output=True, check=False).stdout.strip(),
        "model": args.model or suite["runtime"]["model"],
        "skillCommand": suite["runtime"]["skillCommand"],
        "server": server_catalog.get("server"),
        "serverVersion": server_catalog.get("version"),
        "endpoint": args.endpoint,
        "baseline": suite["baseline"],
        "thresholds": thresholds,
        "summary": summary,
        "gates": gates,
        "cases": results,
    }
    (args.output / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "gates": gates}, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

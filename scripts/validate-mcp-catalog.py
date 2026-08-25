#!/usr/bin/env python3
"""Validate Hermetiq skill/docs/evals against the canonical MCP catalog."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "plugins" / "hermetiq" / "skills" / "hermetiq"
DEFAULT_CATALOG = SKILL_ROOT / "evals" / "canonical-mcp-catalog.json"
EVALS = SKILL_ROOT / "evals" / "evals.json"

PUBLIC_TOOL_PREFIXES = {
    "analyze",
    "create",
    "describe",
    "diff",
    "export",
    "find",
    "get",
    "group",
    "health",
    "import",
    "list",
    "render",
    "resolve",
    "save",
    "search",
    "summarize",
}
GENERATED_NAME = re.compile(r"\b(?:bep_query_v1_|project_v1_|config_v1_)\w+\b")
PASCAL_ALIAS = re.compile(
    r"\b(?:Get|List|Find|Analyze|Resolve|Search|Describe|Create|Diff|Query|Lookup)"
    r"[A-Z][A-Za-z0-9]*\b|\bQuickstart\b"
)
NON_TOOL_TECHNICAL_NAMES = {"FindMissing", "FindMissingBlobs"}
CODE_SPAN = re.compile(r"`([^`\n]+)`")
LEADING_IDENTIFIER = re.compile(r"^([a-z][a-z0-9_]+)(?:\(|\s|$)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--server-catalog",
        type=Path,
        help="cloud-native mcpv2 catalog fixture; also validates exact set parity and eval arguments",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {path}: {error}") from error


def name_set(entries: list[Any], key: str = "name") -> set[str]:
    return {entry if isinstance(entry, str) else entry[key] for entry in entries}


def documentation_files() -> list[Path]:
    return [REPO_ROOT / "README.md", SKILL_ROOT / "SKILL.md", *sorted((SKILL_ROOT / "references").glob("*.md"))]


def validate_sorted_unique(values: list[str], label: str, errors: list[str]) -> None:
    if values != sorted(set(values)):
        errors.append(f"{label} must be sorted and contain no duplicates")


def validate_docs(catalog: dict[str, Any], errors: list[str]) -> None:
    tools = set(catalog["tools"])
    allowlist = catalog["allowlist"]
    allowed_non_tools = set(allowlist["prompts"]) | set(allowlist["resources"]) | set(allowlist["externalMcpTools"])

    for path in [*documentation_files(), EVALS]:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)
        for match in GENERATED_NAME.finditer(text):
            errors.append(f"{relative}: generated MCP name is forbidden: {match.group(0)}")
        for match in PASCAL_ALIAS.finditer(text):
            name = match.group(0)
            if name not in NON_TOOL_TECHNICAL_NAMES:
                errors.append(f"{relative}: legacy MCP alias is forbidden: {name}")

        for code in CODE_SPAN.findall(text):
            if code in allowed_non_tools:
                continue
            identifier = LEADING_IDENTIFIER.match(code)
            if identifier is None:
                continue
            name = identifier.group(1)
            if name.split("_", 1)[0] not in PUBLIC_TOOL_PREFIXES:
                continue
            if "_" not in name and name != "health_check":
                continue
            if name not in tools:
                errors.append(f"{relative}: backticked MCP-like name is absent from catalog: {name}")


def validate_eval_suite(catalog: dict[str, Any], server: dict[str, Any] | None, errors: list[str]) -> None:
    suite = load_json(EVALS)
    tools = set(catalog["tools"])
    cases = suite.get("evals", [])
    required_categories = {
        "core_build_diagnosis",
        "cache_drilldown",
        "test_drilldown",
        "action_drilldown",
        "infrastructure",
        "storage",
        "project_ambiguity",
        "disabled_capability",
        "invalid_argument_recovery",
        "mutation_refusal",
        "mutation_confirmation",
    }
    categories = {case.get("category") for case in cases}
    missing = required_categories - categories
    if missing:
        errors.append(f"eval suite missing categories: {sorted(missing)}")

    schema_by_tool: dict[str, dict[str, Any]] = {}
    if server is not None:
        schema_by_tool = {entry["name"]: entry.get("inputSchema", {}) for entry in server["tools"]}

    for case in cases:
        label = f"eval {case.get('id', '<missing id>')}"
        sequence = case.get("expectedMcpSequence")
        if not isinstance(sequence, list):
            errors.append(f"{label}: expectedMcpSequence must be a list")
            continue
        for name in sequence:
            if name not in tools:
                errors.append(f"{label}: expected tool is absent from catalog: {name}")

        first = case.get("expectedFirstCall")
        if first is None:
            if sequence:
                errors.append(f"{label}: non-empty sequence requires expectedFirstCall")
            continue
        if not sequence or first.get("tool") != sequence[0]:
            errors.append(f"{label}: expectedFirstCall must match sequence[0]")
            continue
        if server is not None:
            validate_arguments(label, first.get("arguments", {}), schema_by_tool.get(first["tool"], {}), errors)

    thresholds = suite.get("thresholds", {})
    for metric in (
        "toolSelectionAccuracy",
        "validFirstArgumentRate",
        "errorRecoveryRate",
        "mutationSafetyRate",
        "evidenceQualityRate",
    ):
        value = thresholds.get(metric)
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            errors.append(f"threshold {metric} must be a number from 0 to 1")
    if not isinstance(thresholds.get("maximumUnnecessaryCallsPerCase"), int):
        errors.append("threshold maximumUnnecessaryCallsPerCase must be an integer")


def validate_arguments(label: str, arguments: Any, schema: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(arguments, dict):
        errors.append(f"{label}: first-call arguments must be an object")
        return
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if unknown:
        errors.append(f"{label}: first-call arguments not in live schema: {sorted(unknown)}")
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        errors.append(f"{label}: required first-call arguments missing: {sorted(missing)}")


def validate_server_parity(catalog: dict[str, Any], server: dict[str, Any], errors: list[str]) -> None:
    comparisons = {
        "tools": name_set(server["tools"]),
        "prompts": name_set(server["prompts"]),
        "resources": name_set(server["resources"], "uri"),
        "resource templates": name_set(server.get("resource_templates", []), "uriTemplate"),
    }
    expected = {
        "tools": set(catalog["tools"]),
        "prompts": set(catalog["allowlist"]["prompts"]),
        "resources": {value for value in catalog["allowlist"]["resources"] if "{" not in value},
        "resource templates": {value for value in catalog["allowlist"]["resources"] if "{" in value},
    }
    for label, actual in comparisons.items():
        if actual != expected[label]:
            errors.append(
                f"server {label} drift: missing={sorted(expected[label] - actual)} "
                f"unexpected={sorted(actual - expected[label])}"
            )
    if server.get("version") != catalog.get("serverVersion"):
        errors.append(
            f"server version drift: fixture={server.get('version')} plugin={catalog.get('serverVersion')}"
        )


def main() -> int:
    args = parse_args()
    try:
        catalog = load_json(args.catalog)
        server = load_json(args.server_catalog) if args.server_catalog else None
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    errors: list[str] = []
    validate_sorted_unique(catalog.get("tools", []), "catalog tools", errors)
    for label, values in catalog.get("allowlist", {}).items():
        validate_sorted_unique(values, f"allowlist {label}", errors)
    validate_docs(catalog, errors)
    if server is not None:
        validate_server_parity(catalog, server, errors)
    validate_eval_suite(catalog, server, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "PASS: canonical MCP references validated "
        f"({len(catalog['tools'])} tools, "
        f"{len(catalog['allowlist']['prompts'])} prompts, "
        f"{len(catalog['allowlist']['resources'])} resources/templates)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

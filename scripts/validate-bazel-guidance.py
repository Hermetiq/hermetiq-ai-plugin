#!/usr/bin/env python3
"""Validate version-sensitive Bazel recommendations in the Hermetiq skill."""

from __future__ import annotations

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "plugins" / "hermetiq" / "skills"
CORE_SKILL = SKILL_ROOT / "hermetiq" / "SKILL.md"
OPTIMIZATION = SKILL_ROOT / "hermetiq" / "references" / "bazel-optimization.md"
BUILD_CONFIGURATION = SKILL_ROOT / "hermetiq" / "references" / "build-configuration.md"
ON_PREM_GOTCHAS = SKILL_ROOT / "on-prem-gke-install" / "references" / "known-gotchas.md"

MIN_SUPPORTED_MAJOR = 5
MAX_SUPPORTED_MAJOR = 9
VERSION_PATTERN = re.compile(r"(?:^|\D)(\d+)(?:\.\d+)?(?:\.\d+)?")

STABLE_FLAGS = {
    "--experimental_repository_cache_hardlinks",
    "--jobs",
    "--noremote_upload_local_results",
    "--remote_default_exec_properties",
    "--remote_download_minimal",
    "--remote_retries",
    "--remote_timeout",
    "--stamp",
    "--nostamp",
}


def bazel_major(version: str | None) -> int | None:
    if not version:
        return None
    match = VERSION_PATTERN.search(version)
    if match is None:
        return None
    major = int(match.group(1))
    if not MIN_SUPPORTED_MAJOR <= major <= MAX_SUPPORTED_MAJOR:
        return None
    return major


def compression_flag_for_version(version: str | None) -> str | None:
    major = bazel_major(version)
    if major is None:
        return None
    if major <= 6:
        return "--experimental_remote_cache_compression"
    return "--remote_cache_compression"


def flag_is_recommended(flag: str, version: str | None) -> bool:
    major = bazel_major(version)
    if major is None:
        return False
    if flag == "--experimental_remote_cache_compression":
        return major <= 6
    if flag == "--remote_cache_compression":
        return major >= 7
    if flag == "--incompatible_strict_action_env":
        return major <= 8
    if flag == "--noexperimental_check_external_repository_files":
        return False
    return flag in STABLE_FLAGS


def validate_guidance() -> list[str]:
    documents = {
        "core skill": CORE_SKILL.read_text(encoding="utf-8"),
        "optimization reference": OPTIMIZATION.read_text(encoding="utf-8"),
        "build-configuration reference": BUILD_CONFIGURATION.read_text(encoding="utf-8"),
        "on-prem timeout reference": ON_PREM_GOTCHAS.read_text(encoding="utf-8"),
    }
    errors: list[str] = []

    for label in ("core skill", "optimization reference", "build-configuration reference"):
        text = documents[label]
        if "`data.invocation.buildToolVersion`" not in text:
            errors.append(f"{label}: must route version-sensitive guidance through buildToolVersion")

    for label in ("optimization reference", "build-configuration reference"):
        text = documents[label]
        if "--noexperimental_check_external_repository_files" in text:
            errors.append(f"{label}: unstable external-repository flag must not be recommended")
        if "Default 3600" in text or "default 3600" in text:
            errors.append(f"{label}: stale remote_timeout default")
        if "Per-action timeout for remote execution" in text:
            errors.append(f"{label}: remote_timeout is incorrectly scoped to actions only")

    optimization = documents["optimization reference"]
    required_matrix_rows = (
        "| `--incompatible_strict_action_env` | 5–9 |",
        "| `--experimental_repository_cache_hardlinks` | 5–9 |",
        "| `--remote_timeout=<duration>` | 5–9 |",
        "| `--remote_retries=<N>` | 5–9 |",
        "| `--jobs=<N>` | 5–9 |",
        "| `--experimental_remote_cache_compression` | 5–6 |",
        "| `--remote_cache_compression` | 7–9 |",
        "| `--remote_download_minimal` | 5–9 |",
        "| `--noremote_upload_local_results` | 5–9 |",
        "| `--nostamp` / `--stamp` | 5–9 |",
        "| `--remote_default_exec_properties=<key=value>` | 5–9 |",
    )
    for row in required_matrix_rows:
        if row not in optimization:
            errors.append(f"optimization reference: missing compatibility row {row}")
    if "build --remote_retries=5" in optimization:
        errors.append("optimization reference: must not recommend Bazel's default retry count")
    for index, block in enumerate(
        re.findall(r"```bazelrc\n(.*?)```", optimization, flags=re.DOTALL),
        start=1,
    ):
        if (
            "--experimental_remote_cache_compression" in block
            and "--remote_cache_compression" in block
        ):
            errors.append(
                "optimization reference: copyable bazelrc block "
                f"{index} mixes mutually exclusive compression flag versions"
            )

    build_configuration = documents["build-configuration reference"]
    for stale_stamp_claim in (
        "absence of `--nostamp`",
        "Recommendation: use `--nostamp` as the default",
    ):
        if stale_stamp_claim in build_configuration:
            errors.append(
                "build-configuration reference: absent --nostamp must not be suspicious "
                f"or recommended by default ({stale_stamp_claim})"
            )
    for required_stamp_rule in ("last-wins", "no stamp flag is present"):
        if required_stamp_rule not in build_configuration:
            errors.append(
                "build-configuration reference: missing effective stamp-state rule "
                f"{required_stamp_rule}"
            )

    for label, text in documents.items():
        if "--remote_timeout" in text and "60" not in text:
            errors.append(f"{label}: remote_timeout guidance must state the 60-second default")

    return errors


def main() -> int:
    errors = validate_guidance()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PASS: Bazel 5-9 flag guidance is version-aware and internally consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Require distributable plugin changes to carry a synchronized SemVer bump."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = Path("plugins/hermetiq/.claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")
REQUIRED_VERSION_FILES = {PLUGIN_MANIFEST.as_posix(), MARKETPLACE_MANIFEST.as_posix()}
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class CheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...]

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = SEMVER_PATTERN.fullmatch(value)
        if match is None:
            raise CheckError(f"invalid plugin SemVer: {value!r}")
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        for identifier in prerelease:
            if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                raise CheckError(f"invalid plugin SemVer: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease)

    def __lt__(self, other: "SemVer") -> bool:
        current = (self.major, self.minor, self.patch)
        target = (other.major, other.minor, other.patch)
        if current != target:
            return current < target
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for current_id, target_id in zip(self.prerelease, other.prerelease):
            if current_id == target_id:
                continue
            current_numeric = current_id.isdigit()
            target_numeric = target_id.isdigit()
            if current_numeric and target_numeric:
                return int(current_id) < int(target_id)
            if current_numeric != target_numeric:
                return current_numeric
            return current_id < target_id
        return len(self.prerelease) < len(other.prerelease)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read {path}: {error}") from error


def manifest_versions(root: Path) -> tuple[str, str, str]:
    plugin = load_json(root / PLUGIN_MANIFEST)
    marketplace = load_json(root / MARKETPLACE_MANIFEST)
    try:
        plugin_version = plugin["version"]
        metadata_version = marketplace["metadata"]["version"]
        marketplace_version = next(
            entry["version"]
            for entry in marketplace["plugins"]
            if entry["name"] == "hermetiq"
        )
    except (KeyError, StopIteration, TypeError) as error:
        raise CheckError(f"missing Hermetiq version field: {error}") from error
    versions = (plugin_version, metadata_version, marketplace_version)
    if not all(isinstance(version, str) for version in versions):
        raise CheckError("all Hermetiq version fields must be strings")
    if len(set(versions)) != 1:
        raise CheckError(
            "plugin.json version, marketplace metadata.version, and marketplace "
            f"plugin version must match (found {versions})"
        )
    SemVer.parse(plugin_version)
    return versions


def git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CheckError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout


def version_at(commit: str, path: Path, selectors: tuple[str, ...]) -> str:
    raw = git("show", f"{commit}:{path.as_posix()}")
    try:
        value: Any = json.loads(raw)
        for selector in selectors:
            if selector.startswith("plugin:"):
                name = selector.removeprefix("plugin:")
                value = next(entry for entry in value["plugins"] if entry["name"] == name)
            else:
                value = value[selector]
    except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as error:
        raise CheckError(f"cannot read baseline version from {path}: {error}") from error
    if not isinstance(value, str):
        raise CheckError(f"baseline version in {path} must be a string")
    SemVer.parse(value)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Git ref used as the pull request base; omit for consistency-only validation",
    )
    arguments = parser.parse_args()

    try:
        plugin_version, _, _ = manifest_versions(REPO_ROOT)
        if not arguments.base_ref:
            print(f"plugin versions are synchronized at {plugin_version}")
            return 0

        merge_base = git("merge-base", arguments.base_ref, "HEAD").strip()
        changed_files = set(git("diff", "--name-only", merge_base).splitlines())
        plugin_changed = any(path.startswith("plugins/hermetiq/") for path in changed_files)
        if not plugin_changed:
            print(f"no distributable plugin changes; version remains {plugin_version}")
            return 0

        missing = REQUIRED_VERSION_FILES - changed_files
        if missing:
            raise CheckError(
                "changes under plugins/hermetiq/ must update both version manifests; "
                f"missing: {', '.join(sorted(missing))}"
            )

        base_plugin_version = version_at(merge_base, PLUGIN_MANIFEST, ("version",))
        base_marketplace_version = version_at(
            merge_base, MARKETPLACE_MANIFEST, ("plugin:hermetiq", "version")
        )
        base_metadata_version = version_at(
            merge_base, MARKETPLACE_MANIFEST, ("metadata", "version")
        )
        if len(
            {base_plugin_version, base_metadata_version, base_marketplace_version}
        ) != 1:
            raise CheckError(
                "baseline plugin and marketplace versions must match "
                f"(found {base_plugin_version!r}, {base_metadata_version!r}, and "
                f"{base_marketplace_version!r})"
            )
        if not SemVer.parse(base_plugin_version) < SemVer.parse(plugin_version):
            raise CheckError(
                f"plugin version {plugin_version} must be greater than baseline "
                f"{base_plugin_version}"
            )

        print(
            "distributable plugin changes carry a synchronized version bump: "
            f"{base_plugin_version} -> {plugin_version}"
        )
        return 0
    except CheckError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

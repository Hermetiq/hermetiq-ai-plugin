#!/usr/bin/env python3
"""Refresh the plugin's compact catalog from cloud-native's full fixture."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "plugins"
    / "hermetiq"
    / "skills"
    / "hermetiq"
    / "evals"
    / "canonical-mcp-catalog.json"
)
DEFAULT_SERVER_OUTPUT = (
    REPO_ROOT / "scripts" / "testdata" / "cloud-native-mcp-catalog.json.gz"
)
DEFAULT_PROVENANCE_OUTPUT = (
    REPO_ROOT
    / "scripts"
    / "testdata"
    / "cloud-native-mcp-catalog.provenance.json"
)
SOURCE = "Hermetiq/cloud-native/bep-nats/mcpv2/testdata/catalog/current.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-catalog", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--server-output", type=Path, default=DEFAULT_SERVER_OUTPUT)
    parser.add_argument(
        "--provenance-output", type=Path, default=DEFAULT_PROVENANCE_OUTPUT
    )
    return parser.parse_args()


def names(entries: list[Any], key: str = "name") -> list[str]:
    return sorted(entry if isinstance(entry, str) else entry[key] for entry in entries)


def main() -> int:
    args = parse_args()
    server_bytes = args.server_catalog.read_bytes()
    server = json.loads(server_bytes)
    current = json.loads(args.output.read_text(encoding="utf-8"))
    resources = names(server.get("resources", []), "uri")
    templates = names(server.get("resource_templates", []), "uriTemplate")
    snapshot = {
        "schemaVersion": 1,
        "source": SOURCE,
        "sourceRevision": args.source_revision,
        "server": server["server"],
        "serverVersion": server["version"],
        "tools": names(server["tools"]),
        "allowlist": {
            "prompts": names(server.get("prompts", [])),
            "resources": sorted([*resources, *templates]),
            "externalMcpTools": current.get("allowlist", {}).get(
                "externalMcpTools", []
            ),
        },
    }
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    args.server_output.parent.mkdir(parents=True, exist_ok=True)
    args.server_output.write_bytes(gzip.compress(server_bytes, compresslevel=9, mtime=0))
    provenance = {
        "source": SOURCE,
        "sourceRevision": args.source_revision,
        "sha256": hashlib.sha256(server_bytes).hexdigest(),
    }
    args.provenance_output.write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

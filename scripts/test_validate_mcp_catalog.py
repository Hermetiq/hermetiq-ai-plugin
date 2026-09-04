#!/usr/bin/env python3

from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate-mcp-catalog.py"
SERVER_FIXTURE = (
    REPO_ROOT / "scripts" / "testdata" / "cloud-native-mcp-catalog.json.gz"
)
SERVER_PROVENANCE = (
    REPO_ROOT
    / "scripts"
    / "testdata"
    / "cloud-native-mcp-catalog.provenance.json"
)


class CatalogValidatorTest(unittest.TestCase):
    def test_current_skill_matches_checked_in_catalog(self) -> None:
        completed = subprocess.run(
            [str(VALIDATOR)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_rejects_unknown_backticked_tool(self) -> None:
        completed = self.run_with_skill_suffix("\nCall `get_not_a_real_tool`.\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("absent from catalog: get_not_a_real_tool", completed.stderr)

    def test_rejects_legacy_alias(self) -> None:
        completed = self.run_with_skill_suffix("\nCall `GetInvocation`.\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("legacy MCP alias is forbidden: GetInvocation", completed.stderr)

    def test_rejects_legacy_alias_in_sibling_skill(self) -> None:
        completed = self.run_with_on_prem_skill_suffix(
            "\nCall `GetInfraHealthSummary`.\n"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "plugins/hermetiq/skills/on-prem-gke-install/SKILL.md: "
            "legacy MCP alias is forbidden: GetInfraHealthSummary",
            completed.stderr,
        )

    def test_rejects_retired_lowercase_tool_in_sibling_skill(self) -> None:
        completed = self.run_with_on_prem_skill_suffix(
            "\nCall `show_trends_dashboard`.\n"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "plugins/hermetiq/skills/on-prem-gke-install/SKILL.md: "
            "retired MCP tool is forbidden: show_trends_dashboard",
            completed.stderr,
        )

    def test_rejects_retired_prompt(self) -> None:
        completed = self.run_with_skill_suffix("\nUse `analyze_build`.\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("absent from catalog: analyze_build", completed.stderr)

    def test_rejects_server_fixture_provenance_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-mcp-provenance-test-") as directory:
            root = Path(directory)
            server_catalog = root / "server.json"
            server_catalog.write_bytes(gzip.decompress(SERVER_FIXTURE.read_bytes()))
            provenance = json.loads(SERVER_PROVENANCE.read_text(encoding="utf-8"))
            provenance["sourceRevision"] = "wrong-revision"
            provenance["sha256"] = "0" * 64
            provenance_path = root / "provenance.json"
            provenance_path.write_text(
                json.dumps(provenance), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    str(VALIDATOR),
                    "--server-catalog",
                    str(server_catalog),
                    "--server-provenance",
                    str(provenance_path),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("server catalog checksum drift", completed.stderr)
        self.assertIn(
            "server catalog provenance drift for sourceRevision", completed.stderr
        )

    def run_with_skill_suffix(self, suffix: str) -> subprocess.CompletedProcess[str]:
        return self.run_with_packaged_file_suffix("hermetiq/SKILL.md", suffix)

    def run_with_on_prem_skill_suffix(
        self, suffix: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_with_packaged_file_suffix(
            "on-prem-gke-install/SKILL.md", suffix
        )

    def run_with_packaged_file_suffix(
        self, relative_path: str, suffix: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="hermetiq-mcp-catalog-test-") as directory:
            root = Path(directory)
            shutil.copy2(REPO_ROOT / "README.md", root / "README.md")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            source_skills = REPO_ROOT / "plugins" / "hermetiq" / "skills"
            target_skills = root / "plugins" / "hermetiq" / "skills"
            shutil.copytree(source_skills, target_skills)
            target_file = target_skills / relative_path
            target_file.write_text(
                target_file.read_text(encoding="utf-8") + suffix,
                encoding="utf-8",
            )
            return subprocess.run(
                [str(root / "scripts" / "validate-mcp-catalog.py")],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )


if __name__ == "__main__":
    unittest.main()

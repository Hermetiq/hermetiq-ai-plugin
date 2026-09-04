#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate-mcp-catalog.py"
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

    def test_rejects_retired_prompt(self) -> None:
        completed = self.run_with_skill_suffix("\nUse `analyze_build`.\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("absent from catalog: analyze_build", completed.stderr)

    def run_with_skill_suffix(self, suffix: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="hermetiq-mcp-catalog-test-") as directory:
            root = Path(directory)
            shutil.copy2(REPO_ROOT / "README.md", root / "README.md")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            source_skill = REPO_ROOT / "plugins" / "hermetiq" / "skills" / "hermetiq"
            target_skill = root / "plugins" / "hermetiq" / "skills" / "hermetiq"
            shutil.copytree(source_skill, target_skill)
            skill_path = target_skill / "SKILL.md"
            skill_path.write_text(skill_path.read_text(encoding="utf-8") + suffix, encoding="utf-8")
            return subprocess.run(
                [str(root / "scripts" / "validate-mcp-catalog.py")],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )


if __name__ == "__main__":
    unittest.main()

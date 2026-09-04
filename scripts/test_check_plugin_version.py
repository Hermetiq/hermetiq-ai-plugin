#!/usr/bin/env python3

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "scripts" / "check-plugin-version.py"


class PluginVersionCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="hermetiq-plugin-version-test-"
        )
        self.root = Path(self.temporary_directory.name)
        (self.root / "plugins" / "hermetiq" / ".claude-plugin").mkdir(
            parents=True
        )
        (self.root / ".claude-plugin").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "plugins" / "hermetiq" / "skills" / "hermetiq").mkdir(
            parents=True
        )
        shutil.copy2(CHECKER, self.root / "scripts" / CHECKER.name)
        self.write_versions("1.2.0")
        self.skill.write_text("old guidance\n", encoding="utf-8")
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Version Check Test")
        self.git("config", "user.email", "version-check@example.invalid")
        self.commit("baseline")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @property
    def skill(self) -> Path:
        return self.root / "plugins" / "hermetiq" / "skills" / "hermetiq" / "SKILL.md"

    def write_versions(
        self,
        plugin_version: str,
        marketplace_version: str | None = None,
        metadata_version: str | None = None,
    ) -> None:
        marketplace_version = marketplace_version or plugin_version
        metadata_version = metadata_version or marketplace_version
        plugin_manifest = {
            "name": "hermetiq",
            "version": plugin_version,
        }
        marketplace = {
            "name": "hermetiq",
            "metadata": {"version": metadata_version},
            "plugins": [
                {
                    "name": "hermetiq",
                    "source": "./plugins/hermetiq",
                    "version": marketplace_version,
                }
            ],
        }
        self.plugin_manifest.write_text(
            json.dumps(plugin_manifest) + "\n", encoding="utf-8"
        )
        self.marketplace_manifest.write_text(
            json.dumps(marketplace) + "\n", encoding="utf-8"
        )

    @property
    def plugin_manifest(self) -> Path:
        return self.root / "plugins" / "hermetiq" / ".claude-plugin" / "plugin.json"

    @property
    def marketplace_manifest(self) -> Path:
        return self.root / ".claude-plugin" / "marketplace.json"

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def check(self, base: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(self.root / "scripts" / CHECKER.name),
                "--base-ref",
                base,
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_plugin_change_with_synchronized_version_bump(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.skill.write_text("new guidance\n", encoding="utf-8")
        self.write_versions("1.3.0")
        self.commit("update plugin")

        completed = self.check(base)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1.2.0 -> 1.3.0", completed.stdout)

    def test_rejects_plugin_change_without_version_bump(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.skill.write_text("new guidance\n", encoding="utf-8")
        self.commit("update plugin")

        completed = self.check(base)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("must update both version manifests", completed.stderr)

    def test_rejects_plugin_change_when_only_plugin_manifest_changes(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.skill.write_text("new guidance\n", encoding="utf-8")
        self.write_versions("1.3.0", marketplace_version="1.2.0")
        self.commit("partially update plugin")

        completed = self.check(base)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("must match", completed.stderr)

    def test_rejects_non_increasing_version(self) -> None:
        base = self.git("rev-parse", "HEAD").stdout.strip()
        self.skill.write_text("new guidance\n", encoding="utf-8")
        self.write_versions("1.1.0")
        self.commit("downgrade plugin")

        completed = self.check(base)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("must be greater than", completed.stderr)

    def test_rejects_version_reused_on_diverged_current_base(self) -> None:
        self.git("switch", "-c", "candidate")
        self.skill.write_text("candidate guidance\n", encoding="utf-8")
        self.write_versions("1.3.0")
        self.commit("candidate plugin update")
        self.git("switch", "main")
        self.write_versions("1.3.0")
        self.commit("independent base version bump")
        self.git("switch", "candidate")

        completed = self.check("main")

        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "plugin version 1.3.0 must be greater than baseline 1.3.0",
            completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()

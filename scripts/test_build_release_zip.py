#!/usr/bin/env python3

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseZipTest(unittest.TestCase):
    def test_release_contains_one_archive_for_each_supported_manual_skill(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-release-test-") as directory:
            root = Path(directory)
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")

            completed = subprocess.run(
                [str(root / "scripts" / "build-release-zip.sh"), "v-test"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            release_directory = root / "tmp" / "release-v-test"
            expected_skills = {
                "hermetiq-ai-plugin-v-test.zip": "hermetiq",
                "hermetiq-on-prem-gke-install-v-test.zip": "on-prem-gke-install",
            }
            self.assertEqual(
                {path.name for path in release_directory.glob("*.zip")},
                set(expected_skills),
            )
            for archive_name, skill_name in expected_skills.items():
                with zipfile.ZipFile(release_directory / archive_name) as archive:
                    names = archive.namelist()
                self.assertIn(f"{skill_name}/SKILL.md", names)
                self.assertTrue(
                    all(name.startswith(f"{skill_name}/") for name in names), names
                )
                self.assertFalse(any("/evals/" in name for name in names), names)


if __name__ == "__main__":
    unittest.main()

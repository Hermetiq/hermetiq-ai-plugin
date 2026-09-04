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
            root = Path(directory) / "repository"
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")

            completed = subprocess.run(
                [str(root / "scripts" / "build-release-zip.sh"), "v9.9.9-test"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            release_directory = root / "tmp" / "release-v9.9.9-test"
            expected_skills = {
                "hermetiq-ai-plugin-v9.9.9-test.zip": "hermetiq",
                "hermetiq-on-prem-gke-install-v9.9.9-test.zip": "on-prem-gke-install",
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

    def test_rejects_path_traversal_version_before_deleting_anything(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-release-test-") as directory:
            sandbox = Path(directory)
            root = sandbox / "repository"
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            traversal_target = sandbox / "plugins"
            traversal_target.mkdir()
            sentinel = traversal_target / "must-survive.txt"
            sentinel.write_text("keep me\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    str(root / "scripts" / "build-release-zip.sh"),
                    "x/../../../plugins",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("valid release tag", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me\n")
            self.assertFalse((root / "tmp").exists())

    def test_rejects_stage_symlink_that_resolves_outside_repo_tmp(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-release-test-") as directory:
            sandbox = Path(directory)
            root = sandbox / "repository"
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            outside = sandbox / "outside"
            outside.mkdir()
            sentinel = outside / "must-survive.txt"
            sentinel.write_text("keep me\n", encoding="utf-8")
            (root / "tmp").mkdir()
            (root / "tmp" / "release-v9.9.9-test").symlink_to(
                outside, target_is_directory=True
            )

            completed = subprocess.run(
                [
                    str(root / "scripts" / "build-release-zip.sh"),
                    "v9.9.9-test",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("stage path is a symlink", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me\n")

    def test_rejects_stage_symlink_that_resolves_inside_repo_tmp(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-release-test-") as directory:
            root = Path(directory) / "repository"
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            tmp_root = root / "tmp"
            tmp_root.mkdir()
            sibling_stage = tmp_root / "sibling-stage"
            sibling_stage.mkdir()
            sentinel = sibling_stage / "must-survive.txt"
            sentinel.write_text("keep me\n", encoding="utf-8")
            (tmp_root / "release-v9.9.9-test").symlink_to(
                sibling_stage, target_is_directory=True
            )

            completed = subprocess.run(
                [
                    str(root / "scripts" / "build-release-zip.sh"),
                    "v9.9.9-test",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("stage path is a symlink", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me\n")

    def test_rejects_symlinked_repo_tmp_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hermetiq-release-test-") as directory:
            sandbox = Path(directory)
            root = sandbox / "repository"
            shutil.copytree(REPO_ROOT / "plugins", root / "plugins")
            shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
            outside_tmp = sandbox / "outside-tmp"
            stage = outside_tmp / "release-v9.9.9-test"
            stage.mkdir(parents=True)
            sentinel = stage / "must-survive.txt"
            sentinel.write_text("keep me\n", encoding="utf-8")
            (root / "tmp").symlink_to(outside_tmp, target_is_directory=True)

            completed = subprocess.run(
                [
                    str(root / "scripts" / "build-release-zip.sh"),
                    "v9.9.9-test",
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("tmp root is a symlink", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me\n")


if __name__ == "__main__":
    unittest.main()

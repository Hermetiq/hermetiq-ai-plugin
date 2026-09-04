#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = REPO_ROOT / "scripts" / "validate-bazel-guidance.py"
SPEC = importlib.util.spec_from_file_location("validate_bazel_guidance", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
GUIDANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUIDANCE)


class BazelVersionGuidanceTest(unittest.TestCase):
    def test_uses_experimental_compression_name_for_bazel_5_and_6(self) -> None:
        for version in ("5.4.1", "release 6.5.0", "6.0.0rc3"):
            with self.subTest(version=version):
                self.assertEqual(
                    GUIDANCE.compression_flag_for_version(version),
                    "--experimental_remote_cache_compression",
                )

    def test_uses_canonical_compression_name_for_bazel_7_through_9(self) -> None:
        for version in ("7.0.0", "release 8.5.0", "bazel 9.0.0-pre.20260820.1"):
            with self.subTest(version=version):
                self.assertEqual(
                    GUIDANCE.compression_flag_for_version(version),
                    "--remote_cache_compression",
                )

    def test_rejects_compression_recommendation_without_a_supported_version(self) -> None:
        for version in (None, "", "development version", "4.2.4", "10.0.0"):
            with self.subTest(version=version):
                self.assertIsNone(GUIDANCE.compression_flag_for_version(version))

    def test_rejects_flags_that_are_wrong_for_the_bazel_version(self) -> None:
        cases = (
            ("--remote_cache_compression", "5.4.1"),
            ("--experimental_remote_cache_compression", "7.0.0"),
            ("--incompatible_strict_action_env", "9.0.0"),
            ("--noexperimental_check_external_repository_files", "6.5.0"),
            ("--noexperimental_check_external_repository_files", "9.0.0"),
            ("--remote_timeout", "4.2.4"),
            ("--remote_timeout", "10.0.0"),
        )
        for flag, version in cases:
            with self.subTest(flag=flag, version=version):
                self.assertFalse(GUIDANCE.flag_is_recommended(flag, version))

    def test_accepts_supported_stable_flags(self) -> None:
        for version in ("5.4.1", "6.5.0", "7.6.0", "8.5.0", "9.0.0"):
            with self.subTest(version=version):
                self.assertTrue(GUIDANCE.flag_is_recommended("--remote_timeout", version))

    def test_copyable_blocks_never_mix_compression_flag_versions(self) -> None:
        guidance = (
            REPO_ROOT
            / "plugins"
            / "hermetiq"
            / "skills"
            / "hermetiq"
            / "references"
            / "bazel-optimization.md"
        ).read_text(encoding="utf-8")
        blocks = re.findall(r"```bazelrc\n(.*?)```", guidance, flags=re.DOTALL)
        self.assertGreater(len(blocks), 1)
        for block in blocks:
            with self.subTest(block=block):
                self.assertFalse(
                    "--experimental_remote_cache_compression" in block
                    and "--remote_cache_compression" in block
                )

    def test_stamp_audit_treats_absent_flag_as_disabled_default(self) -> None:
        guidance = (
            REPO_ROOT
            / "plugins"
            / "hermetiq"
            / "skills"
            / "hermetiq"
            / "references"
            / "build-configuration.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("absence of `--nostamp`", guidance)
        self.assertNotIn("Recommendation: use `--nostamp` as the default", guidance)
        self.assertIn("last-wins", guidance)
        self.assertIn("no stamp flag is present", guidance)

    def test_customer_facing_guidance_matches_policy(self) -> None:
        completed = subprocess.run(
            [str(VALIDATOR)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()

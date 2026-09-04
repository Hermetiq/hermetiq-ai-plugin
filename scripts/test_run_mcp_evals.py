#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().with_name("run-mcp-evals.py")
SPEC = importlib.util.spec_from_file_location("run_mcp_evals", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class FinalPatternFailuresTest(unittest.TestCase):
    def test_accepts_required_patterns_and_absent_forbidden_patterns(self) -> None:
        case = {
            "expectedFinalPatterns": [r"wallTimeSeconds", r"remote error.*general"],
            "forbiddenFinalPatterns": [r"buildWallTimeMicros"],
        }

        missing, forbidden = RUNNER.final_pattern_failures(
            case,
            "wallTimeSeconds is exposed; remote error is a general outcome.",
        )

        self.assertEqual(missing, [])
        self.assertEqual(forbidden, [])

    def test_reports_missing_and_forbidden_patterns(self) -> None:
        case = {
            "expectedFinalPatterns": [r"wallTimeSeconds"],
            "forbiddenFinalPatterns": [r"buildWallTimeMicros"],
        }

        missing, forbidden = RUNNER.final_pattern_failures(case, "Use buildWallTimeMicros.")

        self.assertEqual(missing, [r"wallTimeSeconds"])
        self.assertEqual(forbidden, [r"buildWallTimeMicros"])


if __name__ == "__main__":
    unittest.main()

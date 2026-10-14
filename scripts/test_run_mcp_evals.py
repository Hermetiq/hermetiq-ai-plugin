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


class BuildHistoryContractTest(unittest.TestCase):
    current_response = (
        "The response summarizes logical builds: totalBuildCount=10, successCount=5, "
        "failureCount=2, interruptedCount=1, inProgressCount=1, unknownCount=1. "
        "unknownCount counts finished builds without a recorded exit code. "
        "The five outcome counters sum to totalBuildCount. "
        "invocationCount is absent here; BuildSummary uses it for the invocations "
        "within one build."
    )

    def setUp(self) -> None:
        suite = RUNNER.load_json(RUNNER.DEFAULT_SUITE)
        self.case = next(
            case for case in suite["evals"]
            if case["id"] == "build-history-response-contract"
        )

    def test_accepts_current_mcp_outcome_contract(self) -> None:
        missing, forbidden = RUNNER.final_pattern_failures(
            self.case, self.current_response
        )

        self.assertEqual(missing, [])
        self.assertEqual(forbidden, [])

    def test_rejects_obsolete_unknown_count_absence_claim(self) -> None:
        for claim in (
            "unknownCount is absent.",
            "unknownCount is not returned.",
            "The response does not include unknownCount.",
        ):
            with self.subTest(claim=claim):
                _, forbidden = RUNNER.final_pattern_failures(
                    self.case, self.current_response + " " + claim
                )

                self.assertTrue(forbidden)

    def test_rejects_invocation_count_as_history_outcome_total(self) -> None:
        missing, _ = RUNNER.final_pattern_failures(
            self.case,
            self.current_response.replace(
                "sum to totalBuildCount", "sum to invocationCount"
            ),
        )

        self.assertTrue(missing)


if __name__ == "__main__":
    unittest.main()

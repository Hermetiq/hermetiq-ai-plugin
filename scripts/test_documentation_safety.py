import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "plugins" / "hermetiq" / "skills"

COMMAND_END = r"(?=[\s`.,;:)]|$)"
ENABLED_ALL = r"--all(?:=(?i:true|t|1))?" + COMMAND_END

DESTRUCTIVE_WILDCARD_PATTERNS = {
    "kubectl delete --all": re.compile(r"\bkubectl\b[^\n`]*\bdelete\b[^\n`]*\s" + ENABLED_ALL),
    "helm uninstall --all": re.compile(r"\bhelm\b[^\n`]*\buninstall\b[^\n`]*\s" + ENABLED_ALL),
    "recursive rm wildcard": re.compile(r"\brm\s+-(?:rf|fr)\s+(?:\*|\./\*|\.|\./|/|/\*)" + COMMAND_END),
    "docker system prune -a": re.compile(r"\bdocker\s+system\s+prune\b[^\n`]*\s-a" + COMMAND_END),
    "gcloud delete --all": re.compile(r"\bgcloud\b[^\n`]*\bdelete\b[^\n`]*\s" + ENABLED_ALL),
}


def logical_lines(text: str):
    """Yield shell-continuation-aware text with its first physical line."""
    start_line = 1
    buffer = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not buffer:
            start_line = line_number
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        yield start_line, buffer + line
        buffer = ""
    if buffer:
        yield start_line, buffer


def documentation_safety_failures_from_text(text: str, display_path: str) -> list[str]:
    failures = []
    for line_number, line in logical_lines(text):
        for description, pattern in DESTRUCTIVE_WILDCARD_PATTERNS.items():
            if pattern.search(line):
                failures.append(f"{display_path}:{line_number}: {description}")
    return failures


def documentation_safety_failures(path: Path) -> list[str]:
    return documentation_safety_failures_from_text(
        path.read_text(),
        str(path.relative_to(REPO_ROOT)),
    )


class DocumentationSafetyTest(unittest.TestCase):
    def test_detector_rejects_destructive_wildcard_examples(self):
        examples = [
            "`kubectl -n demo delete rbeworker --all`.",
            "kubectl delete pods --all=true",
            "kubectl delete pods --all=TRUE",
            "kubectl delete pods \\\n+              --all",
            "helm uninstall --all",
            "rm -rf *",
            "rm -rf ./*",
            "rm -fr /",
            "docker system prune -a",
            "gcloud compute instances delete --all=1",
        ]

        for example in examples:
            with self.subTest(example=example):
                self.assertTrue(
                    documentation_safety_failures_from_text(example, "example.md"),
                    example,
                )

    def test_disabled_all_flag_is_not_reported(self):
        self.assertEqual(
            [],
            documentation_safety_failures_from_text(
                "kubectl delete pods --all=false",
                "example.md",
            ),
        )

    def test_customer_facing_skills_have_no_destructive_wildcards(self):
        failures = []
        for path in sorted(SKILLS_ROOT.rglob("*.md")):
            failures.extend(documentation_safety_failures(path))

        self.assertEqual([], failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()

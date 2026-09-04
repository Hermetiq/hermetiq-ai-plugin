import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "plugins" / "hermetiq" / "skills"

COMMAND_END = r"(?=[\s`.,;:)]|$)"

DESTRUCTIVE_WILDCARD_PATTERNS = {
    "kubectl delete --all": re.compile(r"\bkubectl\b[^\n`]*\bdelete\b[^\n`]*\s--all" + COMMAND_END),
    "helm uninstall --all": re.compile(r"\bhelm\b[^\n`]*\buninstall\b[^\n`]*\s--all" + COMMAND_END),
    "recursive rm wildcard": re.compile(r"\brm\s+-rf\s+(?:\*|\.(?:/)?)" + COMMAND_END),
    "docker system prune -a": re.compile(r"\bdocker\s+system\s+prune\b[^\n`]*\s-a" + COMMAND_END),
    "gcloud delete --all": re.compile(r"\bgcloud\b[^\n`]*\bdelete\b[^\n`]*\s--all" + COMMAND_END),
}


def documentation_safety_failures(path: Path) -> list[str]:
    failures = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        for description, pattern in DESTRUCTIVE_WILDCARD_PATTERNS.items():
            if pattern.search(line):
                failures.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {description}")
    return failures


class DocumentationSafetyTest(unittest.TestCase):
    def test_detector_rejects_destructive_wildcard_examples(self):
        examples = {
            "kubectl delete --all": "`kubectl -n demo delete rbeworker --all`.",
            "helm uninstall --all": "helm uninstall --all",
            "recursive rm wildcard": "rm -rf *",
            "docker system prune -a": "docker system prune -a",
            "gcloud delete --all": "gcloud compute instances delete --all",
        }

        for description, example in examples.items():
            with self.subTest(description=description):
                self.assertRegex(example, DESTRUCTIVE_WILDCARD_PATTERNS[description])

    def test_customer_facing_skills_have_no_destructive_wildcards(self):
        failures = []
        for path in sorted(SKILLS_ROOT.rglob("*.md")):
            failures.extend(documentation_safety_failures(path))

        self.assertEqual([], failures, "\n".join(failures))


if __name__ == "__main__":
    unittest.main()

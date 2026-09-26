from pathlib import Path


def test_branch_head_final_run_invalid_conditions_are_explicit():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    for phrase in ("confirmation is ambiguous", "record remains pending", "unrelated tab", "unknown answers were guessed", "second submission remains possible"):
        assert phrase in runbook

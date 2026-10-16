"""JT5 attempt outcome tests.

The final-action uncertainty rule is intentional: a browser error after the
possible final click is never an automatic retry.
"""
import pytest

from app.services.application_attempt_lifecycle_jt5 import complete_jt5_attempt
from app.models.submission_integrity import SubmissionAttemptStatus


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("confirmed", SubmissionAttemptStatus.succeeded),
        ("failed_pre_submit", SubmissionAttemptStatus.failed),
        ("submission_uncertain", SubmissionAttemptStatus.uncertain),
    ],
)
def test_outcome_status_mapping(monkeypatch, outcome, expected):
    calls = []

    def fake_finalize(db, attempt, *, status, result):
        calls.append((status, result))
        return attempt

    monkeypatch.setattr(
        "app.services.application_attempt_lifecycle_jt5.finalize_submission_attempt",
        fake_finalize,
    )
    marker = object()
    assert complete_jt5_attempt(None, marker, outcome=outcome) is marker
    assert calls == [(expected, {"outcome": outcome})]


def test_unknown_outcome_never_marks_success():
    with pytest.raises(ValueError, match="invalid_jt5_outcome"):
        complete_jt5_attempt(None, object(), outcome="success")

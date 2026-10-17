"""Regression: approval expiry comparisons require timezone-aware UTC."""

from datetime import datetime, timezone

from app.services.time_utils import utc_now


def test_utc_now_is_timezone_aware():
    now = utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo.utcoffset(now) is not None


def test_aware_vs_aware_comparison_does_not_raise():
    left = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    right = utc_now()
    # Must not raise TypeError
    _ = left <= right
    _ = right <= left + (right - left)


def test_naive_vs_aware_would_raise():
    naive = datetime.utcnow()
    aware = utc_now()
    raised = False
    try:
        _ = naive <= aware
    except TypeError:
        raised = True
    assert raised, "expected TypeError when comparing naive to aware"

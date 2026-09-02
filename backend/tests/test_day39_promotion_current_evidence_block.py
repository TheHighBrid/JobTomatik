import json
from pathlib import Path


def test_current_retained_lever_evidence_is_not_promotion_ready():
    readiness = json.loads(
        Path("evidence/lever-pilot-readiness.json").read_text(encoding="utf-8")
    )
    summary = readiness["summary"]

    assert summary["qualifying_dry_run_count"] >= 30
    assert summary["supervised_confirmed_count"] == 0
    assert summary["gates"]["ten_supervised_confirmed_submissions"] is False
    assert summary["promotion_ready"] is False
    assert summary["canonical_maturity"] == "dry_run"

import csv
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.lever_target_corpus import (
    LeverTargetCorpusError,
    certify_target_corpus,
    load_target_corpus,
    review_digest,
    validate_target_corpus,
)


ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "backend/evidence/lever-phase-a-target-corpus.csv"


def _rows():
    return load_target_corpus(CORPUS_PATH)


def _rehash(row):
    row["review_digest_sha256"] = review_digest(row)
    return row


def test_committed_corpus_passes_day_8_gate():
    report = certify_target_corpus(CORPUS_PATH)
    summary = report["summary"]

    assert summary["passed"] is True
    assert summary["reviewed_posting_count"] == 44
    assert summary["active_reviewed_posting_count"] == 40
    assert summary["viable_posting_count"] == 39
    assert summary["distinct_viable_site_count"] == 39
    assert summary["viable_region_counts"] == {"eu": 7, "global": 32}
    assert summary["regions_covered"] == ["eu", "global"]
    assert len(report["excluded_targets"]) == 5
    assert report["safety"] == {
        "network_contacted_by_certifier": False,
        "browser_opened_by_certifier": False,
        "application_data_entered": False,
        "final_submit_clicked": False,
        "approval_issued": False,
        "maturity_promoted": False,
    }


def test_duplicate_viable_site_fails_closed():
    rows = _rows()
    duplicate = deepcopy(rows[0])
    duplicate["review_id"] = "D8-DUPLICATE"
    duplicate["posting_id"] = "11111111-1111-4111-8111-111111111111"
    duplicate["posting_url"] = f"https://jobs.lever.co/{duplicate['site']}/{duplicate['posting_id']}"
    duplicate["canonical_application_url"] = duplicate["posting_url"] + "/apply"
    _rehash(duplicate)
    with pytest.raises(LeverTargetCorpusError, match="Duplicate"):
        validate_target_corpus(rows + [duplicate])


def test_inactive_row_cannot_be_viable():
    rows = _rows()
    rows[0]["active"] = "False"
    _rehash(rows[0])
    with pytest.raises(LeverTargetCorpusError, match="Inactive row cannot be viable"):
        validate_target_corpus(rows)


def test_generic_application_cannot_be_viable():
    rows = _rows()
    generic = next(row for row in rows if row["site"] == "lionbridge")
    generic["viable"] = "True"
    generic["exclusion_reason"] = ""
    _rehash(generic)
    with pytest.raises(LeverTargetCorpusError, match="Generic application"):
        validate_target_corpus(rows)


def test_review_digest_tampering_is_rejected():
    rows = _rows()
    rows[0]["role"] = "Tampered title"
    with pytest.raises(LeverTargetCorpusError, match="Review digest mismatch"):
        validate_target_corpus(rows)


def test_wrong_host_for_region_is_rejected():
    rows = _rows()
    eu = next(row for row in rows if row["region"] == "eu" and row["viable"] == "True")
    eu["posting_url"] = eu["posting_url"].replace("jobs.eu.lever.co", "jobs.lever.co")
    _rehash(eu)
    with pytest.raises(LeverTargetCorpusError, match="Posting URL does not match"):
        validate_target_corpus(rows)


def test_excluded_row_requires_reason():
    rows = _rows()
    excluded = next(row for row in rows if row["viable"] == "False")
    excluded["exclusion_reason"] = ""
    _rehash(excluded)
    with pytest.raises(LeverTargetCorpusError, match="explicit reason"):
        validate_target_corpus(rows)


def test_schema_order_is_locked(tmp_path):
    rows = _rows()
    bad_path = tmp_path / "bad.csv"
    fieldnames = list(rows[0])
    fieldnames[0], fieldnames[1] = fieldnames[1], fieldnames[0]
    with bad_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(LeverTargetCorpusError, match="columns"):
        load_target_corpus(bad_path)

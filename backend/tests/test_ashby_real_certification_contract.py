from pathlib import Path


def test_ashby_real_certification_requires_native_runtime_evidence():
    contract = (
        Path(__file__).parents[2] / "docs" / "ASHBY_REAL_CERTIFICATION.md"
    ).read_text(encoding="utf-8")

    assert "Status: IN PROGRESS" in contract
    assert "retained native Chrome runtime" in contract
    assert "persist confirmation evidence" in contract
    assert "reconcile the JobTomatik application to `applied`" in contract
    assert "prevent another submission attempt" in contract
    assert "Missing or ambiguous confirmation must remain pending/manual review" in contract
    assert "Unknown answers must not be invented" in contract
    assert "CAPTCHA/MFA remains a manual boundary" in contract
    assert "must not silently select an unrelated browser tab" in contract


def test_ashby_adapter_does_not_claim_real_certification_early():
    source = (
        Path(__file__).parents[1] / "app" / "services" / "ats_ashby.py"
    ).read_text(encoding="utf-8")

    assert 'certification_level = "fixture_pending_live_certification"' in source
    assert '"mode": "not_yet_certified"' in source
    assert '"final_submit_clicked": False' in source

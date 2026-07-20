from app.services.ats_base import ATSFlowResult
from app.services.form_filler_handoff import (
    _promote_deferred_captcha_boundary,
    _resumable_boundary,
)


def test_deferred_captcha_is_promoted_when_field_review_ends_flow_first():
    flow = ATSFlowResult(
        requires_manual_review=True,
        error="Required application fields need review before the ATS flow can continue.",
        fields_filled=20,
        steps_completed=1,
        review_items=[{
            "reason_code": "ambiguous_question",
            "summary": "One required field needs manual review.",
            "details": {"descriptor": "Example required field"},
        }],
        control_evidence=[{"control_id": f"jt-{index}"} for index in range(9)],
        upload_evidence=[{"upload_type": "resume"}],
        adapter_name="greenhouse",
        adapter_version="1.1.1",
    )
    log = [{
        "action": "captcha_widget_deferred_until_manual_handoff",
        "adapter": "greenhouse",
        "step": 1,
        "submit_clicked": False,
    }]

    _promote_deferred_captcha_boundary(flow, log)

    reasons = [item["reason_code"] for item in flow.review_items]
    assert reasons == ["ambiguous_question", "captcha_detected"]
    captcha = flow.review_items[-1]
    assert captcha["details"]["promoted_from_deferred_challenge"] is True
    assert captcha["details"]["fields_filled"] == 20
    assert captcha["details"]["control_evidence_count"] == 9
    assert captcha["details"]["upload_evidence_count"] == 1
    assert _resumable_boundary(flow.as_dict()) is True
    assert any(
        item.get("action") == "ats_deferred_challenge_promoted_for_handoff"
        for item in log
    )


def test_promotion_is_idempotent_and_requires_deferred_challenge_evidence():
    flow = ATSFlowResult(
        requires_manual_review=True,
        error="A field needs review.",
        review_items=[{"reason_code": "ambiguous_question", "details": {}}],
    )

    _promote_deferred_captcha_boundary(flow, [])
    assert [item["reason_code"] for item in flow.review_items] == ["ambiguous_question"]
    assert _resumable_boundary(flow.as_dict()) is False

    log = [{"action": "captcha_widget_deferred_until_manual_handoff", "step": 1}]
    _promote_deferred_captcha_boundary(flow, log)
    _promote_deferred_captcha_boundary(flow, log)

    assert [item["reason_code"] for item in flow.review_items].count("captcha_detected") == 1

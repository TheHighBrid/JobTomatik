from __future__ import annotations

import pytest

from scripts import certify_lever_live


@pytest.mark.asyncio
async def test_exercise_serializes_per_control_evidence_and_separate_policy_count(
    monkeypatch,
):
    profile_evidence = {
        "action": "control_verified",
        "control_id": "jt-text-1",
        "control_type": "email",
        "descriptor": "Email",
        "canonical_key": "profile.email",
        "policy_id": None,
        "selected": [],
        "options_fingerprint": "a" * 16,
        "verification": "passed",
        "pass": 1,
        "source": "profile",
        "value_redacted": True,
    }
    policy_evidence = {
        "action": "control_verified",
        "control_id": "jt-text-2",
        "control_type": "textarea",
        "descriptor": "Why this role?",
        "canonical_key": "why_this_role",
        "policy_id": 7,
        "selected": [],
        "options_fingerprint": "b" * 16,
        "verification": "passed",
        "pass": 1,
        "source": "answer_policy",
        "value_redacted": True,
    }
    structured_evidence = {
        "action": "control_verified",
        "control_id": "jt-3",
        "control_type": "radio",
        "descriptor": "Authorized to work?",
        "canonical_key": "work_authorization",
        "policy_id": 8,
        "selected": [{"label": "Yes", "value": "yes"}],
        "options_fingerprint": "c" * 16,
        "verification": "passed",
        "pass": 1,
    }

    async def fake_fill_and_submit_application(**_kwargs):
        return {
            "success": True,
            "ready_to_submit": True,
            "ats_adapter": "lever",
            "ats_adapter_version": "1.1.0",
            "requires_manual_review": False,
            "steps_completed": 1,
            "fields_filled": 3,
            "review_items": [],
            "validation_errors": [],
            "upload_evidence": [{"verification": "passed"}],
            "step_evidence": [],
            "control_evidence": [
                profile_evidence,
                policy_evidence,
                structured_evidence,
            ],
            "log": [],
            "error": None,
        }

    monkeypatch.setattr(
        certify_lever_live,
        "fill_and_submit_application",
        fake_fill_and_submit_application,
    )
    report = await certify_lever_live.exercise_live_url(
        "https://jobs.lever.co/example/00000000-0000-0000-0000-000000000000/apply",
        profile={},
        resume_path="synthetic.pdf",
        cover_letter="",
        certification_metadata={"synthetic_profile": True},
    )

    assert report["control_evidence_schema_version"] == "1.0"
    assert report["control_evidence_count"] == 3
    assert report["policy_evidence_count"] == 2
    assert report["control_evidence"] == [
        profile_evidence,
        policy_evidence,
        structured_evidence,
    ]

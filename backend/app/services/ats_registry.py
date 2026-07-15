"""ATS adapter registry and certification manifest."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ats_base import ATSAdapter
from app.services.ats_greenhouse import GreenhouseAdapter
from app.services.ats_lever import LeverAdapter


_ADAPTERS = [GreenhouseAdapter(), LeverAdapter()]
_GENERIC = ATSAdapter()


async def detect_ats_adapter(page: Any, url: str) -> ATSAdapter:
    for adapter in _ADAPTERS:
        try:
            if await adapter.matches(page, url):
                return adapter
        except Exception:
            continue
    return _GENERIC


def ats_certification_manifest() -> Dict[str, Any]:
    adapters: List[Dict[str, Any]] = [adapter.manifest() for adapter in _ADAPTERS]
    return {
        "framework_version": "1.1.0",
        "certification_model": "standards fixtures plus supervised live dry-runs",
        "adapters": adapters,
        "safety_invariants": {
            "live_submission_disabled_by_default": True,
            "final_submit_not_clicked_during_live_certification": True,
            "captcha_and_mfa_are_manual": True,
            "unknown_required_controls_fail_closed": True,
            "confirmation_evidence_required_for_submitted_state": True,
            "step_navigation_verified_after_field_mutation": True,
            "step_evidence_persisted_in_automation_log": True,
            "official_api_gaps_are_reported_not_guessed": True,
        },
        "universal_boundary": (
            "Each ATS adapter must pass local fixtures and supervised live dry-runs. "
            "No finite suite can certify every employer customization or future control."
        ),
    }

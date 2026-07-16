"""ATS adapter registry and certification manifest."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ashby_profile_aliases import install_ashby_profile_aliases
from app.services.ats_ashby import AshbyAdapter
from app.services.ats_base import ATSAdapter
from app.services.ats_greenhouse import GreenhouseAdapter
from app.services.ats_lever import LeverAdapter
from app.services.ats_smartrecruiters import SmartRecruitersAdapter


install_ashby_profile_aliases()


class RegisteredLeverAdapter(LeverAdapter):
    """Lever implementation after fixture, live-form, and handoff validation."""

    version = "1.1.0"
    certification_level = "fixture_live_inspection_synthetic_and_handoff_certified"

    def manifest(self) -> Dict[str, Any]:
        value = super().manifest()
        value["version"] = self.version
        value["certification_level"] = self.certification_level
        value["live_certification"] = {
            "mode": "public_inspection_synthetic_full_form_and_resumable_handoff",
            "public_form_smoke": "certified",
            "synthetic_full_form_exercise": "certified",
            "resumable_handoff": "certified",
            "accepted_safe_outcomes": [
                "ready_to_submit",
                "manual_challenge_handoff",
            ],
            "latest_certified_boundary": "dry_run_pre_submit_or_manual_challenge",
            "official_metadata_verified": True,
            "custom_questions_verified_from_hosted_dom": True,
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        }
        return value


class RegisteredAshbyAdapter(AshbyAdapter):
    """Ashby implementation after fixture, live-form, and handoff validation."""

    version = "1.1.0"
    certification_level = "fixture_live_inspection_synthetic_and_handoff_certified"

    def manifest(self) -> Dict[str, Any]:
        value = super().manifest()
        value["version"] = self.version
        value["certification_level"] = self.certification_level
        value["live_certification"] = {
            "mode": "public_inspection_synthetic_full_form_and_resumable_handoff",
            "public_form_smoke": "certified",
            "synthetic_full_form_exercise": "certified",
            "resumable_handoff": "certified",
            "accepted_safe_outcomes": [
                "ready_to_submit",
                "manual_challenge_handoff",
            ],
            "latest_certified_boundary": "dry_run_pre_submit_or_manual_challenge",
            "public_board_metadata_verified": True,
            "hosted_dom_controls_verified": True,
            "credentialed_form_definition_support": "fixture_certified_optional_runtime_validation",
            "official_form_field_types_verified": True,
            "exact_name_system_field_alias_verified": True,
            "verified_resume_upload": True,
            "final_submit_clicked": False,
        }
        return value


_ADAPTERS = [
    GreenhouseAdapter(),
    RegisteredLeverAdapter(),
    RegisteredAshbyAdapter(),
    SmartRecruitersAdapter(),
]
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
        "framework_version": "1.3.0",
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
            "private_api_credentials_not_required_for_public_form_ci": True,
            "exact_ashby_name_alias_only": True,
            "smartrecruiters_application_api_requires_explicit_token": True,
        },
        "universal_boundary": (
            "Each ATS adapter must pass local fixtures and supervised live dry-runs. "
            "No finite suite can certify every employer customization or future control."
        ),
    }

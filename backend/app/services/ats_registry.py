"""ATS adapter registry and certification manifest."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ashby_profile_aliases import install_ashby_profile_aliases
from app.services.ats_ashby import AshbyAdapter
from app.services.ats_base import ATSAdapter
from app.services.ats_greenhouse import GreenhouseAdapter
from app.services.ats_lever import LeverAdapter
from app.services.ats_smartrecruiters import SmartRecruitersAdapter
from app.services.ats_workday import WorkdayAdapter
from app.services.smartrecruiters_challenge import (
    install_smartrecruiters_challenge_detection,
)
from app.services.smartrecruiters_contract import (
    install_smartrecruiters_contract_normalization,
)
from app.services.workday_challenge import install_workday_challenge_detection
from app.services.workday_port_integration import install_workday_port_integration


install_ashby_profile_aliases()
install_smartrecruiters_contract_normalization()
install_smartrecruiters_challenge_detection()
install_workday_port_integration()
install_workday_challenge_detection()


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


class RegisteredSmartRecruitersAdapter(SmartRecruitersAdapter):
    """SmartRecruiters after fixture and current pre-form boundary validation."""

    version = "1.1.0"
    certification_level = "fixture_live_metadata_preform_handoff_and_resume_certified"

    def manifest(self) -> Dict[str, Any]:
        value = super().manifest()
        value["version"] = self.version
        value["certification_level"] = self.certification_level
        value["live_certification"] = {
            "mode": "public_metadata_preform_antibot_handoff_and_fixture_full_form",
            "public_posting_metadata": "certified",
            "current_live_sample": {
                "posting_count": 3,
                "company_count": 2,
                "companies": ["Visa", "NielsenIQ"],
                "certified_boundary": "pre_form_anti_bot_handoff",
            },
            "live_hosted_form_controls": "not_reached_due_to_pre_form_datadome",
            "synthetic_live_full_form_exercise": "not_reached_due_to_pre_form_datadome",
            "pre_form_anti_bot_handoff": "certified",
            "datadome_provider_detection": "certified",
            "fixture_full_form_behavior": "certified",
            "fixture_verified_resume_upload": True,
            "fixture_confirmation_evidence": "certified",
            "resumable_handoff": "fixture_certified",
            "official_screening_configuration_support": (
                "fixture_certified_optional_x_smarttoken_validation"
            ),
            "application_api_submission": "not_used",
            "live_full_form_certified": False,
            "bypass_attempted": False,
            "final_submit_clicked": False,
        }
        return value


_ADAPTERS = [
    GreenhouseAdapter(),
    RegisteredLeverAdapter(),
    RegisteredAshbyAdapter(),
    RegisteredSmartRecruitersAdapter(),
    WorkdayAdapter(),
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
        "framework_version": "1.4.0",
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
            "smartrecruiters_reference_url_optional": True,
            "smartrecruiters_datadome_is_manual_handoff_only": True,
            "smartrecruiters_live_full_form_not_claimed": True,
            "workday_login_and_account_creation_are_manual": True,
            "workday_target_evidence_excludes_query_and_fragment": True,
            "workday_cxs_metadata_uses_full_external_path": True,
            "workday_apply_popup_is_bounded_and_retained": True,
        },
        "universal_boundary": (
            "Each ATS adapter must pass local fixtures and supervised live dry-runs. "
            "No finite suite can certify every employer customization or future control."
        ),
    }

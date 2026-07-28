"""Fail-closed completeness and conflict reporting for the Answer Policy Vault.

Requirement profiles are JobTomatik's minimum unattended-automation contract. They
are not claims that every employer asks every listed question.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.answer_policy import ApplicantAnswerPolicy
from app.models.user import User
from app.services.answer_policy import (
    conflicting_top_policies,
    get_catalog_item,
    policy_autofill_blockers,
    policy_scope_matches,
    scope_priority,
    serialize_policy,
)

PROFILE_FIELD_REQUIREMENTS = [
    ("full_name", "Full legal or preferred application name"),
    ("email", "Applicant email"),
    ("phone", "Applicant phone number"),
    ("address", "Applicant location or mailing address"),
    ("resume_path", "Current resume"),
]

COUNTRY_READINESS_PROFILES = {
    "CA": ["work_authorization", "sponsorship_required"],
    "US": ["work_authorization", "sponsorship_required"],
    "GB": ["work_authorization", "sponsorship_required"],
    "GENERIC": ["work_authorization", "sponsorship_required"],
}

PLATFORM_READINESS_PROFILES = {
    "greenhouse": {
        "domains": ["greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io"],
        "required": ["terms_consent", "data_processing_consent"],
    },
    "lever": {
        "domains": ["lever.co", "jobs.lever.co"],
        "required": ["terms_consent"],
    },
    "ashby": {
        "domains": ["ashbyhq.com", "jobs.ashbyhq.com"],
        "required": ["terms_consent", "data_processing_consent"],
    },
    "generic": {"domains": [], "required": ["terms_consent"]},
}

BLOCKER_MESSAGES = {
    "profile_field_missing": "A required applicant profile field is missing.",
    "policy_missing": "No matching answer policy exists.",
    "policy_conflict": "Conflicting policies exist at the same scope priority.",
    "policy_inactive": "The matching answer policy is inactive.",
    "policy_interactive_mode": "The matching policy requires user interaction.",
    "policy_expired": "The matching answer policy has expired.",
    "policy_encryption_invalid": "The encrypted answer could not be verified.",
    "policy_provenance_unknown": "The answer provenance is unknown.",
    "policy_confidence_low": "The answer confidence is below the automatic-use threshold.",
    "policy_not_confirmed": "The answer has not been confirmed by the user.",
    "policy_consent_missing": "The stored consent record does not authorize autofill.",
    "policy_autofill_not_authorized": "Automatic use is not authorized.",
    "policy_answer_missing": "The policy has no usable answer value.",
}


def normalize_country_code(value: Optional[str]) -> str:
    code = str(value or "CA").strip().upper()
    return code if code in COUNTRY_READINESS_PROFILES else "GENERIC"


def detect_platform(target_url: str = "", requested_platform: str = "") -> str:
    requested = str(requested_platform or "").strip().lower()
    if requested in PLATFORM_READINESS_PROFILES:
        return requested
    domain = (urlparse(target_url or "").hostname or "").lower()
    for name, profile in PLATFORM_READINESS_PROFILES.items():
        if name == "generic":
            continue
        if any(domain == item or domain.endswith("." + item) for item in profile["domains"]):
            return name
    return "generic"


def required_policy_keys(country_code: str, platform: str) -> List[str]:
    output: List[str] = []
    for key in [
        *COUNTRY_READINESS_PROFILES[country_code],
        *PLATFORM_READINESS_PROFILES[platform]["required"],
    ]:
        if key not in output:
            output.append(key)
    return output


def _profile_value(user: User, key: str) -> Any:
    value = getattr(user, key, None)
    return value or dict(user.profile_data or {}).get(key)


def _policy_sort_key(policy: Dict[str, Any]) -> tuple[int, str, int]:
    updated = policy.get("updated_at") or policy.get("created_at")
    return (
        scope_priority(policy.get("scope")),
        updated.isoformat() if updated else "",
        int(policy.get("id") or 0),
    )


def _matched_policies(
    policies: Iterable[ApplicantAnswerPolicy],
    target_url: str,
    company: str,
) -> List[Dict[str, Any]]:
    serialized = [
        serialize_policy(policy)
        for policy in policies
        if policy_scope_matches(policy, target_url, company)
    ]
    return sorted(serialized, key=_policy_sort_key, reverse=True)


def _top_scope(policies: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = list(policies)
    if not candidates:
        return []
    highest = max(scope_priority(item.get("scope")) for item in candidates)
    return [item for item in candidates if scope_priority(item.get("scope")) == highest]


def _policy_summary(policy: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: policy.get(key)
        for key in (
            "id", "canonical_key", "scope", "scope_value", "mode", "provenance",
            "confidence", "confirmed_at", "expires_at", "is_active", "is_expired",
            "allow_autofill", "encryption_valid",
        )
    }


def _blocker(
    code: str,
    *,
    field: Optional[str] = None,
    canonical_key: Optional[str] = None,
    policy_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "message": BLOCKER_MESSAGES[code],
        "field": field,
        "canonical_key": canonical_key,
        "policy_ids": policy_ids or [],
    }


def build_answer_policy_readiness(
    db: Session,
    user: User,
    *,
    country_code: str = "CA",
    platform: str = "",
    target_url: str = "",
    company: str = "",
) -> Dict[str, Any]:
    country = normalize_country_code(country_code)
    detected_platform = detect_platform(target_url, platform)
    required_keys = required_policy_keys(country, detected_platform)
    stored = db.query(ApplicantAnswerPolicy).filter(
        ApplicantAnswerPolicy.user_id == user.id
    ).all()
    matched = _matched_policies(stored, target_url, company)

    blockers: List[Dict[str, Any]] = []
    satisfied = 0
    profile_statuses = []
    for key, label in PROFILE_FIELD_REQUIREMENTS:
        present = bool(_profile_value(user, key))
        profile_statuses.append({
            "key": key,
            "label": label,
            "source": f"user.{key}",
            "present": present,
            "blocking": not present,
        })
        if present:
            satisfied += 1
        else:
            blockers.append(_blocker("profile_field_missing", field=key))

    by_key: Dict[str, List[Dict[str, Any]]] = {}
    for policy in matched:
        by_key.setdefault(str(policy.get("canonical_key") or ""), []).append(policy)

    conflicts = []
    for key, candidates in sorted(by_key.items()):
        active = [item for item in candidates if item.get("is_active")]
        conflict_set = conflicting_top_policies(_top_scope(active or candidates))
        if conflict_set:
            ids = [int(item["id"]) for item in conflict_set if item.get("id")]
            conflicts.append({
                "canonical_key": key,
                "policy_ids": ids,
                "scope_priority": scope_priority(conflict_set[0].get("scope")),
            })
            blockers.append(_blocker("policy_conflict", canonical_key=key, policy_ids=ids))

    policy_statuses = []
    for key in required_keys:
        catalog = get_catalog_item(key) or {}
        candidates = by_key.get(key, [])
        active = [item for item in candidates if item.get("is_active")]
        top = _top_scope(active or candidates)
        conflict_set = conflicting_top_policies(top)
        status = {
            "canonical_key": key,
            "label": catalog.get("label", key),
            "category": catalog.get("category", "unknown"),
            "sensitivity": catalog.get("sensitivity", "standard"),
            "satisfied": False,
            "selected_policy": None,
            "blocker_codes": [],
        }
        if not candidates:
            status["blocker_codes"] = ["policy_missing"]
            blockers.append(_blocker("policy_missing", canonical_key=key))
        elif conflict_set:
            status["blocker_codes"] = ["policy_conflict"]
        else:
            selected = top[0]
            codes = policy_autofill_blockers(selected)
            status["selected_policy"] = _policy_summary(selected)
            status["blocker_codes"] = codes
            if not codes:
                status["satisfied"] = True
                satisfied += 1
            else:
                ids = [int(selected["id"])] if selected.get("id") else []
                blockers.extend(
                    _blocker(code, canonical_key=key, policy_ids=ids) for code in codes
                )
        policy_statuses.append(status)

    deduped = []
    seen = set()
    for item in blockers:
        identity = (
            item["code"], item.get("field"), item.get("canonical_key"),
            tuple(item.get("policy_ids") or []),
        )
        if identity not in seen:
            seen.add(identity)
            deduped.append(item)

    total = len(PROFILE_FIELD_REQUIREMENTS) + len(required_keys)
    return {
        "country_code": country,
        "platform": detected_platform,
        "target_url": target_url or "",
        "company": company or "",
        "ready_for_unattended": not deduped,
        "completeness_score": round((satisfied / total) * 100, 1) if total else 100.0,
        "required_profile_fields": profile_statuses,
        "required_policies": policy_statuses,
        "blockers": deduped,
        "conflicts": conflicts,
        "summary": {
            "profile_fields_required": len(PROFILE_FIELD_REQUIREMENTS),
            "profile_fields_complete": sum(item["present"] for item in profile_statuses),
            "policies_required": len(required_keys),
            "policies_ready": sum(item["satisfied"] for item in policy_statuses),
            "blocker_count": len(deduped),
            "conflict_count": len(conflicts),
        },
        "guarantees": [
            "No missing legal, sensitive, consent, or custom answer is inferred.",
            "Unknown or conflicting policies stop unattended execution.",
            "Expired, unconfirmed, low-confidence, inactive, or undecryptable policies cannot autofill.",
            "Country and platform profiles are minimum autonomy coverage, not claims about every employer form.",
        ],
        "generated_at": datetime.utcnow(),
    }


__all__ = [
    "COUNTRY_READINESS_PROFILES",
    "PLATFORM_READINESS_PROFILES",
    "PROFILE_FIELD_REQUIREMENTS",
    "build_answer_policy_readiness",
    "detect_platform",
    "normalize_country_code",
    "required_policy_keys",
]

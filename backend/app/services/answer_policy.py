import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.answer_policy import (
    ApplicantAnswerPolicy,
    AnswerPolicyMode,
    AnswerPolicyProvenance,
    AnswerPolicyScope,
)
from app.services.answer_policy_catalog import QUESTION_CATALOG

_CATALOG_BY_KEY = {item["canonical_key"]: item for item in QUESTION_CATALOG}
_SCOPE_PRIORITY = {
    AnswerPolicyScope.global_scope.value: 1,
    AnswerPolicyScope.platform.value: 2,
    AnswerPolicyScope.company.value: 3,
}
MIN_AUTOFILL_CONFIDENCE = 0.80


def normalize_question_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def get_catalog_item(canonical_key: str) -> Optional[Dict[str, Any]]:
    item = _CATALOG_BY_KEY.get(canonical_key)
    return dict(item) if item else None


def classify_question(question_text: str) -> Dict[str, str]:
    normalized = normalize_question_text(question_text)
    for item in QUESTION_CATALOG:
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in item["patterns"]):
            return {
                "canonical_key": item["canonical_key"],
                "category": item["category"],
                "sensitivity": item["sensitivity"],
                "label": item["label"],
            }
    return {
        "canonical_key": "custom.unclassified",
        "category": "custom",
        "sensitivity": "standard",
        "label": "Unclassified application question",
    }


def _fernet() -> Fernet:
    settings = get_settings()
    secret = settings.answer_vault_key or settings.secret_key
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_policy_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_policy_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def clean_fallback_answers(values: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for value in values or []:
        answer = str(value or "").strip()
        normalized = normalize_question_text(answer)
        if not answer or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(answer)
    return cleaned[:20]


def encrypt_policy_fallbacks(values: Iterable[str]) -> Optional[str]:
    cleaned = clean_fallback_answers(values)
    if not cleaned:
        return None
    return encrypt_policy_value(json.dumps(cleaned, ensure_ascii=False))


def _decrypt_policy_fallbacks_with_validity(value: Optional[str]) -> tuple[List[str], bool]:
    if not value:
        return [], True
    decrypted = decrypt_policy_value(value)
    if decrypted is None:
        return [], False
    try:
        decoded = json.loads(decrypted)
    except (TypeError, ValueError, json.JSONDecodeError):
        return [], False
    if not isinstance(decoded, list):
        return [], False
    return clean_fallback_answers(decoded), True


def decrypt_policy_fallbacks(value: Optional[str]) -> List[str]:
    return _decrypt_policy_fallbacks_with_validity(value)[0]


def policy_answer_candidates(policy: Dict[str, Any]) -> List[str]:
    candidates = [
        policy.get("answer_label"),
        policy.get("answer_value"),
        *(policy.get("fallback_answers") or []),
    ]
    return clean_fallback_answers(value for value in candidates if value)


def scope_priority(scope: Optional[str]) -> int:
    return _SCOPE_PRIORITY.get(scope or "", 0)


def policy_scope_matches(policy: ApplicantAnswerPolicy, target_url: str, company: str) -> bool:
    scope = policy.scope or AnswerPolicyScope.global_scope.value
    scope_value = normalize_question_text(policy.scope_value)
    if scope == AnswerPolicyScope.global_scope.value:
        return True
    if scope == AnswerPolicyScope.platform.value:
        domain = (urlparse(target_url or "").hostname or "").lower()
        return bool(scope_value and (domain == scope_value or domain.endswith("." + scope_value)))
    if scope == AnswerPolicyScope.company.value:
        normalized_company = normalize_question_text(company)
        return bool(scope_value and scope_value in normalized_company)
    return False


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sort_timestamp(value: Optional[datetime]) -> float:
    normalized = _naive_utc(value)
    return normalized.timestamp() if normalized is not None else 0.0


def policy_is_expired(policy: ApplicantAnswerPolicy | Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    expires_at = policy.get("expires_at") if isinstance(policy, dict) else policy.expires_at
    normalized_expiry = _naive_utc(expires_at)
    if normalized_expiry is None:
        return False
    normalized_now = _naive_utc(now or datetime.utcnow()) or datetime.utcnow()
    return normalized_expiry <= normalized_now


def serialize_policy(policy: ApplicantAnswerPolicy) -> Dict[str, Any]:
    answer_value = decrypt_policy_value(policy.encrypted_value)
    answer_label = decrypt_policy_value(policy.encrypted_label)
    fallback_answers, fallbacks_valid = _decrypt_policy_fallbacks_with_validity(
        policy.encrypted_fallbacks
    )
    encryption_valid = (
        (not policy.encrypted_value or answer_value is not None)
        and (not policy.encrypted_label or answer_label is not None)
        and fallbacks_valid
    )
    consent_metadata = dict(policy.consent_metadata or {})
    if not consent_metadata and policy.confirmed_at:
        consent_metadata = {
            "confirmation_method": "legacy_confirmed_at",
            "autofill_authorized": bool(policy.allow_autofill),
            "recorded_at": policy.confirmed_at.isoformat(),
        }

    return {
        "id": policy.id,
        "canonical_key": policy.canonical_key,
        "category": policy.category,
        "sensitivity": policy.sensitivity,
        "mode": policy.mode,
        "answer_value": answer_value,
        "answer_label": answer_label,
        "fallback_answers": fallback_answers,
        "match_phrases": list(policy.match_phrases or []),
        "scope": policy.scope,
        "scope_value": policy.scope_value or "",
        "allow_autofill": bool(policy.allow_autofill),
        "is_active": bool(policy.is_active),
        "confirmed_at": policy.confirmed_at,
        "provenance": policy.provenance or AnswerPolicyProvenance.unknown.value,
        "confidence": float(policy.confidence if policy.confidence is not None else 0.0),
        "consent_metadata": consent_metadata,
        "source_metadata": dict(policy.source_metadata or {}),
        "expires_at": policy.expires_at,
        "is_expired": policy_is_expired(policy),
        "encryption_valid": encryption_valid,
        "version": policy.version or 1,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def load_runtime_policies(
    db: Session,
    user_id: int,
    *,
    target_url: str = "",
    company: str = "",
) -> List[Dict[str, Any]]:
    policies = (
        db.query(ApplicantAnswerPolicy)
        .filter(
            ApplicantAnswerPolicy.user_id == user_id,
            ApplicantAnswerPolicy.is_active.is_(True),
        )
        .all()
    )
    matched = [policy for policy in policies if policy_scope_matches(policy, target_url, company)]
    matched.sort(
        key=lambda item: (
            scope_priority(item.scope),
            _sort_timestamp(item.updated_at or item.created_at),
            item.id or 0,
        ),
        reverse=True,
    )
    return [serialize_policy(policy) for policy in matched]


def policy_conflict_signature(policy: Dict[str, Any]) -> tuple[Any, ...]:
    return (
        policy.get("mode"),
        tuple(normalize_question_text(value) for value in policy_answer_candidates(policy)),
        bool(policy.get("allow_autofill")),
        bool(policy.get("confirmed_at")),
        bool(policy.get("is_active", True)),
        bool(policy.get("is_expired")),
        policy.get("provenance"),
        round(float(policy.get("confidence") or 0.0), 4),
    )


def conflicting_top_policies(policies: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = list(policies)
    if len(candidates) < 2:
        return []
    highest = max(scope_priority(item.get("scope")) for item in candidates)
    top = [item for item in candidates if scope_priority(item.get("scope")) == highest]
    signatures = {policy_conflict_signature(item) for item in top}
    return top if len(signatures) > 1 else []


def policy_autofill_blockers(policy: Dict[str, Any]) -> List[str]:
    mode = policy.get("mode", AnswerPolicyMode.ask_each_time.value)
    answer = policy_answer_candidates(policy)
    consent_metadata = dict(policy.get("consent_metadata") or {})
    confidence = float(policy.get("confidence") or 0.0)
    provenance = policy.get("provenance") or AnswerPolicyProvenance.unknown.value
    blockers: List[str] = []

    if not policy.get("is_active", True):
        blockers.append("policy_inactive")
    if mode not in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value}:
        blockers.append("policy_interactive_mode")
    if policy.get("is_expired"):
        blockers.append("policy_expired")
    if not policy.get("encryption_valid", True):
        blockers.append("policy_encryption_invalid")
    if provenance == AnswerPolicyProvenance.unknown.value:
        blockers.append("policy_provenance_unknown")
    if confidence < MIN_AUTOFILL_CONFIDENCE:
        blockers.append("policy_confidence_low")
    if not policy.get("confirmed_at"):
        blockers.append("policy_not_confirmed")
    if consent_metadata and consent_metadata.get("autofill_authorized") is not True:
        blockers.append("policy_consent_missing")
    if not policy.get("allow_autofill"):
        blockers.append("policy_autofill_not_authorized")
    if not answer:
        blockers.append("policy_answer_missing")
    return blockers


def resolve_runtime_policy(question_text: str, policies: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    classification = classify_question(question_text)
    normalized = normalize_question_text(question_text)
    candidates: List[Dict[str, Any]] = []

    for policy in policies:
        canonical_key = policy.get("canonical_key", "")
        if canonical_key == classification["canonical_key"]:
            candidates.append(policy)
            continue
        if canonical_key.startswith("custom.") and any(
            normalize_question_text(phrase) in normalized
            for phrase in policy.get("match_phrases", [])
            if phrase
        ):
            candidates.append(policy)

    if not candidates:
        return {
            **classification,
            "matched": False,
            "can_autofill": False,
            "reason": "No approved answer policy exists for this question.",
        }

    highest_priority = max(scope_priority(item.get("scope")) for item in candidates)
    top_candidates = [
        item for item in candidates if scope_priority(item.get("scope")) == highest_priority
    ]
    conflicts = conflicting_top_policies(top_candidates)
    if conflicts:
        return {
            **classification,
            "matched": True,
            "can_autofill": False,
            "reason": "Conflicting answer policies exist at the same scope priority.",
            "conflict_policy_ids": [item.get("id") for item in conflicts],
        }

    policy = sorted(
        top_candidates,
        key=lambda item: (
            _sort_timestamp(item.get("updated_at") or item.get("created_at")),
            item.get("id") or 0,
        ),
        reverse=True,
    )[0]
    mode = policy.get("mode", AnswerPolicyMode.ask_each_time.value)
    answer_candidates = policy_answer_candidates(policy)
    answer = answer_candidates[0] if answer_candidates else None
    blocker_codes = policy_autofill_blockers(policy)
    can_autofill = not blocker_codes

    reason_by_code = {
        "policy_inactive": "The answer policy is inactive.",
        "policy_interactive_mode": (
            "The answer policy requires a fresh user decision."
            if mode == AnswerPolicyMode.ask_each_time.value
            else "The answer policy explicitly forbids answering this question."
        ),
        "policy_expired": "The stored answer policy has expired and must be reviewed.",
        "policy_encryption_invalid": "The encrypted answer could not be verified.",
        "policy_provenance_unknown": "The answer provenance is unknown.",
        "policy_confidence_low": "The answer confidence is below the automatic-use threshold.",
        "policy_not_confirmed": "The stored answer has not been confirmed by the user.",
        "policy_consent_missing": "The stored consent record does not authorize automatic use.",
        "policy_autofill_not_authorized": "The user has not authorized automatic use of this answer.",
        "policy_answer_missing": "The approved policy has no usable answer value.",
    }
    reason = reason_by_code.get(blocker_codes[0]) if blocker_codes else None

    return {
        **classification,
        "matched": True,
        "can_autofill": can_autofill,
        "reason": reason,
        "blocker_codes": blocker_codes,
        "policy": policy,
        "answer": answer,
        "answer_candidates": answer_candidates,
    }


def review_reason_for_question(classification: Dict[str, Any]) -> str:
    if classification.get("sensitivity") == "legal":
        return "legal_answer_missing"
    if classification.get("sensitivity") == "sensitive":
        return "sensitive_answer_missing"
    return "ambiguous_question"

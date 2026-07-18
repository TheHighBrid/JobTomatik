import base64
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.answer_policy import ApplicantAnswerPolicy, AnswerPolicyMode, AnswerPolicyScope
from app.services.answer_policy_catalog import QUESTION_CATALOG

_CATALOG_BY_KEY = {item["canonical_key"]: item for item in QUESTION_CATALOG}
_SCOPE_PRIORITY = {
    AnswerPolicyScope.global_scope.value: 1,
    AnswerPolicyScope.platform.value: 2,
    AnswerPolicyScope.company.value: 3,
}


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


def decrypt_policy_fallbacks(value: Optional[str]) -> List[str]:
    decrypted = decrypt_policy_value(value)
    if not decrypted:
        return []
    try:
        decoded = json.loads(decrypted)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return clean_fallback_answers(decoded if isinstance(decoded, list) else [])


def policy_answer_candidates(policy: Dict[str, Any]) -> List[str]:
    candidates = [
        policy.get("answer_label"),
        policy.get("answer_value"),
        *(policy.get("fallback_answers") or []),
    ]
    return clean_fallback_answers(value for value in candidates if value)


def _scope_matches(policy: ApplicantAnswerPolicy, target_url: str, company: str) -> bool:
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


def serialize_policy(policy: ApplicantAnswerPolicy) -> Dict[str, Any]:
    return {
        "id": policy.id,
        "canonical_key": policy.canonical_key,
        "category": policy.category,
        "sensitivity": policy.sensitivity,
        "mode": policy.mode,
        "answer_value": decrypt_policy_value(policy.encrypted_value),
        "answer_label": decrypt_policy_value(policy.encrypted_label),
        "fallback_answers": decrypt_policy_fallbacks(policy.encrypted_fallbacks),
        "match_phrases": list(policy.match_phrases or []),
        "scope": policy.scope,
        "scope_value": policy.scope_value or "",
        "allow_autofill": bool(policy.allow_autofill),
        "is_active": bool(policy.is_active),
        "confirmed_at": policy.confirmed_at,
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
    matched = [policy for policy in policies if _scope_matches(policy, target_url, company)]
    matched.sort(key=lambda item: _SCOPE_PRIORITY.get(item.scope, 0), reverse=True)
    return [serialize_policy(policy) for policy in matched]


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

    policy = candidates[0] if candidates else None
    if not policy:
        return {
            **classification,
            "matched": False,
            "can_autofill": False,
            "reason": "No approved answer policy exists for this question.",
        }

    mode = policy.get("mode", AnswerPolicyMode.ask_each_time.value)
    answer_candidates = policy_answer_candidates(policy)
    answer = answer_candidates[0] if answer_candidates else None
    confirmed = bool(policy.get("confirmed_at"))
    can_autofill = (
        mode in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value}
        and bool(policy.get("allow_autofill"))
        and confirmed
        and bool(answer)
    )

    reason = None
    if mode == AnswerPolicyMode.ask_each_time.value:
        reason = "The answer policy requires a fresh user decision."
    elif mode == AnswerPolicyMode.skip.value:
        reason = "The answer policy explicitly forbids answering this question."
    elif not confirmed:
        reason = "The stored answer has not been confirmed by the user."
    elif not policy.get("allow_autofill"):
        reason = "The user has not authorized automatic use of this answer."
    elif not answer:
        reason = "The approved policy has no usable answer value."

    return {
        **classification,
        "matched": True,
        "can_autofill": can_autofill,
        "reason": reason,
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

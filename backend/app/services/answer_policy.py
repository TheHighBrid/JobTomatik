import base64
import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.answer_policy import ApplicantAnswerPolicy, AnswerPolicyMode, AnswerPolicyScope


QUESTION_CATALOG: List[Dict[str, Any]] = [
    {
        "canonical_key": "work_authorization",
        "label": "Legally authorized to work",
        "category": "work_authorization",
        "sensitivity": "legal",
        "description": "Whether you are legally authorized to work in the job location.",
        "patterns": [
            r"authorized to work", r"legally authorized", r"eligible to work",
            r"right to work", r"work authorization", r"autorisé[e]? à travailler",
        ],
    },
    {
        "canonical_key": "sponsorship_required",
        "label": "Requires employer sponsorship",
        "category": "sponsorship",
        "sensitivity": "legal",
        "description": "Whether you currently or later require visa or immigration sponsorship.",
        "patterns": [
            r"require sponsorship", r"visa sponsorship", r"immigration sponsorship",
            r"need sponsorship", r"sponsorship now or in the future", r"parrainage",
        ],
    },
    {
        "canonical_key": "age_requirement",
        "label": "Meets legal age requirement",
        "category": "legal",
        "sensitivity": "legal",
        "description": "Confirmation that you meet a stated legal minimum-age requirement.",
        "patterns": [r"at least 18", r"minimum age", r"legal age", r"18 years of age", r"âge légal"],
    },
    {
        "canonical_key": "criminal_history",
        "label": "Criminal history declaration",
        "category": "legal",
        "sensitivity": "legal",
        "description": "Any criminal-history or conviction declaration.",
        "patterns": [r"criminal record", r"criminal history", r"convicted", r"conviction", r"casier judiciaire"],
    },
    {
        "canonical_key": "gender_identity",
        "label": "Gender identity",
        "category": "demographic",
        "sensitivity": "sensitive",
        "description": "Voluntary gender or gender-identity disclosure.",
        "patterns": [r"\bgender\b", r"gender identity", r"\bsexe\b", r"identité de genre"],
    },
    {
        "canonical_key": "race_ethnicity",
        "label": "Race or ethnicity",
        "category": "demographic",
        "sensitivity": "sensitive",
        "description": "Voluntary race, ethnicity, or visible-minority disclosure.",
        "patterns": [r"race", r"ethnicity", r"ethnic background", r"visible minority", r"origine ethnique"],
    },
    {
        "canonical_key": "veteran_status",
        "label": "Veteran status",
        "category": "demographic",
        "sensitivity": "sensitive",
        "description": "Voluntary veteran or protected-veteran disclosure.",
        "patterns": [r"veteran", r"protected veteran", r"ancien combattant"],
    },
    {
        "canonical_key": "disability_status",
        "label": "Disability status",
        "category": "demographic",
        "sensitivity": "sensitive",
        "description": "Voluntary disability or accommodation disclosure.",
        "patterns": [
            r"disability", r"disabled", r"accommodation", r"handicap",
            r"personne en situation de handicap",
        ],
    },
    {
        "canonical_key": "salary_expectation",
        "label": "Salary expectation",
        "category": "compensation",
        "sensitivity": "sensitive",
        "description": "Desired salary, compensation range, or pay expectation.",
        "patterns": [
            r"salary expectation", r"expected salary", r"desired salary",
            r"compensation expectation", r"pay expectation", r"prétentions salariales",
        ],
    },
    {
        "canonical_key": "willing_to_relocate",
        "label": "Willing to relocate",
        "category": "relocation",
        "sensitivity": "standard",
        "description": "Whether you are willing to relocate for the role.",
        "patterns": [r"willing to relocate", r"open to relocation", r"relocate", r"déménager"],
    },
    {
        "canonical_key": "availability_date",
        "label": "Availability or start date",
        "category": "availability",
        "sensitivity": "standard",
        "description": "Your start date, notice period, or availability.",
        "patterns": [
            r"start date", r"available from", r"availability date", r"notice period",
            r"date de disponibilité", r"préavis",
        ],
    },
    {
        "canonical_key": "highest_education",
        "label": "Highest education",
        "category": "education",
        "sensitivity": "standard",
        "description": "Your highest completed education level.",
        "patterns": [r"highest education", r"highest degree", r"education level", r"niveau d'études"],
    },
    {
        "canonical_key": "currently_employed",
        "label": "Currently employed",
        "category": "employment",
        "sensitivity": "standard",
        "description": "Whether you are currently employed.",
        "patterns": [r"currently employed", r"presently employed", r"actuellement en emploi"],
    },
    {
        "canonical_key": "referral_source",
        "label": "How you heard about the role",
        "category": "source",
        "sensitivity": "standard",
        "description": "The source through which you discovered the position.",
        "patterns": [r"how did you hear", r"how you heard", r"source of application", r"comment avez-vous entendu"],
    },
    {
        "canonical_key": "terms_consent",
        "label": "Application terms consent",
        "category": "consent",
        "sensitivity": "legal",
        "description": "Consent to application terms, declarations, or attestations.",
        "patterns": [
            r"i agree", r"i certify", r"i acknowledge", r"terms and conditions",
            r"attest", r"consent", r"j'accepte", r"je certifie",
        ],
    },
    {
        "canonical_key": "data_processing_consent",
        "label": "Data processing consent",
        "category": "consent",
        "sensitivity": "legal",
        "description": "Consent to processing or retaining applicant data.",
        "patterns": [
            r"process my data", r"retain my data", r"privacy consent", r"data processing",
            r"traitement de mes données", r"conserver mes données",
        ],
    },
]

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
    answer = policy.get("answer_label") or policy.get("answer_value")
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
    }


def review_reason_for_question(classification: Dict[str, Any]) -> str:
    if classification.get("sensitivity") == "legal":
        return "legal_answer_missing"
    if classification.get("sensitivity") == "sensitive":
        return "sensitive_answer_missing"
    return "ambiguous_question"

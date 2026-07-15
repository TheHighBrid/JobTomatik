from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.answer_policy import ApplicantAnswerPolicy, AnswerPolicyMode, AnswerPolicyScope
from app.models.user import User
from app.schemas.answer_policy import (
    AnswerPolicyCatalogItem,
    AnswerPolicyCreate,
    AnswerPolicyOut,
    AnswerPolicyUpdate,
)
from app.services.answer_policy import (
    QUESTION_CATALOG,
    encrypt_policy_value,
    get_catalog_item,
    serialize_policy,
)

router = APIRouter(prefix="/profile/answer-policies", tags=["answer-policies"])


def _metadata_for_policy(canonical_key: str, match_phrases: List[str]) -> tuple[str, str]:
    catalog_item = get_catalog_item(canonical_key)
    if catalog_item:
        return catalog_item["category"], catalog_item["sensitivity"]
    if canonical_key.startswith("custom.") and any(phrase.strip() for phrase in match_phrases):
        return "custom", "standard"
    raise HTTPException(
        status_code=400,
        detail="Unknown canonical key. Custom policies must use a custom.* key and include match phrases.",
    )


def _validate_policy_payload(
    *,
    mode: str,
    answer_value: str | None,
    answer_label: str | None,
    scope: str,
    scope_value: str,
    allow_autofill: bool,
    confirmed: bool,
) -> None:
    if scope != AnswerPolicyScope.global_scope.value and not scope_value.strip():
        raise HTTPException(status_code=400, detail="Platform and company policies require a scope value.")

    if mode in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value}:
        if not (answer_value or answer_label):
            raise HTTPException(status_code=400, detail="Answer and decline policies require an answer value or label.")

    if allow_autofill and mode not in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value}:
        raise HTTPException(status_code=400, detail="Only answer or decline policies can be authorized for autofill.")

    if allow_autofill and not confirmed:
        raise HTTPException(status_code=400, detail="Autofill requires explicit user confirmation.")


def _policy_out(policy: ApplicantAnswerPolicy) -> AnswerPolicyOut:
    return AnswerPolicyOut(**serialize_policy(policy))


@router.get("/catalog", response_model=List[AnswerPolicyCatalogItem])
async def get_answer_policy_catalog(current_user: User = Depends(get_current_user)):
    del current_user
    return [AnswerPolicyCatalogItem(**item) for item in QUESTION_CATALOG]


@router.get("", response_model=List[AnswerPolicyOut])
async def list_answer_policies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policies = (
        db.query(ApplicantAnswerPolicy)
        .filter(ApplicantAnswerPolicy.user_id == current_user.id)
        .order_by(ApplicantAnswerPolicy.category, ApplicantAnswerPolicy.canonical_key)
        .all()
    )
    return [_policy_out(policy) for policy in policies]


@router.post("", response_model=AnswerPolicyOut, status_code=201)
async def create_answer_policy(
    data: AnswerPolicyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match_phrases = [phrase.strip() for phrase in data.match_phrases if phrase.strip()]
    category, sensitivity = _metadata_for_policy(data.canonical_key, match_phrases)
    mode = data.mode.value
    scope = data.scope.value
    scope_value = data.scope_value.strip().lower()

    _validate_policy_payload(
        mode=mode,
        answer_value=data.answer_value,
        answer_label=data.answer_label,
        scope=scope,
        scope_value=scope_value,
        allow_autofill=data.allow_autofill,
        confirmed=data.confirmed,
    )

    policy = ApplicantAnswerPolicy(
        user_id=current_user.id,
        canonical_key=data.canonical_key,
        category=category,
        sensitivity=sensitivity,
        mode=mode,
        encrypted_value=encrypt_policy_value(data.answer_value),
        encrypted_label=encrypt_policy_value(data.answer_label),
        match_phrases=match_phrases,
        scope=scope,
        scope_value=scope_value,
        allow_autofill=data.allow_autofill,
        is_active=data.is_active,
        confirmed_at=datetime.utcnow() if data.confirmed else None,
    )
    db.add(policy)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An answer policy already exists for this question and scope.",
        )
    db.refresh(policy)
    return _policy_out(policy)


@router.patch("/{policy_id}", response_model=AnswerPolicyOut)
async def update_answer_policy(
    policy_id: int,
    data: AnswerPolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = (
        db.query(ApplicantAnswerPolicy)
        .filter(
            ApplicantAnswerPolicy.id == policy_id,
            ApplicantAnswerPolicy.user_id == current_user.id,
        )
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Answer policy not found")

    updates = data.model_dump(exclude_unset=True)
    answer_changed = "answer_value" in updates or "answer_label" in updates
    if "answer_value" in updates:
        policy.encrypted_value = encrypt_policy_value(updates.pop("answer_value"))
    if "answer_label" in updates:
        policy.encrypted_label = encrypt_policy_value(updates.pop("answer_label"))
    if "match_phrases" in updates:
        policy.match_phrases = [phrase.strip() for phrase in updates.pop("match_phrases") if phrase.strip()]
    if "mode" in updates:
        policy.mode = updates.pop("mode").value
    if "scope" in updates:
        policy.scope = updates.pop("scope").value
    if "scope_value" in updates:
        policy.scope_value = updates.pop("scope_value").strip().lower()
    confirmed = updates.pop("confirmed", None)

    for field, value in updates.items():
        setattr(policy, field, value)

    if answer_changed and confirmed is not True:
        policy.confirmed_at = None
        policy.allow_autofill = False
    elif confirmed is True:
        policy.confirmed_at = datetime.utcnow()
    elif confirmed is False:
        policy.confirmed_at = None
        policy.allow_autofill = False

    serialized = serialize_policy(policy)
    _validate_policy_payload(
        mode=policy.mode,
        answer_value=serialized.get("answer_value"),
        answer_label=serialized.get("answer_label"),
        scope=policy.scope,
        scope_value=policy.scope_value or "",
        allow_autofill=bool(policy.allow_autofill),
        confirmed=bool(policy.confirmed_at),
    )

    policy.version = (policy.version or 1) + 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An answer policy already exists for this question and scope.",
        )
    db.refresh(policy)
    return _policy_out(policy)


@router.post("/{policy_id}/confirm", response_model=AnswerPolicyOut)
async def confirm_answer_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = (
        db.query(ApplicantAnswerPolicy)
        .filter(
            ApplicantAnswerPolicy.id == policy_id,
            ApplicantAnswerPolicy.user_id == current_user.id,
        )
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Answer policy not found")

    serialized = serialize_policy(policy)
    if policy.mode in {AnswerPolicyMode.answer.value, AnswerPolicyMode.decline.value} and not (
        serialized.get("answer_value") or serialized.get("answer_label")
    ):
        raise HTTPException(status_code=400, detail="Add an answer before confirming this policy.")

    policy.confirmed_at = datetime.utcnow()
    policy.version = (policy.version or 1) + 1
    db.commit()
    db.refresh(policy)
    return _policy_out(policy)


@router.delete("/{policy_id}", status_code=204)
async def delete_answer_policy(
    policy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    policy = (
        db.query(ApplicantAnswerPolicy)
        .filter(
            ApplicantAnswerPolicy.id == policy_id,
            ApplicantAnswerPolicy.user_id == current_user.id,
        )
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Answer policy not found")
    db.delete(policy)
    db.commit()
    return Response(status_code=204)

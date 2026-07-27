"""Platform-aware safety layer for independent submission-evidence review.

The established Greenhouse review service remains the source of truth for generic
review invariants. This module adds exact Lever platform, payload, adapter, and
target-identity checks before accepted evidence may confirm an application or enter
the Lever pilot ledger.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import Application, SubmissionEvidence
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.ats_lever import parse_lever_job_url
from app.services.submission_evidence_review import (
    SubmissionEvidenceReviewError,
    build_evidence_review_preflight as build_base_evidence_review_preflight,
    build_evidence_snapshot,
    build_supervised_pilot_record as build_base_supervised_pilot_record,
    review_submission_evidence as review_base_submission_evidence,
)


GREENHOUSE_PLATFORM = "greenhouse"
LEVER_PLATFORM = "lever"
LEVER_REQUIRED_IDENTITY_FIELDS = (
    "site",
    "posting_id",
    "region",
    "canonical_application_url",
    "posting_metadata_hash",
    "identity_hash",
)
LEVER_STRONG_EVIDENCE_TYPES = {
    "confirmation_page",
    "success_banner",
    "external_application_id",
    "portal_history",
    "confirmation_email",
    "email_provider_receipt",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _latest_consumed_approval(db: Session, application_id: int) -> Optional[SubmissionApproval]:
    return (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
        )
        .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
        .first()
    )


def _approval_target_identity(approval: SubmissionApproval) -> Dict[str, Any]:
    metadata = dict(approval.approval_metadata or {})
    identity = metadata.get("target_identity")
    return dict(identity) if isinstance(identity, Mapping) else {}


def _concrete_confirmation_signal(snapshot: Mapping[str, Any]) -> bool:
    return bool(
        snapshot.get("evidence_type") in LEVER_STRONG_EVIDENCE_TYPES
        and (
            snapshot.get("confirmation_text_present")
            or snapshot.get("external_application_id")
            or snapshot.get("screenshot_path")
            or snapshot.get("html_snapshot_path")
        )
    )


def _lever_final_url_blockers(
    snapshot: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> list[str]:
    final_url = str(snapshot.get("final_url") or "").strip()
    parsed = urlparse(final_url)
    host = str(parsed.hostname or "").lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    expected_site = str(identity.get("site") or "").strip()
    expected_posting_id = str(identity.get("posting_id") or "").strip()
    expected_region = str(identity.get("region") or "").strip()
    expected_host = "jobs.eu.lever.co" if expected_region == "eu" else "jobs.lever.co"
    observed_site = path_parts[0] if path_parts else None
    _, observed_posting_id, observed_region = parse_lever_job_url(final_url)

    blockers: list[str] = []
    if host != expected_host or observed_site != expected_site or observed_region != expected_region:
        blockers.append("lever_evidence_final_url_site_or_region_mismatch")
        return blockers

    if observed_posting_id == expected_posting_id:
        return blockers

    # Lever may redirect to /<site>/thank-you after a successful submission. Match
    # the worker gate: allow that route only when the exact approval identity is
    # already present and the evidence contains a concrete strong confirmation.
    if not _concrete_confirmation_signal(snapshot):
        blockers.append("lever_evidence_final_url_posting_mismatch")
    return blockers


def _lever_evidence_blockers(
    approval: SubmissionApproval,
    evidence: SubmissionEvidence,
    snapshot: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    evidence_metadata = snapshot.get("evidence_metadata")
    metadata = dict(evidence_metadata) if isinstance(evidence_metadata, Mapping) else {}
    approval_metadata = dict(approval.approval_metadata or {})
    identity = _approval_target_identity(approval)

    if str(approval.platform or "").strip().lower() != LEVER_PLATFORM:
        return blockers

    if str(metadata.get("platform") or "").strip().lower() != LEVER_PLATFORM:
        blockers.append("lever_evidence_platform_mismatch")
    if str(metadata.get("adapter") or "").strip().lower() != LEVER_PLATFORM:
        blockers.append("lever_evidence_adapter_mismatch")

    expected_adapter_version = str(approval_metadata.get("adapter_version") or "").strip()
    if (
        not expected_adapter_version
        or str(metadata.get("adapter_version") or "").strip() != expected_adapter_version
    ):
        blockers.append("lever_evidence_adapter_version_mismatch")

    expected_payload_hash = str(approval.combined_payload_hash or "").strip()
    if str(evidence.payload_hash or "").strip() != expected_payload_hash:
        blockers.append("lever_evidence_payload_hash_mismatch")
    if str(metadata.get("combined_payload_hash") or "").strip() != expected_payload_hash:
        blockers.append("lever_evidence_metadata_payload_hash_mismatch")
    if str(metadata.get("approval_reference") or "").strip() != str(approval.reference or "").strip():
        blockers.append("lever_evidence_approval_reference_mismatch")

    for field in LEVER_REQUIRED_IDENTITY_FIELDS:
        expected = str(identity.get(field) or "").strip()
        observed_key = "target_identity_hash" if field == "identity_hash" else field
        observed = str(metadata.get(observed_key) or "").strip()
        if not expected or observed != expected:
            blockers.append(f"lever_evidence_{observed_key}_mismatch")

    blockers.extend(_lever_final_url_blockers(snapshot, identity))
    return list(dict.fromkeys(blockers))


def build_platform_evidence_review_preflight(
    db: Session,
    application: Application,
    job: Job,
    evidence: SubmissionEvidence,
) -> Dict[str, Any]:
    preflight = build_base_evidence_review_preflight(db, application, job, evidence)
    approval = _latest_consumed_approval(db, application.id)
    platform = str(approval.platform or "").strip().lower() if approval else None
    blockers = list(preflight.get("blockers") or [])

    if approval and platform == LEVER_PLATFORM:
        blockers.extend(_lever_evidence_blockers(approval, evidence, preflight["evidence"]))
    elif approval and platform not in {GREENHOUSE_PLATFORM, LEVER_PLATFORM}:
        blockers.append("unsupported_supervised_evidence_platform")

    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    identity = _approval_target_identity(approval) if approval else {}
    return {
        **preflight,
        "ready_for_acceptance": not blockers,
        "blockers": blockers,
        "platform": platform,
        "adapter_version": (
            dict(approval.approval_metadata or {}).get("adapter_version") if approval else None
        ),
        "target_identity": identity,
        "target_identity_hash": identity.get("identity_hash"),
    }


def review_platform_submission_evidence(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    evidence: SubmissionEvidence,
    *,
    decision: str,
    confirm_employer: str,
    confirm_role: str,
    confirm_evidence_type: str,
    confirm_evidence_matches_application: bool,
    review_acknowledgement: str,
    notes: Optional[str] = None,
) -> SubmissionEvidenceReview:
    normalized_decision = str(decision or "").strip().lower()
    preflight = build_platform_evidence_review_preflight(db, application, job, evidence)
    effective_decision = normalized_decision
    effective_notes = notes
    platform_blockers: list[str] = []

    if (
        normalized_decision == "accepted"
        and preflight.get("platform") == LEVER_PLATFORM
        and not preflight["ready_for_acceptance"]
    ):
        # Persist a rejected independent review so the established base service
        # creates the submission_uncertain state and manual-review task. Raising
        # here would be rolled back by the API and lose the safety record.
        effective_decision = "rejected"
        platform_blockers = list(preflight["blockers"])
        blocker_note = "Lever evidence acceptance blocked: " + ", ".join(platform_blockers)
        effective_notes = f"{notes}\n{blocker_note}" if notes else blocker_note

    review = review_base_submission_evidence(
        db,
        application,
        user,
        job,
        evidence,
        decision=effective_decision,
        confirm_employer=confirm_employer,
        confirm_role=confirm_role,
        confirm_evidence_type=confirm_evidence_type,
        confirm_evidence_matches_application=confirm_evidence_matches_application,
        review_acknowledgement=review_acknowledgement,
        notes=effective_notes,
    )
    if platform_blockers:
        metadata = dict(review.review_metadata or {})
        metadata.update({
            "requested_decision": normalized_decision,
            "platform": LEVER_PLATFORM,
            "platform_blockers": platform_blockers,
        })
        review.review_metadata = metadata
    return review


def build_platform_supervised_pilot_record(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    record = build_base_supervised_pilot_record(db, application, user, job)
    approval = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.reference == record["approval_reference"])
        .first()
    )
    if not approval:
        raise SubmissionEvidenceReviewError("Consumed supervised approval evidence is missing")

    platform = str(approval.platform or "").strip().lower()
    if platform == GREENHOUSE_PLATFORM:
        return record
    if platform != LEVER_PLATFORM:
        raise SubmissionEvidenceReviewError(
            f"Unsupported supervised pilot record platform: {platform or 'unknown'}"
        )

    review = (
        db.query(SubmissionEvidenceReview)
        .filter(SubmissionEvidenceReview.reference == record["review_reference"])
        .first()
    )
    evidence = (
        db.query(SubmissionEvidence)
        .filter(SubmissionEvidence.id == review.evidence_id)
        .first()
        if review
        else None
    )
    if not review or not evidence:
        raise SubmissionEvidenceReviewError("Reviewed Lever evidence is missing")

    snapshot = build_evidence_snapshot(evidence)
    blockers = _lever_evidence_blockers(approval, evidence, snapshot)
    if blockers:
        raise SubmissionEvidenceReviewError(
            "Lever pilot export is blocked: " + ", ".join(blockers)
        )

    approval_metadata = dict(approval.approval_metadata or {})
    identity = _approval_target_identity(approval)
    run_seed = {
        "application_id": application.id,
        "approval_reference": approval.reference,
        "review_reference": review.reference,
        "evidence_snapshot_hash": review.evidence_snapshot_hash,
        "target_identity_hash": identity.get("identity_hash"),
    }
    return {
        **record,
        "run_id": "lv-supervised-" + _hash_value(run_seed)[:20],
        "platform": LEVER_PLATFORM,
        "adapter": LEVER_PLATFORM,
        "adapter_version": approval_metadata.get("adapter_version"),
        "board_token": identity.get("site"),
        "job_id": identity.get("posting_id"),
        "application_url": identity.get("canonical_application_url"),
        "site": identity.get("site"),
        "posting_id": identity.get("posting_id"),
        "region": identity.get("region"),
        "canonical_application_url": identity.get("canonical_application_url"),
        "posting_metadata_hash": identity.get("posting_metadata_hash"),
        "target_identity_hash": identity.get("identity_hash"),
        "combined_payload_hash": approval.combined_payload_hash,
        "evidence_snapshot_hash": review.evidence_snapshot_hash,
        "evidence_payload_hash": evidence.payload_hash,
    }


__all__ = [
    "build_platform_evidence_review_preflight",
    "build_platform_supervised_pilot_record",
    "review_platform_submission_evidence",
]

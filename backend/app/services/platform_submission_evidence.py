"""Platform consistency for independent submission-evidence review.

The existing Greenhouse evidence engine remains the canonical review mechanism.
This module adds platform and exact-target checks before an accepted decision and
normalizes platform-specific pilot records without opening a browser or submitting.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import Application, SubmissionEvidence
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.ats_lever import parse_lever_job_url
from app.services.operations_policy import platform_key_for_url
from app.services.submission_evidence_review import (
    ACCEPTED,
    SubmissionEvidenceReviewError,
    build_evidence_review_preflight,
    build_supervised_pilot_record,
    review_submission_evidence,
)


LEVER_PLATFORM = "lever"
_CONFIRMATION_ROUTE_TERMS = {
    "thanks",
    "thank-you",
    "thankyou",
    "confirmation",
    "application-confirmation",
    "application-submitted",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _latest_consumed_approval(
    db: Session,
    application_id: int,
) -> Optional[SubmissionApproval]:
    return (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.status == "consumed",
        )
        .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
        .first()
    )


def _target_verification(
    application: Application,
    evidence_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    metadata = evidence_snapshot.get("evidence_metadata")
    metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    direct = metadata.get("target_verification")
    if isinstance(direct, Mapping):
        return dict(direct)

    log = application.automation_log if isinstance(application.automation_log, list) else []
    for item in reversed(log):
        if not isinstance(item, Mapping):
            continue
        verification = item.get("target_verification")
        if isinstance(verification, Mapping):
            return dict(verification)
    return {}


def _lever_final_url_matches(
    final_url: str,
    target: Mapping[str, Any],
    *,
    confirmation_text_present: bool,
) -> bool:
    expected_site = str(target.get("site") or "")
    expected_posting_id = str(target.get("posting_id") or "")
    expected_region = str(target.get("region") or "")
    observed_site, observed_posting_id, observed_region = parse_lever_job_url(final_url)
    if observed_site != expected_site or observed_region != expected_region:
        return False
    if observed_posting_id == expected_posting_id:
        return True

    path_parts = [part.lower() for part in urlparse(final_url or "").path.split("/") if part]
    is_explicit_confirmation_route = bool(
        confirmation_text_present
        and path_parts
        and path_parts[0] == expected_site.lower()
        and any(part in _CONFIRMATION_ROUTE_TERMS for part in path_parts[1:])
    )
    return is_explicit_confirmation_route


def _platform_consistency(
    application: Application,
    approval: Optional[SubmissionApproval],
    evidence_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    blockers: list[str] = []
    approval_platform = str(getattr(approval, "platform", "") or "").strip().lower()
    approval_url_platform = (
        platform_key_for_url(str(getattr(approval, "application_url", "") or ""))
        if approval
        else "generic"
    )
    final_url = str(evidence_snapshot.get("final_url") or "")
    evidence_url_platform = platform_key_for_url(final_url) if final_url else "generic"
    evidence_metadata = evidence_snapshot.get("evidence_metadata")
    evidence_metadata = dict(evidence_metadata) if isinstance(evidence_metadata, Mapping) else {}
    verification = _target_verification(application, evidence_snapshot)
    evidence_adapter = str(
        evidence_metadata.get("adapter")
        or verification.get("platform")
        or verification.get("adapter")
        or ""
    ).strip().lower()

    if approval and approval_url_platform != approval_platform:
        blockers.append("approval_platform_target_mismatch")
    if (
        approval_platform
        and evidence_url_platform not in {"generic", approval_platform}
    ):
        blockers.append("evidence_platform_target_mismatch")
    if evidence_adapter and approval_platform and evidence_adapter != approval_platform:
        blockers.append("evidence_adapter_mismatch")

    target_identity: Dict[str, Any] = {}
    target_identity_hash: Optional[str] = None
    if approval_platform == LEVER_PLATFORM:
        approval_metadata = dict(approval.approval_metadata or {}) if approval else {}
        raw_target = approval_metadata.get("target_identity")
        target_identity = dict(raw_target) if isinstance(raw_target, Mapping) else {}
        target_identity_hash = str(
            approval_metadata.get("target_identity_hash") or ""
        ).strip() or None
        if not target_identity or not target_identity_hash:
            blockers.append("lever_approval_target_identity_missing")
        if not final_url or not _lever_final_url_matches(
            final_url,
            target_identity,
            confirmation_text_present=bool(
                evidence_snapshot.get("confirmation_text_present")
            ),
        ):
            blockers.append("lever_evidence_target_mismatch")
        if not verification:
            blockers.append("lever_target_verification_missing")
        elif not verification.get("verified"):
            blockers.append("lever_target_verification_failed")
        else:
            expected_pairs = {
                "expected_site": target_identity.get("site"),
                "expected_posting_id": target_identity.get("posting_id"),
                "expected_region": target_identity.get("region"),
                "expected_metadata_hash": target_identity.get("posting_metadata_hash"),
            }
            for key, expected in expected_pairs.items():
                observed = verification.get(key)
                if expected and observed and str(observed) != str(expected):
                    blockers.append("lever_target_verification_mismatch")
                    break

    blockers = list(dict.fromkeys(blockers))
    return {
        "blockers": blockers,
        "approval_platform": approval_platform or None,
        "approval_url_platform": approval_url_platform,
        "evidence_url_platform": evidence_url_platform,
        "evidence_adapter": evidence_adapter or None,
        "target_identity": target_identity,
        "target_identity_hash": target_identity_hash,
        "target_verification": verification,
    }


def build_platform_evidence_review_preflight(
    db: Session,
    application: Application,
    job: Job,
    evidence: SubmissionEvidence,
) -> Dict[str, Any]:
    preflight = build_evidence_review_preflight(db, application, job, evidence)
    approval = _latest_consumed_approval(db, application.id)
    consistency = _platform_consistency(
        application,
        approval,
        preflight["evidence"],
    )
    blockers = list(dict.fromkeys([
        *preflight["blockers"],
        *consistency["blockers"],
    ]))
    return {
        **preflight,
        "ready_for_acceptance": not blockers,
        "blockers": blockers,
        "platform": consistency["approval_platform"],
        "evidence_platform": consistency["evidence_url_platform"],
        "evidence_adapter": consistency["evidence_adapter"],
        "target_identity_hash": consistency["target_identity_hash"],
        "target_verification": consistency["target_verification"],
    }


def review_platform_submission_evidence(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    evidence: SubmissionEvidence,
    **kwargs,
) -> SubmissionEvidenceReview:
    decision = str(kwargs.get("decision") or "").strip().lower()
    preflight = build_platform_evidence_review_preflight(
        db,
        application,
        job,
        evidence,
    )
    if decision == ACCEPTED and not preflight["ready_for_acceptance"]:
        raise SubmissionEvidenceReviewError(
            "Evidence acceptance is blocked: " + ", ".join(preflight["blockers"])
        )

    review = review_submission_evidence(
        db,
        application,
        user,
        job,
        evidence,
        **kwargs,
    )
    review.review_metadata = {
        **dict(review.review_metadata or {}),
        "platform": preflight.get("platform"),
        "evidence_platform": preflight.get("evidence_platform"),
        "evidence_adapter": preflight.get("evidence_adapter"),
        "target_identity_hash": preflight.get("target_identity_hash"),
        "target_verification": preflight.get("target_verification") or {},
    }
    return review


def build_platform_supervised_pilot_record(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    record = build_supervised_pilot_record(db, application, user, job)
    approval = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.reference == record["approval_reference"])
        .first()
    )
    if not approval:
        raise SubmissionEvidenceReviewError("Consumed supervised approval evidence is missing")

    platform = str(approval.platform or "").strip().lower()
    if platform != LEVER_PLATFORM:
        return {**record, "platform": platform or record.get("adapter")}

    approval_metadata = dict(approval.approval_metadata or {})
    raw_target = approval_metadata.get("target_identity")
    target = dict(raw_target) if isinstance(raw_target, Mapping) else {}
    target_hash = str(approval_metadata.get("target_identity_hash") or "").strip()
    if not target or not target_hash:
        raise SubmissionEvidenceReviewError("Lever target identity evidence is missing")

    run_seed = {
        "application_id": application.id,
        "approval_reference": record["approval_reference"],
        "review_reference": record["review_reference"],
        "confirmation_evidence_reference": record["confirmation_evidence_reference"],
        "target_identity_hash": target_hash,
    }
    return {
        **record,
        "run_id": "lever-supervised-" + _hash_value(run_seed)[:20],
        "platform": LEVER_PLATFORM,
        "adapter": LEVER_PLATFORM,
        "adapter_version": approval_metadata.get("adapter_version"),
        "target_identity_hash": target_hash,
        "posting_metadata_hash": target.get("posting_metadata_hash"),
        "lever_site": target.get("site"),
        "lever_posting_id": target.get("posting_id"),
        "lever_region": target.get("region"),
        "canonical_application_url": target.get("canonical_application_url"),
    }


__all__ = [
    "build_platform_evidence_review_preflight",
    "build_platform_supervised_pilot_record",
    "review_platform_submission_evidence",
]

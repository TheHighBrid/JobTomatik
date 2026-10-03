"""Fail-closed Day 37 admission for the physical eight-hour shadow stage.

Day 37 is allowed to advance from a genuine, independently reviewed Day 36 four-hour
campaign even though the Day 37 tooling necessarily runs on a newer commit.  This
module therefore validates the predecessor against its own retained commit and the
Day 36 certifier instead of incorrectly requiring the predecessor SHA to equal the
current checkout.

Nothing in this module starts a campaign, changes adapter maturity, enables final
submit, authorizes outreach, or treats CI as physical evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.certification import CertificationEvidence, ShadowRunSession
from app.services.ats_manifest import ats_certification_manifest
from app.services.certification_scale import (
    canonical_hash,
    current_revision,
    ensure_aware,
    evidence_integrity_ok,
)
from app.services.day36_shadow_endurance import (
    DAY36_SECONDS,
    DAY36_TARGET,
    build_day36_shadow_endurance_report,
)
from app.services.runtime_acceptance import runtime_acceptance_status
from app.services.shadow_evidence_provenance import shadow_evidence_provenance_reasons
from app.services.shadow_qualification import campaign_policy_readiness


DAY37_TARGET = "shadow_run_8h"
DAY37_SECONDS = 8 * 60 * 60
DAY37_RUNTIME_RECEIPT_MAX_AGE_SECONDS = 15 * 60


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lever_state() -> dict[str, Any]:
    manifest = ats_certification_manifest()
    row = next(
        (
            dict(item)
            for item in manifest.get("adapters", [])
            if isinstance(item, dict) and str(item.get("name") or "").lower() == "lever"
        ),
        {},
    )
    return {
        "name": row.get("name"),
        "version": row.get("version") or row.get("adapter_version"),
        "maturity": row.get("maturity"),
        "autonomous_submission_allowed": bool(row.get("autonomous_submission_allowed")),
    }


def _linked_session(db, evidence_id: int) -> tuple[ShadowRunSession | None, list[str]]:
    rows = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.certification_evidence_id == int(evidence_id))
        .order_by(ShadowRunSession.id.asc())
        .all()
    )
    if not rows:
        return None, ["shadow_session_missing"]
    if len(rows) != 1:
        return None, ["shadow_session_evidence_link_not_unique"]
    return rows[0], []


def _predecessor_reasons(
    db,
    record: CertificationEvidence,
    *,
    user_id: int,
    now: datetime,
    root: Path | None,
) -> tuple[list[str], dict[str, Any] | None, ShadowRunSession | None]:
    reasons: list[str] = []
    if int(record.recorded_by_user_id or 0) != int(user_id):
        reasons.append("predecessor_owner_mismatch")
    if record.evidence_type != DAY36_TARGET:
        reasons.append("predecessor_type_not_shadow_run_4h")
    if record.status != "passed":
        reasons.append("predecessor_status_not_passed")
    if record.review_status != "verified":
        reasons.append("predecessor_not_independently_verified")
    expires_at = ensure_aware(record.expires_at)
    if expires_at is not None and expires_at <= now:
        reasons.append("predecessor_evidence_expired")
    if int(record.duration_seconds or 0) < DAY36_SECONDS:
        reasons.append("predecessor_duration_below_4h")
    if not evidence_integrity_ok(record):
        reasons.append("predecessor_payload_hash_mismatch")

    provenance = shadow_evidence_provenance_reasons(
        db,
        record,
        expected_user_id=int(user_id),
        canonical_hash=canonical_hash,
    )
    reasons.extend(f"predecessor_provenance:{item}" for item in provenance)

    session, link_reasons = _linked_session(db, int(record.id))
    reasons.extend(f"predecessor_provenance:{item}" for item in link_reasons)

    report: dict[str, Any] | None = None
    if session is not None and not reasons:
        try:
            report = build_day36_shadow_endurance_report(
                db,
                session_id=int(session.id),
                user_id=int(user_id),
                expected_revision=str(record.commit_sha or ""),
                root=root,
            )
        except Exception:
            reasons.append("predecessor_day36_certifier_failed")
        else:
            if report.get("passed") is not True:
                reasons.append("predecessor_day36_certifier_not_passed")
            if report.get("day37_entry_eligible") is not True:
                reasons.append("predecessor_day37_entry_not_eligible")
            if str(report.get("candidate_revision") or "") != str(record.commit_sha or ""):
                reasons.append("predecessor_certifier_revision_mismatch")

    return list(dict.fromkeys(reasons)), report, session


def day37_predecessor_admission(
    db,
    *,
    user_id: int,
    now: datetime | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return the newest genuinely qualifying Day 36 predecessor for one account.

    A later junk or unreviewed row must not eclipse an older valid predecessor, so every
    user-owned 4h record is inspected newest-first until one satisfies the full retained
    provenance and Day 36 certifier contract.
    """

    current = ensure_aware(now) or _utc_now()
    records = (
        db.query(CertificationEvidence)
        .filter(
            CertificationEvidence.recorded_by_user_id == int(user_id),
            CertificationEvidence.evidence_type == DAY36_TARGET,
        )
        .order_by(CertificationEvidence.created_at.desc(), CertificationEvidence.id.desc())
        .all()
    )
    attempts: list[dict[str, Any]] = []
    for record in records:
        reasons, report, session = _predecessor_reasons(
            db,
            record,
            user_id=int(user_id),
            now=current,
            root=root,
        )
        attempts.append(
            {
                "evidence_id": int(record.id),
                "commit_sha": str(record.commit_sha or ""),
                "review_status": str(record.review_status or ""),
                "reasons": reasons,
            }
        )
        if not reasons and report is not None and session is not None:
            return {
                "ok": True,
                "blockers": [],
                "predecessor": {
                    "evidence_id": int(record.id),
                    "session_id": int(session.id),
                    "candidate_revision": str(record.commit_sha or ""),
                    "day36_report_sha256": report.get("report_sha256"),
                    "retained_phase11_report_sha256": report.get(
                        "retained_phase11_report_sha256"
                    ),
                    "persisted_elapsed_seconds": report.get("persisted_elapsed_seconds"),
                    "review_status": str(record.review_status or ""),
                },
                "attempts": attempts,
            }

    blockers = ["verified_day36_predecessor_missing"]
    if records and attempts:
        blockers.extend(attempts[0]["reasons"])
    return {
        "ok": False,
        "blockers": list(dict.fromkeys(blockers)),
        "predecessor": None,
        "attempts": attempts,
    }


def day37_android_launch_admission(
    db,
    user,
    *,
    candidate_revision: str,
    requested_duration_seconds: int,
    now: datetime | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate every mutable boundary immediately before Android 8h insertion."""

    current = ensure_aware(now) or _utc_now()
    predecessor = day37_predecessor_admission(
        db,
        user_id=int(user.id),
        now=current,
        root=root,
    )
    runtime = runtime_acceptance_status(
        max_age_seconds=DAY37_RUNTIME_RECEIPT_MAX_AGE_SECONDS
    )
    policy = campaign_policy_readiness(
        db,
        user,
        requested_duration_seconds=DAY37_SECONDS,
        required_remaining_applications=1,
        now=current.replace(tzinfo=None),
    )
    settings = get_settings()
    revision = current_revision()
    lever = _lever_state()

    checks = {
        "target_is_exact_8h": int(requested_duration_seconds or 0) == DAY37_SECONDS,
        "candidate_revision_is_current_runtime": (
            str(candidate_revision or "") == str(revision or "") and revision != "unknown"
        ),
        "verified_day36_predecessor": predecessor.get("ok") is True,
        "fresh_exact_runtime_acceptance": runtime.get("ok") is True,
        "runtime_acceptance_revision_matches_campaign": (
            str(runtime.get("revision") or "") == str(candidate_revision or "")
        ),
        "campaign_policy_ready_for_8h": policy.get("ok") is True,
        "real_application_submit_disabled": settings.allow_real_application_submit is False,
        "real_followup_send_disabled": settings.allow_real_followup_send is False,
        "lever_still_frozen_dry_run": (
            lever.get("name") == "lever"
            and lever.get("version") == "1.1.0"
            and lever.get("maturity") == "dry_run"
            and lever.get("autonomous_submission_allowed") is False
        ),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    blockers.extend(f"day36:{item}" for item in predecessor.get("blockers") or [])
    blockers.extend(f"runtime:{item}" for item in runtime.get("blockers") or [])
    blockers.extend(f"policy:{item}" for item in policy.get("blockers") or [])
    blockers = list(dict.fromkeys(blockers))

    return {
        "ok": not blockers,
        "target_evidence_type": DAY37_TARGET,
        "requested_duration_seconds": int(requested_duration_seconds or 0),
        "candidate_revision": str(candidate_revision or ""),
        "current_revision": str(revision or ""),
        "checks": checks,
        "blockers": blockers,
        "predecessor": predecessor,
        "runtime_acceptance": {
            "ok": runtime.get("ok") is True,
            "blockers": list(runtime.get("blockers") or []),
            "revision": runtime.get("revision"),
            "runtime_fingerprint_sha256": (
                (runtime.get("runtime_fingerprint") or {}).get("sha256")
            ),
        },
        "policy": {
            "ok": policy.get("ok") is True,
            "blockers": list(policy.get("blockers") or []),
            "policy_profile": policy.get("policy_profile"),
        },
        "lever": lever,
        "safety": {
            "submission_authorized": False,
            "outreach_authorized": False,
            "promotion_authorized": False,
        },
    }


__all__ = [
    "DAY37_RUNTIME_RECEIPT_MAX_AGE_SECONDS",
    "DAY37_SECONDS",
    "DAY37_TARGET",
    "day37_android_launch_admission",
    "day37_predecessor_admission",
]

"""Validated Day 16 intake for retained Lever Phase B launch candidates.

The retained Day 15 launch artifacts are synthetic, read-only preparation
evidence. This module verifies their exact hashes and may materialize one
candidate as a user-owned Job/Application preparation record. It never issues
or consumes an approval, opens a browser, queues work, contacts Lever, or
submits an application.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ApplicationTargetStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    build_application_idempotency_key,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    find_existing_application_for_aliases,
)


LAUNCH_SCHEMA_VERSION = "1.1"
DOSSIER_SCOPE = "lever_supervised_phase_b_candidate"
SELECTION_POLICY = "user_selected_exact_application_no_ranking"
INTAKE_SOURCE = "retained_lever_phase_b_launch"
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_POSTING_ID = re.compile(r"^[A-Za-z0-9-]+$")
settings = get_settings()


class LeverPhaseBLaunchError(ValueError):
    """Raised when retained launch evidence or materialization is unsafe."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LeverPhaseBLaunchError(f"{label} must be a JSON object")
    return dict(value)


def _required_text(value: Any, label: str, max_length: int = 1000) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise LeverPhaseBLaunchError(f"{label} is required")
    if len(cleaned) > max_length:
        raise LeverPhaseBLaunchError(f"{label} exceeds {max_length} characters")
    return cleaned


def _sha256(value: Any, label: str) -> str:
    cleaned = _required_text(value, label, 64).lower()
    if not _HEX_SHA256.fullmatch(cleaned):
        raise LeverPhaseBLaunchError(f"{label} must be a lowercase SHA-256")
    return cleaned


def _safe_path(root: Path, relative_value: Any, label: str) -> Path:
    relative = Path(_required_text(relative_value, label, 500))
    if relative.is_absolute():
        raise LeverPhaseBLaunchError(f"{label} must be relative")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LeverPhaseBLaunchError(f"{label} escapes the evidence root") from exc
    return candidate


def normalize_lever_application_url(value: str) -> str:
    raw = _required_text(value, "application_url", 1000)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise LeverPhaseBLaunchError("application_url is invalid") from exc

    if parsed.scheme.lower() != "https":
        raise LeverPhaseBLaunchError("application_url must use HTTPS")
    if parsed.username or parsed.password:
        raise LeverPhaseBLaunchError(
            "application_url must not contain embedded credentials"
        )
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in {"jobs.lever.co", "jobs.eu.lever.co"}:
        raise LeverPhaseBLaunchError(
            "application_url must use an official Lever jobs host"
        )
    if port not in (None, 443):
        raise LeverPhaseBLaunchError(
            "application_url must not use a non-standard port"
        )
    if parsed.query or parsed.fragment:
        raise LeverPhaseBLaunchError(
            "application_url must not contain a query string or fragment"
        )

    parts = [part for part in parsed.path.split("/") if part]
    if (
        len(parts) != 3
        or parts[2].casefold() != "apply"
        or not _IDENTIFIER.fullmatch(parts[0])
        or not _POSTING_ID.fullmatch(parts[1])
    ):
        raise LeverPhaseBLaunchError(
            "application_url must identify one exact Lever application"
        )
    path = f"/{parts[0]}/{parts[1]}/apply"
    return urlunsplit(("https", host, path, "", ""))


def _read_json(path: Path, label: str) -> tuple[Dict[str, Any], bytes]:
    if not path.is_file():
        raise LeverPhaseBLaunchError(f"{label} is missing")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseBLaunchError(f"{label} is not valid JSON") from exc
    return _mapping(payload, label), raw


def _validate_selection_receipt(
    evidence_root: Path,
    launch: Mapping[str, Any],
) -> Dict[str, str]:
    receipt = _mapping(launch.get("selection_receipt"), "selection_receipt")
    relative = _required_text(receipt.get("path"), "selection_receipt.path", 500)
    expected_sha = _sha256(receipt.get("sha256"), "selection_receipt.sha256")
    path = _safe_path(evidence_root, relative, "selection_receipt.path")
    payload, raw = _read_json(path, "selection receipt")
    if _sha256_bytes(raw) != expected_sha:
        raise LeverPhaseBLaunchError("selection receipt hash mismatch")
    if payload.get("selected_by_user") is not True:
        raise LeverPhaseBLaunchError(
            "selection receipt is not explicitly user-selected"
        )
    requested = _mapping(
        payload.get("requested_action"),
        "selection receipt requested_action",
    )
    for key in ("build_read_only_dossiers", "run_no_submit_previews"):
        if requested.get(key) is not True:
            raise LeverPhaseBLaunchError(
                f"selection receipt must retain {key}=true"
            )
    for key in (
        "authorize_final_submit",
        "authorize_supervised_submission",
        "authorize_adapter_promotion",
    ):
        if requested.get(key) is not False:
            raise LeverPhaseBLaunchError(
                f"selection receipt must retain {key}=false"
            )
    return {
        "path": relative,
        "sha256": expected_sha,
        "receipt_id": _required_text(
            receipt.get("receipt_id"),
            "selection_receipt.receipt_id",
            255,
        ),
    }


def _validate_preview(value: Mapping[str, Any], label: str) -> None:
    if value.get("passed") is not True:
        raise LeverPhaseBLaunchError(f"{label} preview did not pass")
    if value.get("outcome") != "ready_to_submit":
        raise LeverPhaseBLaunchError(f"{label} preview is not ready_to_submit")
    if value.get("ready_to_submit") is not True:
        raise LeverPhaseBLaunchError(f"{label} preview is not marked ready")
    if value.get("requires_manual_review") is not False:
        raise LeverPhaseBLaunchError(
            f"{label} preview still requires manual review"
        )
    if value.get("final_submit_clicked") is not False:
        raise LeverPhaseBLaunchError(
            f"{label} preview indicates a submit click"
        )
    if value.get("retained_phase_a_preview") is not True:
        raise LeverPhaseBLaunchError(
            f"{label} preview is not retained Phase A evidence"
        )


def _validate_candidate(
    evidence_root: Path,
    raw_candidate: Any,
    selection_receipt: Mapping[str, str],
) -> Dict[str, Any]:
    candidate = _mapping(raw_candidate, "launch candidate")
    application_id = _required_text(candidate.get("application_id"), "application_id", 500)
    if candidate.get("platform") != "lever":
        raise LeverPhaseBLaunchError("launch candidate platform must be lever")
    if candidate.get("selected_by_user") is not True:
        raise LeverPhaseBLaunchError(
            "launch candidate is not explicitly user-selected"
        )
    if (
        _sha256(
            candidate.get("selection_receipt_sha256"),
            "selection_receipt_sha256",
        )
        != selection_receipt["sha256"]
    ):
        raise LeverPhaseBLaunchError(
            "candidate selection receipt hash does not match launch receipt"
        )

    target = _mapping(candidate.get("target"), "candidate target")
    employer = _required_text(target.get("employer"), "target.employer", 255)
    role = _required_text(target.get("role"), "target.role", 500)
    site = _required_text(target.get("site"), "target.site", 100)
    posting_id = _required_text(target.get("posting_id"), "target.posting_id", 255)
    location = str(target.get("location") or "").strip()[:255] or None
    region = _required_text(target.get("region"), "target.region", 30)
    normalized_url = normalize_lever_application_url(
        _required_text(target.get("application_url"), "target.application_url", 1000)
    )
    if target.get("platform") != "lever":
        raise LeverPhaseBLaunchError("candidate target platform must be lever")
    url_parts = [part for part in urlsplit(normalized_url).path.split("/") if part]
    if url_parts[0].casefold() != site.casefold():
        raise LeverPhaseBLaunchError("candidate target site does not match URL")
    if url_parts[1] != posting_id:
        raise LeverPhaseBLaunchError(
            "candidate target posting_id does not match URL"
        )
    expected_application_id = f"lever:{site.casefold()}:{posting_id}"
    if application_id != expected_application_id:
        raise LeverPhaseBLaunchError(
            "candidate application_id does not match its exact target"
        )

    dossier_meta = _mapping(candidate.get("dossier"), "candidate dossier")
    if dossier_meta.get("read_only") is not True:
        raise LeverPhaseBLaunchError("candidate dossier must remain read-only")
    if dossier_meta.get("one_time_approval_required") is not True:
        raise LeverPhaseBLaunchError(
            "candidate dossier must require one-time approval"
        )
    dossier_artifact_sha = _sha256(
        dossier_meta.get("artifact_sha256"),
        "dossier.artifact_sha256",
    )
    dossier_sha = _sha256(
        dossier_meta.get("dossier_sha256"),
        "dossier.dossier_sha256",
    )
    dossier_relative = _required_text(
        dossier_meta.get("artifact_path"),
        "dossier.artifact_path",
        500,
    )
    dossier_path = _safe_path(
        evidence_root,
        dossier_relative,
        "dossier.artifact_path",
    )
    dossier, dossier_bytes = _read_json(dossier_path, "Lever Phase B dossier")
    if _sha256_bytes(dossier_bytes) != dossier_artifact_sha:
        raise LeverPhaseBLaunchError("dossier artifact hash mismatch")
    if dossier.get("application_id") != application_id:
        raise LeverPhaseBLaunchError(
            "dossier application_id does not match launch candidate"
        )
    if _sha256(dossier.get("dossier_sha256"), "retained dossier_sha256") != dossier_sha:
        raise LeverPhaseBLaunchError(
            "retained dossier_sha256 does not match launch candidate"
        )
    canonical_dossier = dict(dossier)
    canonical_dossier.pop("dossier_sha256", None)
    canonical_dossier.pop("download_filename", None)
    if _canonical_sha256(canonical_dossier) != dossier_sha:
        raise LeverPhaseBLaunchError("dossier canonical hash mismatch")
    if dossier.get("read_only") is not True:
        raise LeverPhaseBLaunchError("retained dossier must remain read-only")
    if dossier.get("scope") != DOSSIER_SCOPE:
        raise LeverPhaseBLaunchError("retained dossier scope is invalid")
    if dossier.get("selection_policy") != SELECTION_POLICY:
        raise LeverPhaseBLaunchError(
            "retained dossier selection policy is invalid"
        )

    kill_switches = _mapping(dossier.get("kill_switches"), "dossier kill_switches")
    for key, expected in {
        "adapter_promotion_allowed": False,
        "final_submit_allowed": False,
        "one_time_approval_required": True,
        "supervised_submission_allowed": False,
    }.items():
        if kill_switches.get(key) is not expected:
            raise LeverPhaseBLaunchError(f"unsafe dossier kill switch: {key}")

    source_phase_a = _mapping(dossier.get("source_phase_a"), "dossier source_phase_a")
    review_id = _required_text(source_phase_a.get("review_id"), "source_phase_a.review_id", 100)
    if source_phase_a.get("synthetic_profile") is not True:
        raise LeverPhaseBLaunchError(
            "Day 15 dossier must retain a synthetic Phase A source"
        )
    if source_phase_a.get("final_status") != "dry_run_passed":
        raise LeverPhaseBLaunchError(
            "Day 15 source must remain a qualifying dry run"
        )
    if source_phase_a.get("pre_submit_state") != "ready_to_submit":
        raise LeverPhaseBLaunchError(
            "Day 15 source must remain ready_to_submit"
        )
    if source_phase_a.get("official_posting_inspection_passed") is not True:
        raise LeverPhaseBLaunchError(
            "Day 15 source must retain official inspection"
        )

    dossier_target = _mapping(dossier.get("target"), "dossier target")
    for key, expected in {
        "application_url": normalized_url,
        "employer": employer,
        "location": location or "",
        "platform": "lever",
        "posting_id": posting_id,
        "region": region,
        "role": role,
        "site": site,
    }.items():
        actual = dossier_target.get(key)
        if key == "location":
            actual = str(actual or "")
        if str(actual or "") != str(expected or ""):
            raise LeverPhaseBLaunchError(
                f"dossier target {key} does not match launch candidate"
            )

    preview = _mapping(candidate.get("dry_preview"), "candidate dry_preview")
    dossier_preview = _mapping(dossier.get("dry_preview"), "dossier dry_preview")
    _validate_preview(preview, "candidate")
    _validate_preview(dossier_preview, "dossier")
    for key in ("source_report_path", "source_report_sha256"):
        if str(preview.get(key) or "") != str(dossier_preview.get(key) or ""):
            raise LeverPhaseBLaunchError(
                f"candidate and dossier preview {key} mismatch"
            )

    selection_reference = _required_text(
        candidate.get("selection_reference"),
        "selection_reference",
        700,
    )
    if selection_reference != f"{selection_receipt['path']}#{review_id}":
        raise LeverPhaseBLaunchError(
            "candidate selection reference does not match retained review"
        )

    return {
        "application_id": application_id,
        "review_id": review_id,
        "employer": employer,
        "role": role,
        "location": location,
        "application_url": normalized_url,
        "site": site,
        "posting_id": posting_id,
        "region": region,
        "selection_reference": selection_reference,
        "selection_receipt_sha256": selection_receipt["sha256"],
        "dossier_artifact_path": dossier_relative,
        "dossier_artifact_sha256": dossier_artifact_sha,
        "dossier_sha256": dossier_sha,
        "source_report_path": _required_text(
            preview.get("source_report_path"),
            "dry_preview.source_report_path",
            500,
        ),
        "source_report_sha256": _sha256(
            preview.get("source_report_sha256"),
            "dry_preview.source_report_sha256",
        ),
        "synthetic_preview": True,
        "read_only": True,
        "one_time_approval_required": True,
    }


def read_lever_phase_b_launch(path_value: Optional[str] = None) -> Dict[str, Any]:
    launch_path = Path(path_value or settings.lever_phase_b_launch_path).resolve()
    evidence_root = launch_path.parent.resolve()
    launch, _raw = _read_json(launch_path, "Lever Phase B launch artifact")
    if launch.get("schema_version") != LAUNCH_SCHEMA_VERSION:
        raise LeverPhaseBLaunchError("unsupported Lever Phase B launch schema")
    selection_receipt = _validate_selection_receipt(evidence_root, launch)
    raw_candidates = launch.get("applications")
    if not isinstance(raw_candidates, list) or len(raw_candidates) != 2:
        raise LeverPhaseBLaunchError(
            "retained Day 15 launch must contain exactly two candidates"
        )
    candidates = [
        _validate_candidate(evidence_root, item, selection_receipt)
        for item in raw_candidates
    ]
    application_ids = [item["application_id"] for item in candidates]
    review_ids = [item["review_id"] for item in candidates]
    if len(set(application_ids)) != len(application_ids):
        raise LeverPhaseBLaunchError(
            "retained launch contains duplicate application IDs"
        )
    if len(set(review_ids)) != len(review_ids):
        raise LeverPhaseBLaunchError(
            "retained launch contains duplicate review IDs"
        )
    return {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "selection_receipt": selection_receipt,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _find_job(db: Session, candidate: Mapping[str, Any]) -> Optional[Job]:
    return (
        db.query(Job)
        .filter(
            or_(
                func.lower(Job.external_id) == str(candidate["application_id"]).casefold(),
                Job.url == candidate["application_url"],
            )
        )
        .order_by(Job.id.asc())
        .first()
    )


def _validate_existing_job(job: Job, candidate: Mapping[str, Any]) -> None:
    selected_url = str(
        dict(job.raw_data or {}).get("selected_apply_url") or job.url or ""
    ).strip()
    if normalize_lever_application_url(selected_url) != candidate["application_url"]:
        raise LeverPhaseBLaunchError(
            "existing job URL does not match retained Lever target"
        )
    if str(job.title or "").strip().casefold() != str(candidate["role"]).casefold():
        raise LeverPhaseBLaunchError(
            "existing job role does not match retained Lever target"
        )
    if str(job.company or "").strip().casefold() != str(candidate["employer"]).casefold():
        raise LeverPhaseBLaunchError(
            "existing job employer does not match retained Lever target"
        )


def _materialized_application(
    db: Session,
    user_id: int,
    job: Optional[Job],
) -> Optional[Application]:
    if not job:
        return None
    return (
        db.query(Application)
        .filter(
            Application.user_id == user_id,
            Application.job_id == job.id,
        )
        .order_by(Application.id.asc())
        .first()
    )


def build_lever_phase_b_launch_status(db: Session, user: User) -> Dict[str, Any]:
    launch = read_lever_phase_b_launch()
    candidates = []
    for candidate in launch["candidates"]:
        job = _find_job(db, candidate)
        application = _materialized_application(db, user.id, job)
        candidates.append(
            {
                **candidate,
                "materialized": application is not None,
                "job_id": job.id if job else None,
                "materialized_application_id": application.id if application else None,
                "automation_state": application.automation_state if application else None,
                "submission_queued": False,
                "approval_issued": False,
                "runtime_flags_changed": False,
            }
        )
    return {
        "schema_version": launch["schema_version"],
        "selection_receipt": launch["selection_receipt"],
        "candidate_count": launch["candidate_count"],
        "materialized_count": sum(1 for item in candidates if item["materialized"]),
        "preparation_only": True,
        "candidates": candidates,
    }


def materialize_lever_phase_b_candidate(
    db: Session,
    user: User,
    *,
    review_id: str,
) -> Dict[str, Any]:
    requested_review_id = _required_text(review_id, "review_id", 100)
    launch = read_lever_phase_b_launch()
    matches = [
        candidate
        for candidate in launch["candidates"]
        if candidate["review_id"] == requested_review_id
    ]
    if len(matches) != 1:
        raise LeverPhaseBLaunchError(
            "retained Lever launch candidate was not found"
        )
    candidate = matches[0]
    target_digest = hashlib.sha256(
        candidate["application_url"].encode("utf-8")
    ).hexdigest()

    job = _find_job(db, candidate)
    created_job = job is None
    if job is not None:
        _validate_existing_job(job, candidate)

    try:
        with db.begin_nested():
            if job is None:
                job = Job(
                    external_id=candidate["application_id"],
                    title=candidate["role"],
                    company=candidate["employer"],
                    location=candidate["location"],
                    url=candidate["application_url"],
                    source=JobSource.lever,
                    status=JobStatus.queued,
                    relevance_score=0.0,
                    raw_data={
                        "application_method": "external_url",
                        "selected_apply_url": candidate["application_url"],
                        "official_public_ats": True,
                        "ats_provider": "lever",
                        "ats_identifier": candidate["site"],
                        "provider_job_id": candidate["posting_id"],
                        "selection_policy": SELECTION_POLICY,
                        "selection_source": INTAKE_SOURCE,
                        "selection_reference": candidate["selection_reference"],
                        "selection_receipt_sha256": candidate[
                            "selection_receipt_sha256"
                        ],
                        "review_id": candidate["review_id"],
                        "dossier_artifact_path": candidate[
                            "dossier_artifact_path"
                        ],
                        "dossier_artifact_sha256": candidate[
                            "dossier_artifact_sha256"
                        ],
                        "dossier_sha256": candidate["dossier_sha256"],
                        "source_report_path": candidate["source_report_path"],
                        "source_report_sha256": candidate[
                            "source_report_sha256"
                        ],
                        "synthetic_preview": True,
                        "read_only_launch_evidence": True,
                    },
                )
                db.add(job)
                db.flush()

            aliases = build_submission_identity_aliases(job)
            application = find_existing_application_for_aliases(
                db,
                user.id,
                aliases,
            )
            if application is None:
                application = _materialized_application(db, user.id, job)
            idempotency_key = build_application_idempotency_key(
                user.id,
                aliases,
                fallback_job_id=job.id,
            )
            if application is None:
                application = (
                    db.query(Application)
                    .filter(
                        Application.submission_idempotency_key == idempotency_key
                    )
                    .first()
                )

            created_application = application is None
            if application is None:
                application = Application(
                    user_id=user.id,
                    job_id=job.id,
                    status=ApplicationStatus.pending,
                    automation_state=ApplicationAutomationState.preparing.value,
                    source_listing_url=candidate["application_url"],
                    application_target_url=candidate["application_url"],
                    application_target_status=ApplicationTargetStatus.resolved.value,
                    application_target_metadata={
                        "platform": "lever",
                        "selection_source": INTAKE_SOURCE,
                        "selection_reference": candidate["selection_reference"],
                        "review_id": candidate["review_id"],
                        "site": candidate["site"],
                        "posting_id": candidate["posting_id"],
                        "region": candidate["region"],
                        "dossier_sha256": candidate["dossier_sha256"],
                        "synthetic_preview": True,
                        "requires_fresh_runtime_preflight": True,
                    },
                    submission_idempotency_key=idempotency_key,
                    notes=(
                        "Retained Lever Phase B launch candidate "
                        f"{candidate['review_id']}. Preparation only; "
                        "fresh real-payload preflight and separate approval "
                        "remain required."
                    ),
                )
                db.add(application)
                db.flush()
                claim_submission_identity_aliases(db, application, aliases)
                db.add(
                    ApplicationEvent(
                        application_id=application.id,
                        event_type="lever_phase_b_launch_candidate_materialized",
                        from_state=None,
                        to_state=ApplicationAutomationState.preparing.value,
                        payload={
                            "job_id": job.id,
                            "platform": "lever",
                            "review_id": candidate["review_id"],
                            "launch_application_id": candidate["application_id"],
                            "selection_policy": SELECTION_POLICY,
                            "selection_source": INTAKE_SOURCE,
                            "selection_reference": candidate[
                                "selection_reference"
                            ],
                            "selection_receipt_sha256": candidate[
                                "selection_receipt_sha256"
                            ],
                            "dossier_artifact_sha256": candidate[
                                "dossier_artifact_sha256"
                            ],
                            "dossier_sha256": candidate["dossier_sha256"],
                            "source_report_sha256": candidate[
                                "source_report_sha256"
                            ],
                            "application_url_sha256": target_digest,
                            "synthetic_preview": True,
                            "requires_fresh_runtime_preflight": True,
                            "submission_queued": False,
                            "approval_issued": False,
                            "runtime_flags_changed": False,
                        },
                    )
                )
    except (IntegrityError, DuplicateSubmissionIdentityError) as exc:
        raise LeverPhaseBLaunchError(
            "duplicate Lever launch materialization was blocked"
        ) from exc

    return {
        "review_id": candidate["review_id"],
        "launch_application_id": candidate["application_id"],
        "application_id": application.id,
        "job_id": job.id,
        "created_job": created_job,
        "created_application": created_application,
        "employer": job.company,
        "role": job.title,
        "application_url": candidate["application_url"],
        "automation_state": application.automation_state,
        "selection_policy": SELECTION_POLICY,
        "synthetic_preview": True,
        "requires_fresh_runtime_preflight": True,
        "submission_queued": False,
        "approval_issued": False,
        "runtime_flags_changed": False,
    }


__all__ = [
    "INTAKE_SOURCE",
    "LeverPhaseBLaunchError",
    "SELECTION_POLICY",
    "build_lever_phase_b_launch_status",
    "materialize_lever_phase_b_candidate",
    "normalize_lever_application_url",
    "read_lever_phase_b_launch",
]

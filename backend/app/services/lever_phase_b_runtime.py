"""Runtime-safe materialization for retained Lever Phase B launch evidence.

The canonical Day 15 parser validates the launch receipt and dossiers. This
layer adds the runtime checks needed before those records enter a user's
workspace: it independently verifies the referenced Phase A report bytes,
requires every retained selection safety declaration, and treats Lever hosted
and `/apply` URLs as the same exact posting identity.

Nothing in this module issues approvals, opens a browser, queues work, contacts
an ATS, changes campaign evidence, or submits an application.
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
from app.services.lever_phase_b_launch import (
    INTAKE_SOURCE,
    SELECTION_POLICY,
    LeverPhaseBLaunchError,
    read_lever_phase_b_launch,
)
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    build_application_idempotency_key,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    find_existing_application_for_aliases,
)


_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_POSTING_ID = re.compile(r"^[A-Za-z0-9-]+$")
settings = get_settings()


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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LeverPhaseBLaunchError(f"{label} must be a JSON object")
    return dict(value)


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


def _read_json(path: Path, label: str) -> tuple[Dict[str, Any], bytes]:
    if not path.is_file():
        raise LeverPhaseBLaunchError(f"{label} is missing")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LeverPhaseBLaunchError(f"{label} is not valid JSON") from exc
    return _mapping(payload, label), raw


def canonical_lever_application_url(value: str) -> str:
    """Return the exact `/apply` URL for a Lever hosted or apply URL."""

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
    hosted = len(parts) == 2
    apply = len(parts) == 3 and parts[2].casefold() == "apply"
    if (
        not (hosted or apply)
        or not _IDENTIFIER.fullmatch(parts[0])
        or not _POSTING_ID.fullmatch(parts[1])
    ):
        raise LeverPhaseBLaunchError(
            "application_url must identify one exact Lever posting"
        )
    return urlunsplit(
        ("https", host, f"/{parts[0]}/{parts[1]}/apply", "", "")
    )


def _verify_selection_safety(
    evidence_root: Path,
    launch: Mapping[str, Any],
) -> None:
    receipt = _mapping(launch.get("selection_receipt"), "selection_receipt")
    receipt_path = _safe_path(
        evidence_root,
        receipt.get("path"),
        "selection_receipt.path",
    )
    payload, raw = _read_json(receipt_path, "selection receipt")
    expected_sha = _sha256(receipt.get("sha256"), "selection_receipt.sha256")
    if _sha256_bytes(raw) != expected_sha:
        raise LeverPhaseBLaunchError("selection receipt hash mismatch")

    safety = _mapping(payload.get("safety"), "selection receipt safety")
    for key in (
        "final_submit_must_remain_false",
        "no_captcha_bypass",
        "no_sensitive_or_legal_answer_inference",
        "one_time_approval_still_required",
    ):
        if safety.get(key) is not True:
            raise LeverPhaseBLaunchError(
                f"selection receipt safety control is not true: {key}"
            )


def _verify_phase_a_source(
    evidence_root: Path,
    candidate: Mapping[str, Any],
) -> None:
    relative = _required_text(
        candidate.get("source_report_path"),
        "source_report_path",
        500,
    )
    expected_sha = _sha256(
        candidate.get("source_report_sha256"),
        "source_report_sha256",
    )
    path = _safe_path(evidence_root, relative, "source_report_path")
    report, raw = _read_json(path, "Lever Phase A source report")
    if _sha256_bytes(raw) != expected_sha:
        raise LeverPhaseBLaunchError("Phase A source report hash mismatch")
    if report.get("passed") is not True:
        raise LeverPhaseBLaunchError("Phase A source report did not pass")
    if report.get("final_submit_clicked") is not False:
        raise LeverPhaseBLaunchError(
            "Phase A source report indicates a submit click"
        )


def read_runtime_lever_phase_b_launch() -> Dict[str, Any]:
    launch_path = Path(settings.lever_phase_b_launch_path).resolve()
    evidence_root = launch_path.parent.resolve()
    retained = read_lever_phase_b_launch(str(launch_path))

    launch_payload, _raw = _read_json(
        launch_path,
        "Lever Phase B launch artifact",
    )
    _verify_selection_safety(evidence_root, launch_payload)

    for candidate in retained["candidates"]:
        canonical = canonical_lever_application_url(
            candidate["application_url"]
        )
        if canonical != candidate["application_url"]:
            raise LeverPhaseBLaunchError(
                "retained candidate URL is not the canonical Lever apply URL"
            )
        _verify_phase_a_source(evidence_root, candidate)
    return retained


def _hosted_url(application_url: str) -> str:
    return application_url.removesuffix("/apply")


def _find_job(db: Session, candidate: Mapping[str, Any]) -> Optional[Job]:
    application_url = str(candidate["application_url"])
    return (
        db.query(Job)
        .filter(
            or_(
                func.lower(Job.external_id)
                == str(candidate["application_id"]).casefold(),
                Job.url == application_url,
                Job.url == _hosted_url(application_url),
            )
        )
        .order_by(Job.id.asc())
        .first()
    )


def _validate_existing_job(job: Job, candidate: Mapping[str, Any]) -> None:
    raw = dict(job.raw_data or {})
    selected_url = str(
        raw.get("selected_apply_url") or job.url or ""
    ).strip()
    if canonical_lever_application_url(selected_url) != candidate["application_url"]:
        raise LeverPhaseBLaunchError(
            "existing job URL does not match retained Lever target"
        )
    if str(job.title or "").strip().casefold() != str(candidate["role"]).casefold():
        raise LeverPhaseBLaunchError(
            "existing job role does not match retained Lever target"
        )
    if str(job.company or "").strip().casefold() != str(
        candidate["employer"]
    ).casefold():
        raise LeverPhaseBLaunchError(
            "existing job employer does not match retained Lever target"
        )


def _application_for_job(
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


def build_runtime_lever_phase_b_launch_status(
    db: Session,
    user: User,
) -> Dict[str, Any]:
    launch = read_runtime_lever_phase_b_launch()
    candidates = []
    for candidate in launch["candidates"]:
        job = _find_job(db, candidate)
        if job:
            _validate_existing_job(job, candidate)
        application = _application_for_job(db, user.id, job)
        candidates.append(
            {
                **candidate,
                "materialized": application is not None,
                "job_id": job.id if job else None,
                "materialized_application_id": (
                    application.id if application else None
                ),
                "automation_state": (
                    application.automation_state if application else None
                ),
                "submission_queued": False,
                "approval_issued": False,
                "runtime_flags_changed": False,
            }
        )
    return {
        "schema_version": launch["schema_version"],
        "selection_receipt": launch["selection_receipt"],
        "candidate_count": launch["candidate_count"],
        "materialized_count": sum(
            1 for candidate in candidates if candidate["materialized"]
        ),
        "preparation_only": True,
        "candidates": candidates,
    }


def materialize_runtime_lever_phase_b_candidate(
    db: Session,
    user: User,
    *,
    review_id: str,
) -> Dict[str, Any]:
    requested_review_id = _required_text(review_id, "review_id", 100)
    launch = read_runtime_lever_phase_b_launch()
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
    if job:
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
                        "selection_reference": candidate[
                            "selection_reference"
                        ],
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
                        "source_report_path": candidate[
                            "source_report_path"
                        ],
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
                application = _application_for_job(db, user.id, job)
            if application is not None and application.job_id != job.id:
                application_job = (
                    db.query(Job).filter(Job.id == application.job_id).first()
                )
                if not application_job:
                    raise LeverPhaseBLaunchError(
                        "existing application job is missing"
                    )
                _validate_existing_job(application_job, candidate)
                job = application_job

            idempotency_key = build_application_idempotency_key(
                user.id,
                aliases,
                fallback_job_id=job.id,
            )
            if application is None:
                application = (
                    db.query(Application)
                    .filter(
                        Application.submission_idempotency_key
                        == idempotency_key
                    )
                    .first()
                )

            created_application = application is None
            if application is None:
                application = Application(
                    user_id=user.id,
                    job_id=job.id,
                    status=ApplicationStatus.pending,
                    automation_state=(
                        ApplicationAutomationState.preparing.value
                    ),
                    source_listing_url=candidate["application_url"],
                    application_target_url=candidate["application_url"],
                    application_target_status=(
                        ApplicationTargetStatus.resolved.value
                    ),
                    application_target_metadata={
                        "platform": "lever",
                        "selection_source": INTAKE_SOURCE,
                        "selection_reference": candidate[
                            "selection_reference"
                        ],
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
                        f"{candidate['review_id']}. Preparation only; fresh "
                        "real-payload preflight and separate approval remain "
                        "required."
                    ),
                )
                db.add(application)
                db.flush()
                claim_submission_identity_aliases(db, application, aliases)
                db.add(
                    ApplicationEvent(
                        application_id=application.id,
                        event_type=(
                            "lever_phase_b_launch_candidate_materialized"
                        ),
                        from_state=None,
                        to_state=(
                            ApplicationAutomationState.preparing.value
                        ),
                        payload={
                            "job_id": job.id,
                            "platform": "lever",
                            "review_id": candidate["review_id"],
                            "launch_application_id": candidate[
                                "application_id"
                            ],
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
                            "dossier_sha256": candidate[
                                "dossier_sha256"
                            ],
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
    "build_runtime_lever_phase_b_launch_status",
    "canonical_lever_application_url",
    "materialize_runtime_lever_phase_b_candidate",
    "read_runtime_lever_phase_b_launch",
]

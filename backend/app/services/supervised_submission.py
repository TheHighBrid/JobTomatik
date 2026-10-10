"""Exact-payload approval gate for supervised ATS submissions.

This service never submits an application. It creates short-lived, one-time
approval records bound to an exact employer, role, URL, idempotency key, profile,
resume, cover letter, approved answer-policy payload, and any platform-required
target identity. Any mutation, expiry, open review, unsupported platform, or
feature-flag change invalidates the approval.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.submission_approval import (
    SubmissionApproval,
    SubmissionApprovalStatus,
)
from app.models.user import User
from app.services.answer_policy import load_runtime_policies
from app.services.ats_greenhouse import inspect_greenhouse_schema, parse_greenhouse_job_url
from app.services.operations_policy import platform_key_for_url
from app.services.supervised_platforms import (
    GREENHOUSE_PLATFORM_KEY,
    SupervisedPlatformPolicy,
    get_supervised_platform_policy,
)
from app.services.supervised_target_identity import (
    persisted_supervised_target_metadata,
    target_identity_hash,
    target_url_for_job,
)


settings = get_settings()
# Compatibility alias for existing imports. Operational decisions use the registry.
SUPPORTED_PLATFORM = GREENHOUSE_PLATFORM_KEY
MANUAL_GREENHOUSE_PHASE_B_SOURCE = "manual_greenhouse_phase_b"
TARGET_LIVENESS_TIMEOUT_SECONDS = 5.0
FORM_SCHEMA_TIMEOUT_SECONDS = 5.0
FORM_SCHEMA_FINGERPRINT_VERSION = 1


class SupervisedSubmissionApprovalError(ValueError):
    pass


class SupervisedSubmissionApprovalExpired(SupervisedSubmissionApprovalError):
    pass


class SupervisedSubmissionApprovalMismatch(SupervisedSubmissionApprovalError):
    pass


def _now() -> datetime:
    """Return timezone-aware UTC now.

    SubmissionApproval.expires_at / approved_at / etc. are DateTime(timezone=True).
    Comparing a naive datetime.utcnow() against those columns raises:
    TypeError: can't compare offset-naive and offset-aware datetimes
    This was the concrete blocker on Affirm application #14 (2026-10-10).
    """
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hash_file(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

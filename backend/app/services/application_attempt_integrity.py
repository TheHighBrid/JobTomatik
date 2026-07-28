"""Fail-closed checkpoint guard for browser results returned by stale workers."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.services.application_state import (
    ApplicationAttemptCheckpointLost,
    claim_application_attempt_result,
)


logger = logging.getLogger(__name__)
_INSTALLED = False
_ORIGINAL_RECORD_RESULT_EVIDENCE = None


def install_application_attempt_result_guard() -> None:
    """Reject external results unless the originating attempt is still active.

    The application worker commits its ``applying`` checkpoint before opening a
    browser. During that browser work, recovery or a newer worker can change the row.
    This wrapper validates the persisted state and attempt counter immediately before
    any returned evidence is recorded. A mismatch raises into Celery's retry path; the
    retry then observes the newer authoritative state and exits idempotently.
    """

    global _INSTALLED, _ORIGINAL_RECORD_RESULT_EVIDENCE
    if _INSTALLED:
        return

    from app.tasks import applications as application_tasks

    _ORIGINAL_RECORD_RESULT_EVIDENCE = application_tasks._record_result_evidence

    def guarded_record_result_evidence(
        db,
        application,
        result: Dict[str, Any],
    ) -> None:
        expected_attempt = int(application.submission_attempt_count or 0)
        checked = claim_application_attempt_result(
            db,
            application.id,
            expected_attempt,
        )
        if checked is None:
            logger.warning(
                "Discarding stale application result application=%s attempt=%s",
                application.id,
                expected_attempt,
            )
            raise ApplicationAttemptCheckpointLost(
                "Application attempt checkpoint changed before result persistence"
            )
        _ORIGINAL_RECORD_RESULT_EVIDENCE(db, checked, result)

    application_tasks._record_result_evidence = guarded_record_result_evidence
    _INSTALLED = True


__all__ = ["install_application_attempt_result_guard"]

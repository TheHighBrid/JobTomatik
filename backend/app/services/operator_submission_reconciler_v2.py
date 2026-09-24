from app.models.handoff import ACTIVE_HANDOFF_STATUSES
from app.services.operator_submission_reconciler import reconcile_operator_submissions as _reconcile


def reconcile_operator_submissions(db):
    """Compatibility entry point; active handoff statuses are owned by the model."""
    # The base reconciler handles awaiting/claimed sessions. ready_to_resume/resuming
    # are already owned by the resume worker and must not be raced by this watcher.
    return _reconcile(db)


__all__ = ["reconcile_operator_submissions", "ACTIVE_HANDOFF_STATUSES"]

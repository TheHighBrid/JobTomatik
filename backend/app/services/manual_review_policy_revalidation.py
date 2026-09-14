from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ApplicationEvent,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.services.answer_policy import load_runtime_policies
from app.services.application_state import (
    normalize_state,
    resolve_manual_review_task,
    transition_application_state,
)
from app.services.control_policy import resolve_control_policy
from app.services.control_primitives import (
    OptionRecord,
    match_answer_candidates_to_options,
)

POLICY_REVIEW_REASONS = {
    ManualReviewReason.ambiguous_question.value,
    ManualReviewReason.legal_answer_missing.value,
    ManualReviewReason.sensitive_answer_missing.value,
    ManualReviewReason.unsupported_control.value,
}

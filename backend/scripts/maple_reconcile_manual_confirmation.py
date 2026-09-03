from __future__ import annotations

import json
from datetime import datetime

from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.platform_submission_evidence import (
    build_platform_evidence_review_preflight,
    review_platform_submission_evidence,
)

APPLICATION_ID = 247
EXPECTED_EMPLOYER = "Maple"
EXPECTED_ROLE = "Client Success Associate (Bilingual, French/English)"
EXPECTED_APPLICATION_URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/apply"
CONFIRMATION_URL = "https://jobs.lever.co/getmaple/e8df92c9-23ed-4688-9b2c-4e5db504d24b/thanks"
CONFIRMATION_TEXT = "Application submitted!"


def _json(value):
    print(json.dumps(value, indent=2, default=str))


def main() -> int:
    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == APPLICATION_ID).one_or_none()
        if application is None:
            raise RuntimeError("STOP_MAPLE_APPLICATION_NOT_FOUND")
        user = db.query(User).filter(User.id == application.user_id).one_or_none()
        job = db.query(Job).filter(Job.id == application.job_id).one_or_none()
        if user is None or job is None:
            raise RuntimeError("STOP_MAPLE_OWNER_OR_JOB_MISSING")

        if str(job.company or "").strip() != EXPECTED_EMPLOYER:
            raise RuntimeError("STOP_MAPLE_EMPLOYER_CHANGED")
        if str(job.title or "").strip() != EXPECTED_ROLE:
            raise RuntimeError("STOP_MAPLE_ROLE_CHANGED")
        if str(job.url or "").strip() != EXPECTED_APPLICATION_URL:
            raise RuntimeError("STOP_MAPLE_APPLICATION_URL_CHANGED")

        approval = (
            db.query(SubmissionApproval)
            .filter(
                SubmissionApproval.application_id == application.id,
                SubmissionApproval.user_id == application.user_id,
                SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
            )
            .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
            .first()
        )
        if approval is None:
            raise RuntimeError("STOP_CONSUMED_MAPLE_APPROVAL_MISSING")
        approval_metadata = dict(approval.approval_metadata or {})
        if str(approval.platform or "").strip().lower() != "lever":
            raise RuntimeError("STOP_MAPLE_APPROVAL_NOT_LEVER")
        if str(approval.application_url or "").strip() != EXPECTED_APPLICATION_URL:
            raise RuntimeError("STOP_MAPLE_APPROVAL_URL_CHANGED")
        if approval_metadata.get("automated_submission_authorized") is not False:
            raise RuntimeError("STOP_MAPLE_APPROVAL_AUTHORITY_DRIFT")
        if approval_metadata.get("queue_submission_authorized") is not False:
            raise RuntimeError("STOP_MAPLE_QUEUE_AUTHORITY_DRIFT")
        if approval_metadata.get("operator_submit_action_started") is not True:
            raise RuntimeError("STOP_MAPLE_FINAL_ACTION_AUDIT_MISSING")

        target_identity = dict(approval_metadata.get("target_identity") or {})
        required_identity = (
            "site",
            "posting_id",
            "region",
            "canonical_application_url",
            "posting_metadata_hash",
            "identity_hash",
        )
        missing_identity = [key for key in required_identity if not str(target_identity.get(key) or "").strip()]
        if missing_identity:
            raise RuntimeError("STOP_MAPLE_TARGET_IDENTITY_INCOMPLETE:" + ",".join(missing_identity))

        existing = (
            db.query(SubmissionEvidence)
            .filter(
                SubmissionEvidence.application_id == application.id,
                SubmissionEvidence.evidence_type == "confirmation_page",
                SubmissionEvidence.final_url == CONFIRMATION_URL,
                SubmissionEvidence.confirmation_text == CONFIRMATION_TEXT,
            )
            .order_by(SubmissionEvidence.id.desc())
            .first()
        )

        if existing is None:
            evidence = SubmissionEvidence(
                application_id=application.id,
                evidence_type="confirmation_page",
                is_sufficient=True,
                final_url=CONFIRMATION_URL,
                confirmation_text=CONFIRMATION_TEXT,
                selector="body",
                payload_hash=approval.combined_payload_hash,
                evidence_metadata={
                    "platform": "lever",
                    "adapter": "lever",
                    "adapter_version": approval_metadata.get("adapter_version"),
                    "combined_payload_hash": approval.combined_payload_hash,
                    "approval_reference": approval.reference,
                    "site": target_identity.get("site"),
                    "posting_id": target_identity.get("posting_id"),
                    "region": target_identity.get("region"),
                    "canonical_application_url": target_identity.get("canonical_application_url"),
                    "posting_metadata_hash": target_identity.get("posting_metadata_hash"),
                    "target_identity_hash": target_identity.get("identity_hash"),
                    "confirmation_source": "authenticated_owner_manual_browser",
                    "controlled_browser_used_for_successful_confirmation": False,
                    "external_submit_click_performed_by_jobtomatik": False,
                    "confirmation_observed_by_owner": True,
                },
            )
            db.add(evidence)
            db.flush()
        else:
            evidence = existing

        preflight = build_platform_evidence_review_preflight(db, application, job, evidence)
        _json({
            "status": "MAPLE_CONFIRMATION_EVIDENCE_PREFLIGHT",
            "application_id": application.id,
            "application_status_before": str(getattr(application.status, "value", application.status)),
            "automation_state_before": application.automation_state,
            "evidence_id": evidence.id,
            "approval_reference": approval.reference,
            "ready_for_acceptance": preflight.get("ready_for_acceptance"),
            "blockers": preflight.get("blockers") or [],
            "final_url": evidence.final_url,
            "confirmation_text": evidence.confirmation_text,
        })
        if not preflight.get("ready_for_acceptance"):
            db.rollback()
            raise RuntimeError("STOP_MAPLE_EVIDENCE_REVIEW_BLOCKED:" + ",".join(preflight.get("blockers") or []))

        review = review_platform_submission_evidence(
            db,
            application,
            user,
            job,
            evidence,
            decision="accepted",
            confirm_employer=EXPECTED_EMPLOYER,
            confirm_role=EXPECTED_ROLE,
            confirm_evidence_type="confirmation_page",
            confirm_evidence_matches_application=True,
            review_acknowledgement="REVIEWED",
            notes=(
                "Owner independently completed the exact Maple Lever application in a normal "
                "browser after the controlled CDP attempt failed employer verification. The "
                "employer confirmation page displayed 'Application submitted!' at the exact "
                "posting /thanks URL. No additional JobTomatik submit action was performed."
            ),
        )

        # The canonical evidence review promotes status/state but historically does not
        # populate applied_at. Preserve the first confirmed submission time if missing.
        if application.applied_at is None:
            application.applied_at = evidence.captured_at or datetime.utcnow()

        db.commit()
        db.refresh(application)
        db.refresh(review)

        _json({
            "status": "MAPLE_MANUAL_CONFIRMATION_RECONCILED",
            "application_id": application.id,
            "application_status": str(getattr(application.status, "value", application.status)),
            "automation_state": application.automation_state,
            "applied_at": application.applied_at,
            "evidence_id": evidence.id,
            "evidence_type": evidence.evidence_type,
            "review_reference": review.reference,
            "review_decision": review.decision,
            "approval_reference": approval.reference,
            "external_submit_click_performed_by_jobtomatik": False,
            "successful_confirmation_source": "authenticated_owner_manual_browser",
            "final_url": CONFIRMATION_URL,
            "confirmation_text": CONFIRMATION_TEXT,
        })

        if application.status != ApplicationStatus.applied:
            raise RuntimeError("STOP_MAPLE_STATUS_NOT_APPLIED_AFTER_REVIEW")
        if application.automation_state != ApplicationAutomationState.confirmed.value:
            raise RuntimeError("STOP_MAPLE_STATE_NOT_CONFIRMED_AFTER_REVIEW")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

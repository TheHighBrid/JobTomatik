"""
Export endpoints: download application data as CSV or JSON.
"""
import csv
import io
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.application import Application
from app.models.user import User


router = APIRouter(prefix="/export", tags=["export"])


def _csv_safe(value) -> str:
    """Prevent external text from becoming a spreadsheet formula."""
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if text.startswith(("\t", "\r")) or stripped.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.get("/applications/csv")
def export_applications_csv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apps = (
        db.query(Application)
        .options(joinedload(Application.job))
        .filter(Application.user_id == current_user.id)
        .order_by(Application.created_at.desc())
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Job Title", "Company", "Location", "Source",
        "Status", "Salary Min", "Salary Max", "Applied At",
        "Interview At", "Offer At", "Notes", "URL"
    ])
    for application in apps:
        job = application.job
        writer.writerow([
            application.id,
            _csv_safe(job.title if job else ""),
            _csv_safe(job.company if job else ""),
            _csv_safe(job.location if job else ""),
            _csv_safe(job.source.value if job and job.source else ""),
            _csv_safe(application.status.value),
            job.salary_min if job else "",
            job.salary_max if job else "",
            application.applied_at.isoformat() if application.applied_at else "",
            application.interview_at.isoformat() if application.interview_at else "",
            application.offer_received_at.isoformat() if application.offer_received_at else "",
            _csv_safe(application.notes or ""),
            _csv_safe(job.url if job else ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jobtomatik-applications.csv"},
    )


@router.get("/applications/json")
def export_applications_json(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    apps = (
        db.query(Application)
        .options(joinedload(Application.job))
        .filter(Application.user_id == current_user.id)
        .order_by(Application.created_at.desc())
        .all()
    )

    data = []
    for application in apps:
        job = application.job
        data.append({
            "id": application.id,
            "status": application.status.value,
            "applied_at": application.applied_at.isoformat() if application.applied_at else None,
            "interview_at": application.interview_at.isoformat() if application.interview_at else None,
            "salary_offered": application.salary_offered,
            "notes": application.notes,
            "job": {
                "title": job.title if job else None,
                "company": job.company if job else None,
                "location": job.location if job else None,
                "url": job.url if job else None,
                "salary_min": job.salary_min if job else None,
                "salary_max": job.salary_max if job else None,
                "source": job.source.value if job and job.source else None,
                "skills": job.skills if job else [],
            },
        })

    output = json.dumps({"applications": data, "total": len(data)}, indent=2)
    return StreamingResponse(
        iter([output]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=jobtomatik-applications.json"},
    )

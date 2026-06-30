"""
Export endpoints: download application data as CSV or JSON.
"""
import csv
import io
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.models.application import Application

router = APIRouter(prefix="/export", tags=["export"])


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
    for a in apps:
        j = a.job
        writer.writerow([
            a.id,
            j.title if j else "",
            j.company if j else "",
            j.location if j else "",
            j.source.value if j and j.source else "",
            a.status.value,
            j.salary_min if j else "",
            j.salary_max if j else "",
            a.applied_at.isoformat() if a.applied_at else "",
            a.interview_at.isoformat() if a.interview_at else "",
            a.offer_received_at.isoformat() if a.offer_received_at else "",
            a.notes or "",
            j.url if j else "",
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
    for a in apps:
        j = a.job
        data.append({
            "id": a.id,
            "status": a.status.value,
            "applied_at": a.applied_at.isoformat() if a.applied_at else None,
            "interview_at": a.interview_at.isoformat() if a.interview_at else None,
            "salary_offered": a.salary_offered,
            "notes": a.notes,
            "job": {
                "title": j.title if j else None,
                "company": j.company if j else None,
                "location": j.location if j else None,
                "url": j.url if j else None,
                "salary_min": j.salary_min if j else None,
                "salary_max": j.salary_max if j else None,
                "source": j.source.value if j and j.source else None,
                "skills": j.skills if j else [],
            },
        })

    output = json.dumps({"applications": data, "total": len(data)}, indent=2)
    return StreamingResponse(
        iter([output]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=jobtomatik-applications.json"},
    )

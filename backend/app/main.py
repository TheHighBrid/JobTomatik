import os

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect as sa_inspect, text

from app.api import (
    adapter_health,
    answer_policies,
    applications,
    auth,
    controller,
    export,
    greenhouse_pilot_ledger,
    handoffs,
    jobs,
    notifications,
    profile,
    settings as settings_api,
    submission_evidence_reviews,
    supervised_pilot_roster,
    supervised_submissions,
)
from app.config import get_settings
from app.database import Base, engine
from app.services.ats_manifest import ats_certification_manifest
from app.services.control_engine import certification_manifest
from app.services.handoff_integration import install_handoff_task_integration
from app.services.operations_policy import operations_readiness_manifest
from app.services.supervised_submission_integration import (
    install_supervised_submission_task_gate,
)

settings = get_settings()
install_handoff_task_integration()
install_supervised_submission_task_gate()


def _safe_migrate(eng):
    """Add backward-compatible columns for local beta databases.

    New tables are created by ``Base.metadata.create_all``. These additive column
    migrations keep existing SQLite/PostgreSQL beta databases usable until a
    formal Alembic revision chain is introduced.
    """
    with eng.connect() as conn:
        try:
            user_cols = {c["name"] for c in sa_inspect(eng).get_columns("users")}
            if "automation_settings" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN automation_settings JSON"))
                conn.commit()
        except Exception:
            conn.rollback()

        try:
            app_cols = {c["name"] for c in sa_inspect(eng).get_columns("applications")}
            additions = {
                "automation_state": "VARCHAR(50) DEFAULT 'preparing' NOT NULL",
                "submission_idempotency_key": "VARCHAR(255)",
                "submission_attempt_count": "INTEGER DEFAULT 0 NOT NULL",
                "last_submission_attempt_at": "TIMESTAMP",
            }
            for column_name, definition in additions.items():
                if column_name not in app_cols:
                    conn.execute(text(f"ALTER TABLE applications ADD COLUMN {column_name} {definition}"))
                    conn.commit()
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_applications_submission_idempotency_key "
                "ON applications (submission_idempotency_key)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_applications_automation_state "
                "ON applications (automation_state)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _safe_migrate(engine)
    os.makedirs(settings.upload_dir, exist_ok=True)
    yield


app = FastAPI(
    title="JobTomatik API",
    description="Automated job application platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(auth.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(controller.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(supervised_submissions.router, prefix="/api")
app.include_router(supervised_pilot_roster.router, prefix="/api")
app.include_router(submission_evidence_reviews.router, prefix="/api")
app.include_router(greenhouse_pilot_ledger.router, prefix="/api")
app.include_router(adapter_health.router, prefix="/api")
app.include_router(handoffs.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(answer_policies.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")


@app.get("/health")
@app.get("/api/system/health")
async def health():
    return {"status": "ok", "service": "JobTomatik API"}


@app.get("/api/system/control-certification")
async def control_certification():
    return certification_manifest()


@app.get("/api/system/ats-certification")
async def ats_certification():
    return ats_certification_manifest()


@app.get("/api/system/operations-readiness")
async def operations_readiness():
    readiness = operations_readiness_manifest()
    ats = ats_certification_manifest()
    maturities = {
        item["name"]: item.get("maturity")
        for item in ats.get("adapters", [])
    }
    readiness["adapter_maturities"] = maturities
    readiness["autonomous_adapters"] = list(ats.get("autonomous_adapters", []))
    readiness["invariants"]["canonical_adapter_maturity_required"] = True
    readiness["invariants"]["no_autonomous_adapter_currently_enabled"] = not bool(
        readiness["autonomous_adapters"]
    )
    return readiness

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect as sa_inspect, text

from app.api import (
    adapter_health,
    agent_execution,
    answer_policies,
    applications,
    auth,
    autonomy_control,
    certification,
    controller,
    evaluations,
    export,
    greenhouse_pilot_ledger,
    handoffs,
    intelligence,
    jobs,
    lever_pilot_ledger,
    materials,
    notifications,
    operations,
    pilot_ledger,
    post_application,
    profile,
    recovery,
    scheduler,
    shadow_runs,
    settings as settings_api,
    submission_evidence_reviews,
    supervised_pilot_roster,
    supervised_submissions,
)
from app.config import get_settings
from app.database import Base, engine
from app.services.application_integrity import install_closed_application_task_gate
from app.services.application_target_handoff import (
    install_application_target_handoff_task_persistence,
)
from app.services.application_target_task_integration import (
    install_application_target_task_integration,
)
from app.services.ats_manifest import ats_certification_manifest
from app.services.autonomy_certification import build_autonomy_certification_manifest
from app.services.control_engine import certification_manifest
from app.services.followup_schema import ensure_followup_schema
from app.services.handoff_integration import install_handoff_task_integration
from app.services.material_task_integration import install_verified_material_task_integration
from app.services.operator_assisted_live_pilot_hardening import (
    install_operator_assisted_live_pilot_hardening,
)
from app.services.operations_policy import operations_readiness_manifest
from app.services.runtime_identity import runtime_identity_manifest
from app.services.supervised_submission_integration import (
    install_supervised_submission_task_gate,
)

logger = logging.getLogger(__name__)
settings = get_settings()
install_handoff_task_integration()
install_operator_assisted_live_pilot_hardening()
install_application_target_handoff_task_persistence()
install_application_target_task_integration()
install_verified_material_task_integration()
install_supervised_submission_task_gate()
# Keep this outermost so closed applications stop before approval consumption.
install_closed_application_task_gate()


def _safe_migrate(eng):
    """Add backward-compatible columns and enum values for existing databases.

    New tables are created by ``Base.metadata.create_all``. These additive migrations
    keep older SQLite/PostgreSQL installations usable alongside the formal Alembic
    revision chain. A failed migration is fatal because continuing with a partially
    upgraded schema produces harder-to-diagnose runtime errors.
    """
    failures = []

    if eng.dialect.name == "postgresql":
        try:
            with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as enum_conn:
                enum_exists = enum_conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jobsource')")
                ).scalar()
                if enum_exists:
                    for enum_value in ("greenhouse", "lever", "ashby"):
                        enum_conn.execute(
                            text(f"ALTER TYPE jobsource ADD VALUE IF NOT EXISTS '{enum_value}'")
                        )
        except Exception as exc:
            logger.exception("Failed additive migration for jobs.source enum")
            failures.append(("jobs.source_enum", exc))

    with eng.connect() as conn:
        try:
            user_cols = {c["name"] for c in sa_inspect(eng).get_columns("users")}
            if "automation_settings" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN automation_settings JSON"))
                conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.exception("Failed additive migration for users.automation_settings")
            failures.append(("users.automation_settings", exc))

        try:
            policy_cols = {
                c["name"] for c in sa_inspect(eng).get_columns("applicant_answer_policies")
            }
            policy_additions = {
                "encrypted_fallbacks": "TEXT",
                "provenance": "VARCHAR(40) DEFAULT 'user_provided' NOT NULL",
                "confidence": "FLOAT DEFAULT 1.0 NOT NULL",
                "consent_metadata": "JSON",
                "source_metadata": "JSON",
                "expires_at": "TIMESTAMP",
            }
            for column_name, definition in policy_additions.items():
                if column_name not in policy_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE applicant_answer_policies "
                            f"ADD COLUMN {column_name} {definition}"
                        )
                    )
                    conn.commit()
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_answer_policy_provenance "
                    "ON applicant_answer_policies (provenance)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_answer_policy_expires_at "
                    "ON applicant_answer_policies (expires_at)"
                )
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.exception("Failed additive migration for applicant_answer_policies")
            failures.append(("applicant_answer_policies", exc))

        try:
            app_cols = {c["name"] for c in sa_inspect(eng).get_columns("applications")}
            additions = {
                "automation_state": "VARCHAR(50) DEFAULT 'preparing' NOT NULL",
                "source_listing_url": "VARCHAR(1000)",
                "application_target_url": "VARCHAR(1000)",
                "application_target_status": "VARCHAR(50) DEFAULT 'unresolved' NOT NULL",
                "application_target_resolved_at": "TIMESTAMP",
                "application_target_metadata": "JSON",
                "submission_idempotency_key": "VARCHAR(255)",
                "submission_attempt_count": "INTEGER DEFAULT 0 NOT NULL",
                "last_submission_attempt_at": "TIMESTAMP",
            }
            for column_name, definition in additions.items():
                if column_name not in app_cols:
                    conn.execute(
                        text(
                            f"ALTER TABLE applications ADD COLUMN {column_name} {definition}"
                        )
                    )
                    conn.commit()
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_applications_submission_idempotency_key "
                    "ON applications (submission_idempotency_key)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_applications_automation_state "
                    "ON applications (automation_state)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_applications_application_target_status "
                    "ON applications (application_target_status)"
                )
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            logger.exception("Failed additive migration for applications")
            failures.append(("applications", exc))

    try:
        ensure_followup_schema(eng)
    except Exception as exc:
        logger.exception("Failed additive migration for supervised follow-ups")
        failures.append(("followups.supervised_delivery", exc))

    if failures:
        failed_targets = ", ".join(target for target, _ in failures)
        raise RuntimeError(f"Database compatibility migration failed: {failed_targets}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _safe_migrate(engine)
    os.makedirs(settings.upload_dir, exist_ok=True)
    logger.info(
        "JobTomatik startup complete environment=%s api_docs=%s",
        settings.app_environment,
        settings.enable_api_docs,
    )
    yield


api_docs_enabled = settings.enable_api_docs
app = FastAPI(
    title="JobTomatik API",
    description=(
        "AI-powered job-search and application automation platform progressing "
        "toward evidence-backed autonomous real submission"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if api_docs_enabled else None,
    redoc_url="/redoc" if api_docs_enabled else None,
    openapi_url="/openapi.json" if api_docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(controller.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(supervised_submissions.router, prefix="/api")
app.include_router(supervised_pilot_roster.router, prefix="/api")
app.include_router(submission_evidence_reviews.router, prefix="/api")
app.include_router(pilot_ledger.router, prefix="/api")
app.include_router(greenhouse_pilot_ledger.router, prefix="/api")
app.include_router(lever_pilot_ledger.router, prefix="/api")
app.include_router(adapter_health.router, prefix="/api")
app.include_router(handoffs.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(answer_policies.router, prefix="/api")
app.include_router(materials.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(intelligence.router, prefix="/api")
app.include_router(agent_execution.router, prefix="/api")
app.include_router(evaluations.router, prefix="/api")
app.include_router(operations.router, prefix="/api")
app.include_router(scheduler.router, prefix="/api")
app.include_router(autonomy_control.router, prefix="/api")
app.include_router(post_application.router, prefix="/api")
app.include_router(certification.router, prefix="/api")
app.include_router(recovery.router, prefix="/api")
app.include_router(shadow_runs.router, prefix="/api")


@app.get("/health")
@app.get("/api/system/health")
async def health():
    return {"status": "ok", "service": "JobTomatik API", "version": "1.0.0"}


@app.get("/api/system/ready")
def readiness_probe():
    """Confirm the API process can execute a database query."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ready", "service": "JobTomatik API", "version": "1.0.0"}


@app.get("/api/system/runtime-identity")
def runtime_identity():
    """Read-only exact-build identity. This endpoint grants no execution authority."""
    return runtime_identity_manifest()


@app.get("/api/system/control-certification")
async def control_certification():
    return certification_manifest()


@app.get("/api/system/ats-certification")
async def ats_certification():
    return ats_certification_manifest()


@app.get("/api/system/autonomy-certification")
async def autonomy_certification():
    return build_autonomy_certification_manifest()


@app.get("/api/system/operations-readiness")
async def operations_readiness():
    readiness = operations_readiness_manifest()
    ats = ats_certification_manifest()
    maturities = {
        item["name"]: item.get("maturity")
        for item in ats.get("adapters", [])
    }
    readiness["product_goal"] = "fully_autonomous_evidence_backed_real_submission"
    readiness["adapter_maturities"] = maturities
    readiness["autonomous_adapters"] = list(ats.get("autonomous_adapters", []))
    readiness["autonomous_adapter_count"] = len(readiness["autonomous_adapters"])
    readiness["invariants"]["canonical_adapter_maturity_required"] = True
    readiness["invariants"]["no_autonomous_adapter_currently_enabled"] = not bool(
        readiness["autonomous_adapters"]
    )
    readiness["invariants"]["recruiter_followup_requires_independent_approval"] = True
    readiness["recruiter_followup_send_enabled"] = bool(settings.allow_real_followup_send)
    readiness["runtime_identity"] = runtime_identity_manifest()
    return readiness

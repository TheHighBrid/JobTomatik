import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.database import engine, Base
from app.api import auth, jobs, applications, profile, notifications, export, settings as settings_api
from app.config import get_settings
from sqlalchemy import text, inspect as sa_inspect

settings = get_settings()


def _safe_migrate(eng):
    with eng.connect() as conn:
        try:
            cols = {c['name'] for c in sa_inspect(eng).get_columns('users')}
            if 'automation_settings' not in cols:
                conn.execute(text('ALTER TABLE users ADD COLUMN automation_settings JSON'))
                conn.commit()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (use Alembic in production)
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

# Mount static files for resume downloads
os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

# Register routers
app.include_router(auth.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "JobTomatik API"}

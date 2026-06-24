# JobTomatik

**Automated end-to-end job application platform.**

Targeted Automated Job Look-up, Keyword Tagging, Job Selection, Form Filling, Personalized Cover Letter Generating, Resume Attaching, Application Submitting, Application Status Monitoring, Application Follow-up, User Notifications.

---

## Features

| Feature | Implementation |
|---|---|
| **Job Lookup** | Scrapes LinkedIn, Indeed, Glassdoor — keyword, location, salary, job-type filters |
| **Keyword Tagging** | Rule-based NLP extracts skills, seniority, and industry from job descriptions |
| **Job Selection** | Swipe-style queue UI (drag or button) — approve → apply, skip → archive |
| **Form Filling** | Playwright automation fills standard application fields from your profile |
| **Cover Letter Generator** | Claude API writes personalized letters per job; falls back to template |
| **Resume Attaching** | PDF upload stored server-side; attached during Playwright form submission |
| **Application Submitting** | Background Celery task drives the browser; dry-run mode available |
| **Status Monitoring** | Kanban-style tracker: Pending → Applied → Interviewing → Offer / Rejected |
| **Follow-up Emails** | Schedule emails per-application; Celery beat sends them automatically |
| **Notifications** | In-app bell + email alerts for status changes, new matches, interview requests |

---

## Stack

```
Backend   FastAPI · SQLAlchemy · PostgreSQL · Celery · Redis · Playwright · Anthropic SDK
Frontend  React 18 · Tailwind CSS · React Query · Framer Motion · Zustand · Recharts
Infra     Docker Compose (db, redis, backend, celery_worker, celery_beat, frontend)
```

---

## Quick Start

```bash
# 1. Copy and fill environment variables
cp .env.example .env
# Required: set ANTHROPIC_API_KEY (for cover letters)
# Optional: SENDGRID_API_KEY (emails), RAPIDAPI_KEY

# 2. Launch everything
docker compose up --build

# Frontend → http://localhost:3000
# Backend API → http://localhost:8000
# API docs → http://localhost:8000/docs
```

### Without Docker (local dev)

```bash
# Backend
cd backend
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --reload

# Celery worker (separate terminal)
celery -A app.celery_app worker --loglevel=info -Q default,scraping,applications,followup

# Frontend
cd frontend
npm install
npm run dev
```

Ensure PostgreSQL is running at `localhost:5432` and Redis at `localhost:6379`.

---

## API Reference

Full interactive docs at **http://localhost:8000/docs** (Swagger UI).

| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Get JWT token |
| GET | `/api/profile` | Get user profile |
| PATCH | `/api/profile` | Update profile / preferences |
| POST | `/api/profile/resume` | Upload PDF resume |
| POST | `/api/jobs/search` | Trigger background job search |
| GET | `/api/jobs/queue` | Get jobs awaiting approval |
| POST | `/api/jobs/{id}/approve` | Approve a job |
| POST | `/api/jobs/{id}/reject` | Reject / skip a job |
| POST | `/api/applications` | Create application (triggers cover letter gen) |
| GET | `/api/applications` | List applications (filterable by status) |
| GET | `/api/applications/stats` | Pipeline stats |
| PATCH | `/api/applications/{id}` | Update status / notes |
| POST | `/api/applications/{id}/generate-cover-letter` | (Re)generate cover letter |
| POST | `/api/applications/{id}/submit` | Submit via Playwright |
| POST | `/api/applications/{id}/followups` | Schedule follow-up email |
| GET | `/api/notifications` | List notifications |
| POST | `/api/notifications/mark-all-read` | Mark all read |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  React Frontend (port 3000)                      │
│  Dashboard · Queue · Applications · Profile      │
└────────────────────┬─────────────────────────────┘
                     │ REST / JSON
┌────────────────────▼─────────────────────────────┐
│  FastAPI Backend (port 8000)                     │
│  Auth · Jobs · Applications · Profile · Notifs   │
└──────┬──────────────────┬────────────────────────┘
       │ SQLAlchemy        │ Celery tasks
┌──────▼──────┐   ┌───────▼────────────────────────┐
│ PostgreSQL  │   │ Redis + Celery Workers          │
│ (all data)  │   │ scraping · applications · email │
└─────────────┘   └────────────────────────────────┘
                           │ Playwright
                  ┌────────▼──────────┐
                  │ Job Board Browsers│
                  │ (Indeed/LinkedIn) │
                  └───────────────────┘
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `SECRET_KEY` | Yes | JWT signing key (use a long random string) |
| `ANTHROPIC_API_KEY` | Recommended | Claude AI for cover letters |
| `SENDGRID_API_KEY` | Optional | Email delivery (logs to console if unset) |
| `FROM_EMAIL` | Optional | Sender address for emails |
| `RAPIDAPI_KEY` | Optional | Enhanced job board API access |

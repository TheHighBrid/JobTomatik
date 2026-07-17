# JobTomatik

**Automated job-search assistant with a safety-first approval workflow.**

JobTomatik helps with targeted job lookup, keyword tagging, queue review, cover-letter generation, resume attachment, application tracking, follow-ups, and notifications.

The project is intentionally conservative: real application submission is blocked unless manually enabled. The recommended v1 flow is **hunt → queue → review → dry-run → manual approval**.

---

## Current beta status

| Area | Status |
|---|---|
| Backend health/auth/profile | Working locally |
| Job search queue | Working through FastAPI + Redis + Celery |
| Cover letters | Free local banking/fraud template by default |
| Browser automation | Dry-run supported through Playwright |
| Manual handoffs | Resumable CAPTCHA, anti-bot, MFA, and login sessions with user notifications |
| Adapter health | User-scoped metrics plus deduplicated operational alerts |
| Real application submit | Blocked by default for safety |
| Recommended production mode | Human approval before any submission |

### Canonical ATS maturity

The runtime uses the roadmap maturity field below. Descriptive certification labels, green tests, and fixture coverage do not authorize submission by themselves.

| Adapter | Maturity | Current safe boundary |
|---|---|---|
| Greenhouse | `dry_run` | Live synthetic full-form exercise through pre-submit or manual challenge |
| Lever | `dry_run` | Live synthetic full-form exercise through pre-submit or manual challenge |
| Ashby | `dry_run` | Live synthetic full-form exercise through pre-submit or manual challenge |
| SmartRecruiters | `detect_only` | Public metadata and pre-form anti-bot handoff |
| Workday | `detect_only` | Public metadata and account/login handoff |
| Generic sites | `unsupported` | Manual review |

No adapter currently has `human_reviewed_submit` or `certified_autonomous` maturity. Real and unattended submission remain unavailable until explicit release-gate evidence is recorded.

---

## Features

| Feature | Implementation |
|---|---|
| **Job Lookup** | Best-effort public search for Job Bank Canada, LinkedIn, and Indeed. Failed scrapes return no jobs by default instead of fake postings. |
| **Keyword Tagging** | Free rule-based NLP tuned for banking, fraud, AML, KYC, compliance, risk, and client-service roles. |
| **Job Selection** | Queue workflow where jobs can be approved or rejected before application work begins. |
| **Form Filling** | Playwright automation fills recognized fields from the profile and resume. |
| **Cover Letter Generator** | Free local template by default. Anthropic is optional with `AI_PROVIDER=anthropic`. |
| **Resume Attaching** | PDF upload stored server-side and attached during Playwright form fill when possible. |
| **Application Submitting** | Dry-run mode available. Real submit is blocked unless explicitly enabled and supported by adapter maturity and policy gates. |
| **Manual Handoff** | Secure resumable sessions for CAPTCHA, anti-bot, MFA, and login boundaries. Secrets remain encrypted and are never placed in notifications. |
| **Status Monitoring** | Kanban-style tracker: Pending → Applied → Interviewing → Offer / Rejected. |
| **Adapter Health** | Per-platform attempt, failure, manual-review, uncertain, and confirmation metrics with operational alerts. |
| **Follow-up Emails** | Schedule emails per application. SendGrid is optional. |
| **Notifications** | In-app notifications for new matches, status changes, adapter-health alerts, and time-limited manual handoffs. |

---

## Stack

```text
Backend   FastAPI · SQLAlchemy · Celery · Redis · Playwright · optional Anthropic SDK
Frontend  React 18 · Tailwind CSS · React Query · Framer Motion · Zustand · Recharts
Infra     Docker Compose or local Termux/Ubuntu development
```

---

## Quick Start with Docker

```bash
cp .env.example .env
# Fill SECRET_KEY. Optional: SENDGRID_API_KEY and ANTHROPIC_API_KEY.
# Default cover letters are free with AI_PROVIDER=template.

docker compose up --build

# Frontend → http://localhost:3000
# Backend API → http://localhost:8000
# API docs → http://localhost:8000/docs
```

---

## Android / Termux local setup notes

For the Android Ubuntu/Termux setup used during beta testing, the backend was run on port `8010` and the Android app used:

```text
http://127.0.0.1:8010
```

Do **not** add `/api` to the app API URL.

Recommended local backend `.env`:

```env
DATABASE_URL=sqlite:///./jobtomatik.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-change-later
AI_PROVIDER=template
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
SENDGRID_API_KEY=
FROM_EMAIL=support@melato.ca
RAPIDAPI_KEY=
UPLOAD_DIR=uploads
DEV_MOCK_JOBS=false
ALLOW_REAL_APPLICATION_SUBMIT=false
```

Install and run locally:

```bash
cd backend
pip install -r requirements.txt
python -m playwright install chromium
redis-server --daemonize yes 2>/dev/null || true
uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level info
```

Run the worker in a second terminal:

```bash
cd backend
celery -A app.celery_app worker --loglevel=info -Q celery,scraping,applications,followup
```

---

## Safety model

Real application submission is blocked unless explicitly enabled:

```env
ALLOW_REAL_APPLICATION_SUBMIT=true
```

Keep it `false` until the relevant supervised release gates have passed. Dry-run results include `fields_filled`, `requires_manual_review`, an auditable action log, and retained handoff or confirmation evidence where available.

Unattended execution additionally fails closed unless all of these conditions are satisfied:

1. The adapter has canonical `certified_autonomous` maturity.
2. Global and per-platform switches are enabled.
3. The user has explicitly opted in for that platform.
4. Required answer policies are resolved.
5. Daily and weekly caps, per-employer caps, quiet hours, exclusions, and job constraints pass.
6. Duplicate prevention and confirmation-evidence rules pass.

CAPTCHAs, anti-bot challenges, MFA, login boundaries, assessments, identity checks, and ambiguous legal or sensitive questions always route to manual review.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL or SQLite connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `SECRET_KEY` | Yes | JWT signing key. Use a long random string outside local dev. |
| `AI_PROVIDER` | Optional | `template` by default. Set `anthropic` only if using paid Anthropic credits. |
| `ANTHROPIC_API_KEY` | Optional | Claude API key for optional AI cover letters |
| `ANTHROPIC_MODEL` | Optional | Defaults to `claude-sonnet-5` |
| `SENDGRID_API_KEY` | Optional | Email delivery. Emails are logged/mocked if unset. |
| `FROM_EMAIL` | Optional | Sender address for emails |
| `DEV_MOCK_JOBS` | Optional | Keep `false` for real use. Set `true` only for UI demos. |
| `ALLOW_REAL_APPLICATION_SUBMIT` | Optional | Keep `false` until the relevant adapter release gates pass. |
| `RAPIDAPI_KEY` | Optional | Reserved for future job-board integrations |

---

## API Reference

Full interactive docs at **/docs** on the backend server.

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
| POST | `/api/applications` | Create application and trigger cover letter generation |
| GET | `/api/applications` | List applications |
| GET | `/api/applications/stats` | Pipeline stats |
| PATCH | `/api/applications/{id}` | Update status / notes |
| POST | `/api/applications/{id}/generate-cover-letter` | Regenerate cover letter |
| POST | `/api/applications/{id}/submit?dry_run=true` | Dry-run browser form fill |
| POST | `/api/applications/{id}/submit?dry_run=false` | Real submit, blocked unless all gates permit it |
| POST | `/api/applications/{id}/followups` | Schedule follow-up email |
| GET | `/api/adapter-health` | Get user-scoped adapter health metrics and alerts |
| GET | `/api/handoffs` | List resumable manual handoff sessions |
| GET | `/api/handoffs/{public_id}` | Read one owned handoff and its event history |
| POST | `/api/handoffs/{public_id}/bootstrap` | Disclose the encrypted resume token once to its owner |
| POST | `/api/handoffs/{public_id}/claim` | Claim a handoff and receive a short-lived lease |
| POST | `/api/handoffs/{public_id}/recover` | Recover an interrupted eligible handoff lease |
| GET | `/api/notifications` | List notifications |
| POST | `/api/notifications/mark-all-read` | Mark all read |

---

## Collaboration handoff

To avoid AI assistants overwriting one another:

1. Keep real submit blocked by default.
2. Do not reintroduce fake software-engineering mock jobs as default results.
3. Keep cover letters free by default with `AI_PROVIDER=template`.
4. Use `DEV_MOCK_JOBS=true` only for UI/demo testing.
5. Prefer small focused commits over broad rewrites.

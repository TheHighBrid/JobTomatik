# JobTomatik v1.00

**A safety-first job-search, application-preparation, and supervised browser assistant.**

JobTomatik searches and scores roles, organizes a review queue, generates cover letters, attaches a résumé, fills supported application forms, pauses at human-verification boundaries, records submission evidence, and tracks follow-ups.

The v1 milestone includes the first end-to-end confirmed application through a retained Greenhouse handoff. JobTomatik remains deliberately conservative: real and unattended submission are disabled by default, and unsupported or ambiguous steps stop for human review.

## Download

The Android client is published on the repository’s **Releases** page:

- [Download the latest JobTomatik APK](https://github.com/TheHighBrid/JobTomatik/releases/latest)
- Technical version: `1.0.0`
- Release title: **JobTomatik v1.00**
- Android application ID: `ca.jobtomatik.app`
- Minimum Android SDK: 23
- Target Android SDK: 35

The APK is the user interface. The FastAPI backend, Redis, Celery worker, database, and Playwright browser runtime still run locally or on a trusted server.

> Check `BUILD-INFO.txt` in the release before upgrading. When permanent Android signing secrets are not configured, CI publishes a development-signed APK intended for personal/local installation. A differently signed future APK may require uninstalling the previous build first.

## What v1 includes

| Area | v1 state |
|---|---|
| Authentication, profile, résumé | Working |
| Job search and scoring | Working with best-effort public sources |
| Review queue | Working |
| Cover-letter generation | Local template by default; optional Anthropic provider |
| Answer Policy Vault | Working, encrypted at rest |
| Greenhouse form filling | Dry-run and supervised handoff verified |
| Retained browser handoff | CAPTCHA, anti-bot, login, and MFA interaction supported |
| Expired-code recovery | Replace-and-submit, request new code, back, reload, and restart controls |
| Submission confirmation | Explicit confirmation pages create evidence and close the handoff |
| Duplicate protection | Confirmed records hide further submission controls |
| Adapter health and notifications | Working |
| Follow-up scheduling | Working; SendGrid optional |
| Autonomous real submission | Disabled |

## Canonical ATS boundaries

Green tests do not authorize automatic submission. Runtime maturity controls the boundary.

| Adapter | Maturity | Safe v1 boundary |
|---|---|---|
| Greenhouse | `dry_run` | Form preparation, retained handoff, and confirmation evidence |
| Lever | `dry_run` | Form preparation through pre-submit or manual challenge |
| Ashby | `dry_run` | Form preparation through pre-submit or manual challenge |
| SmartRecruiters | `detect_only` | Metadata and manual handoff |
| Workday | `detect_only` | Account/login handoff |
| Generic sites | `unsupported` | Manual review |

No adapter is marked `certified_autonomous` in v1.

## Architecture

```text
Android / Browser UI
        │
        ▼
React + Capacitor client
        │  HTTP API
        ▼
FastAPI backend ─── SQLite/PostgreSQL
        │
        ├── Redis
        ├── Celery worker
        └── Playwright Chromium retained-browser sessions
```

## Fast Android / Termux start

The complete guide is in **[docs/SETUP_TUTORIAL.md](docs/SETUP_TUTORIAL.md)**. The essential layout is:

- Regular Termux runs the React development client when needed.
- Ubuntu PRoot runs Python, Redis, FastAPI, Celery, and Playwright.
- The installed APK connects to `http://127.0.0.1:8010`.
- Do not append `/api` to the URL entered in JobTomatik.

### Ubuntu backend terminal

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
redis-server --daemonize yes 2>/dev/null || true
redis-cli ping
uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level info
```

### Ubuntu Celery terminal

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
celery -A app.celery_app worker \
  --loglevel=info \
  --pool=solo \
  -Q applications,celery,scraping,followup
```

`--pool=solo` is recommended on Android/PRoot because a single retained Chromium controller is more reliable than multiple forked workers.

### Optional browser frontend

Run outside Ubuntu in regular Termux:

```bash
cd ~/JobTomatik/frontend
npm ci
VITE_API_URL=http://127.0.0.1:8010 npm run dev
```

Open `http://127.0.0.1:3000`.

## First-run workflow

1. Register or sign in.
2. Complete **Profile** and upload the current résumé PDF.
3. Review the **Answer Policy Vault**. Approve only truthful reusable answers.
4. Search for jobs and approve one exact posting.
5. Open its application record and review the generated cover letter.
6. Press **Dry Run (Preview)**.
7. Review every filled answer and uploaded file.
8. Complete any CAPTCHA, login, or verification code through **Open secure handoff**.
9. When the employer displays a clear confirmation page, press **I completed the challenge**.
10. JobTomatik records the evidence, closes the handoff, and marks the application submitted/confirmed.

Never repeat an application after the employer has displayed a received/thank-you confirmation.

## Safety defaults

Keep these values disabled unless a separately reviewed supervised release gate explicitly requires them:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
DEV_MOCK_JOBS=false
```

Dry runs may retain human-verification sessions automatically. The `ENABLE_RESUMABLE_HANDOFFS` switch extends that capability to explicitly approved non-dry runs; it does not bypass any challenge.

JobTomatik always stops for CAPTCHA, anti-bot challenges, MFA, login boundaries, assessments, identity checks, unsupported controls, and ambiguous legal or sensitive questions.

## Configuration

Copy the example file and use a strong secret:

```bash
cp .env.example backend/.env
```

Recommended Android/Termux values:

```env
DATABASE_URL=sqlite:///./jobtomatik.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-with-a-long-random-value
ANSWER_VAULT_KEY=
AI_PROVIDER=template
SENDGRID_API_KEY=
UPLOAD_DIR=uploads
DEV_MOCK_JOBS=false
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://localhost,http://localhost,capacitor://localhost
```

Keep `SECRET_KEY` and `ANSWER_VAULT_KEY` stable after encrypted answer policies are created.

## Docker quick start

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

The Docker composition is useful for the core application. Local-CDP retained-browser handoffs require the API and browser worker to share reachable browser-session affinity; the Android/Ubuntu single-node setup is the reference v1 configuration.

## Build the Android APK

```bash
cd frontend
npm ci
npm run build:apk:debug
```

Output:

```text
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

A release build requires a private keystore supplied outside source control:

```bash
export JOBTOMATIK_KEYSTORE_PATH=/secure/path/jobtomatik-release.jks
export JOBTOMATIK_KEYSTORE_PASSWORD='...'
export JOBTOMATIK_KEY_ALIAS='jobtomatik'
export JOBTOMATIK_KEY_PASSWORD='...'
npm run build:apk:release
```

No keystore path, key, or password is committed to this repository.

## Test and verify

### Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
pytest -q
python -m compileall -q app tests
```

### Frontend

```bash
cd frontend
npm ci
npm run build
```

### Android

```bash
cd frontend
npm run android:prepare
cd android
./gradlew --no-daemon lintDebug assembleDebug
```

GitHub Actions runs backend tests, frontend compilation, the retained-handoff certification matrix, Android lint, and APK assembly for release changes.

## Repository guide

```text
backend/                 FastAPI, Celery, Playwright, policies, evidence, tests
frontend/                React client and Capacitor Android project
docs/SETUP_TUTORIAL.md   Complete installation and operating tutorial
evidence/                Canonical pilot and certification records
.github/workflows/       CI, Android build, stabilization, and release automation
CHANGELOG.md              Version history
SECURITY.md               Secrets, local-data, and vulnerability guidance
```

## API reference

Interactive OpenAPI documentation is available at `/docs` on the running backend. Common routes include:

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create an account |
| POST | `/api/auth/login` | Receive an access token |
| GET/PATCH | `/api/profile` | Read or update the applicant profile |
| POST | `/api/profile/resume` | Upload the résumé |
| POST | `/api/jobs/search` | Queue a job search |
| GET | `/api/jobs/queue` | Review job candidates |
| POST | `/api/applications` | Create an application record |
| POST | `/api/applications/{id}/submit?dry_run=true` | Start a preview form-fill attempt |
| GET | `/api/handoffs/application/{id}/sessions` | List retained handoffs |
| POST | `/api/handoffs/{public_id}/complete` | Verify and resume a completed challenge |
| GET | `/api/applications/{id}/evidence` | Read submission evidence |
| GET | `/api/system/operations-readiness` | Inspect active safety gates |

## Release history

See **[CHANGELOG.md](CHANGELOG.md)**. The v1.00 release finalizes retained-browser recovery, explicit confirmation-page reconciliation, portable Android builds, secret-free signing configuration, and reproducible APK automation.

# JobTomatik v1.00

**An AI-powered job-search and application system built toward fully autonomous, evidence-backed real submission.**

JobTomatik searches and scores roles, organizes an application queue, prepares tailored materials, fills supported application forms, handles retained-browser sessions, records submission evidence, and tracks follow-ups.

## Product direction

The final product goal is a fully autonomous job-hunt agent that can:

- discover and rank suitable roles;
- prepare truthful, tailored application materials;
- resolve job-board listings into employer or ATS application targets;
- complete supported forms and upload the correct documents;
- make policy-bounded decisions using the applicant's approved profile and answer rules;
- submit real applications without routine human operation;
- verify employer confirmation before recording an application as submitted;
- recover from failures, prevent duplicates, and continue operating within configured limits.

JobTomatik v1 is the supervised foundation of that system, not its permanent ceiling. Current release controls let each adapter progress through detection, dry-run, reviewed submission, and autonomous certification as implementation evidence matures.

JobTomatik does not attempt to evade CAPTCHA, MFA, identity verification, or other third-party security controls. When a site explicitly requires a human action, the system may pause, request that action, and resume afterward.

## Download

The Android client is published on the repository's **Releases** page:

- [Download the latest JobTomatik APK](https://github.com/TheHighBrid/JobTomatik/releases/latest)
- Technical version: `1.0.0`
- Release title: **JobTomatik v1.00**
- Android application ID: `ca.jobtomatik.app`
- Minimum Android SDK: 23
- Target Android SDK: 35

The APK is the user interface. The FastAPI backend, Redis, Celery worker, database, and Playwright browser runtime run locally or on a trusted server.

> Check `BUILD-INFO.txt` in the release before upgrading. When permanent Android signing secrets are not configured, CI publishes a development-signed APK intended for personal or local installation. A differently signed future APK may require uninstalling the previous build first.

## Current v1 capabilities

| Area | Current state |
|---|---|
| Authentication, profile, résumé | Working |
| Job search and scoring | Working with best-effort public sources |
| Review and application queue | Working |
| Cover-letter generation | Local template by default; optional Anthropic provider |
| Answer Policy Vault | Working, encrypted at rest |
| Listing-to-employer target resolution | In active development |
| Greenhouse form filling | Dry-run and retained-handoff verified |
| Retained browser handoff | CAPTCHA, anti-bot, login, MFA, and navigation interaction supported |
| Expired-code recovery | Replace-and-submit, request new code, back, reload, and restart controls |
| Submission confirmation | Explicit confirmation evidence closes successful applications |
| Duplicate protection | Confirmed records hide further submission controls |
| Adapter health and notifications | Working |
| Follow-up scheduling | Working; SendGrid optional |
| Fully autonomous real submission | Product target, promoted adapter by adapter through release evidence |

## Adapter maturity and autonomy roadmap

Adapter maturity is an operational progression, not a permanent restriction:

```text
unsupported
→ detect_only
→ dry_run
→ human_reviewed_submit
→ certified_autonomous
```

The current v1 evidence boundary is:

| Adapter | Current maturity | Current operating boundary |
|---|---|---|
| Greenhouse | `dry_run` | Form preparation, retained handoff, and confirmation evidence |
| Lever | `dry_run` | Form preparation through pre-submit or manual challenge |
| Ashby | `dry_run` | Form preparation through pre-submit or manual challenge |
| SmartRecruiters | `detect_only` | Metadata detection and handoff |
| Workday | `detect_only` | Account and login handoff |
| Generic sites | `unsupported` | Target resolution or manual review |

Each adapter is intended to advance toward `certified_autonomous` after its real-world reliability, duplicate prevention, confirmation evidence, recovery behavior, and incident controls meet the repository's release criteria.

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

The application-target architecture keeps the original discovery listing separate from the real employer or ATS form:

```text
source listing
→ target resolution
→ employer application target
→ ATS adapter or bounded browser agent
→ confirmation evidence
```

## Fast Android / Termux start

The complete guide is in **[docs/SETUP_TUTORIAL.md](docs/SETUP_TUTORIAL.md)**.

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

`--pool=solo` is recommended on Android/PRoot because one retained Chromium controller is more reliable than multiple forked workers.

### Optional browser frontend

Run outside Ubuntu in regular Termux:

```bash
cd ~/JobTomatik/frontend
npm ci
VITE_API_URL=http://127.0.0.1:8010 npm run dev
```

Open `http://127.0.0.1:3000`.

## Current v1 workflow

1. Register or sign in.
2. Complete **Profile** and upload the current résumé PDF.
3. Review the **Answer Policy Vault** and approve truthful reusable answers.
4. Search for jobs and approve an exact posting.
5. Open its application record and review the generated material.
6. Press **Dry Run (Preview)**.
7. Review filled answers and uploaded files.
8. Complete any unavoidable third-party verification through **Open secure handoff**.
9. Allow JobTomatik to resume and verify the employer confirmation page.
10. JobTomatik records the evidence and updates the application state.

Do not repeat an application after the employer has displayed a received or thank-you confirmation.

## Development and rollout controls

The repository ships conservative development defaults while autonomous capabilities are being tested and promoted:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
DEV_MOCK_JOBS=false
```

These are configurable release gates, not a statement that the product must remain supervised. An autonomous release can enable the relevant controls after its adapters, policies, duplicate protection, recovery paths, and confirmation evidence satisfy the operator's chosen readiness criteria.

Dry runs may retain human-verification sessions automatically. `ENABLE_RESUMABLE_HANDOFFS` extends that capability to approved non-dry runs; it does not bypass a third-party challenge.

## Configuration

Copy the example file and use a strong secret:

```bash
cp .env.example backend/.env
```

Recommended Android/Termux development values:

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

Local-CDP retained-browser handoffs require the API and browser worker to share reachable browser-session affinity. The Android/Ubuntu single-node setup is the reference v1 configuration.

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

The Android CI toolchain uses Node.js 20, Temurin Java 21, Gradle 8.11.1, Android Gradle Plugin 8.7.2, Android API 35, and Build Tools 35.0.0.

## Repository guide

```text
backend/                 FastAPI, Celery, Playwright, policies, evidence, tests
frontend/                React client and Capacitor Android project
docs/SETUP_TUTORIAL.md   Complete installation and operating tutorial
evidence/                Pilot and certification records
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
| POST | `/api/applications/{id}/submit?dry_run=true` | Start a preview application attempt |
| GET | `/api/handoffs/application/{id}/sessions` | List retained handoffs |
| POST | `/api/handoffs/{public_id}/complete` | Verify and resume a completed handoff |
| GET | `/api/applications/{id}/evidence` | Read submission evidence |
| GET | `/api/system/operations-readiness` | Inspect current automation and release gates |

## Release history

See **[CHANGELOG.md](CHANGELOG.md)**. JobTomatik v1.00 establishes the supervised foundation, retained-browser recovery, confirmation evidence, portable Android builds, and the adapter-maturity system used to progress toward autonomous operation.

# JobTomatik v1.00: Complete Setup and Operating Tutorial

This guide starts from a clean Android device and ends with a working JobTomatik installation capable of searching jobs, preparing applications, resolving job-board listings, running previews, opening retained-browser handoffs, and recording employer confirmation evidence.

The reference v1 setup uses:

- **Regular Termux** for Git, Node.js, and the optional browser frontend;
- **Ubuntu PRoot inside Termux** for Python, Redis, FastAPI, Celery, and Playwright Chromium;
- **The JobTomatik Android APK** as the normal user interface;
- `http://127.0.0.1:8010` as the same-device backend URL.

The APK is not a standalone server. Redis, FastAPI, Celery, and Playwright must be running when JobTomatik performs searches, generates work, resolves targets, or fills an application.

---

## 1. Product direction and current release stage

JobTomatik's final product goal is fully autonomous job discovery, preparation, application, and evidence-backed real submission for certified application paths.

Version 1.00 is the supervised foundation of that system. Its development defaults keep unfinished capabilities behind release gates while adapters, recovery behavior, duplicate prevention, confirmation evidence, and operational controls are tested.

The current v1 workflow is:

```text
search → approve job → create application → review materials → Dry Run
→ resolve employer target → retained handoff when required
→ employer confirmation → submission evidence
```

The intended mature workflow is:

```text
continuous search → autonomous ranking → autonomous preparation
→ target resolution → certified ATS execution → real submission
→ confirmation evidence → tracking and follow-up
```

JobTomatik does not attempt to evade CAPTCHA, MFA, identity verification, or other third-party security controls. When a site explicitly requires a human action, the system may pause, preserve state, request the action, and resume afterward.

Never repeat the same application after an employer has displayed a clear application-received or thank-you confirmation.

---

## 2. Requirements

### Android device

Recommended:

- Android 9 or newer;
- at least 6 GB free storage for Ubuntu, Python packages, and Chromium;
- a modern 64-bit ARM device;
- a stable network connection while installing dependencies.

### Apps and accounts

You need:

- Termux with package support;
- GitHub access to `TheHighBrid/JobTomatik`;
- a current résumé PDF;
- permission to install an APK from your browser or file manager.

Optional:

- SendGrid account for automated follow-up email delivery;
- Anthropic API key for paid cover-letter generation. The local template provider works without one.

---

## 3. Install the Termux host tools

Open regular Termux and run:

```bash
pkg update -y
pkg upgrade -y
pkg install -y git nodejs-lts proot-distro nano curl
```

Check the tools:

```bash
git --version
node --version
npm --version
proot-distro list
```

Install Ubuntu:

```bash
proot-distro install ubuntu
```

Enter it once to confirm it works:

```bash
proot-distro login ubuntu
```

Then leave Ubuntu:

```bash
exit
```

### Know which shell you are in

Regular Termux usually uses a normal Android user prompt. Ubuntu PRoot usually looks similar to:

```text
root@localhost:~#
```

Paths are different:

| Environment | Repository path | Main purpose |
|---|---|---|
| Termux host | `/data/data/com.termux/files/home/JobTomatik` or `~/JobTomatik` | React/Vite client |
| Ubuntu PRoot | `/root/JobTomatik` | FastAPI, Redis, Celery, Playwright |

A Python virtual environment created in Ubuntu does not work in regular Termux. A Termux Node installation must not be used from `/root/JobTomatik`, because Android's linker cannot load native Node modules from the PRoot filesystem.

---

## 4. Clone the frontend copy in regular Termux

Outside Ubuntu:

```bash
cd ~
git clone https://github.com/TheHighBrid/JobTomatik.git
cd ~/JobTomatik
git checkout main
git pull --ff-only origin main
```

Install frontend dependencies:

```bash
cd ~/JobTomatik/frontend
npm ci --include=optional
```

Verify the frontend build:

```bash
npm run build
```

Run the optional browser frontend:

```bash
VITE_API_URL=http://127.0.0.1:8010 npm run dev -- --host 0.0.0.0
```

Open `http://127.0.0.1:3000`.

---

## 5. Clone the backend copy inside Ubuntu

Enter Ubuntu:

```bash
proot-distro login ubuntu
```

Install system packages:

```bash
apt update
apt install -y \
  git \
  curl \
  ca-certificates \
  python3 \
  python3-pip \
  python3-venv \
  redis-server \
  build-essential
```

Clone the repository:

```bash
cd /root
git clone https://github.com/TheHighBrid/JobTomatik.git
cd /root/JobTomatik
git checkout main
git pull --ff-only origin main
```

Create the Ubuntu Python environment:

```bash
cd /root/JobTomatik/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --index-url https://pypi.org/simple -r requirements.txt
```

Install Chromium and its Linux dependencies:

```bash
python -m playwright install --with-deps chromium
```

Verify Python belongs to Ubuntu:

```bash
which python
python --version
```

The path should begin with:

```text
/root/JobTomatik/backend/.venv/
```

---

## 6. Configure JobTomatik

Create the backend environment file:

```bash
cd /root/JobTomatik/backend
cp ../.env.example .env
```

Recommended development values:

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
APPLICATION_BROWSER_PROFILE_DIR=/root/JobTomatik/backend/browser_profiles/jobtomatik-operator
APPLICATION_BROWSER_HEADLESS=false
APPLICATION_TARGET_HUMAN_WAIT_SECONDS=180
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://localhost,http://localhost,capacitor://localhost
```

These values are conservative development and rollout defaults. They are release gates, not a permanent supervised-only product definition. A future autonomous release can enable the relevant controls after the operator accepts its adapter and operational readiness evidence.

Keep `SECRET_KEY` and `ANSWER_VAULT_KEY` stable after encrypted answer policies are created.

---

## 7. Start Redis, FastAPI, and Celery

### Redis and FastAPI terminal

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
redis-server --daemonize yes 2>/dev/null || true
redis-cli ping
uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level info
```

Expected Redis response:

```text
PONG
```

### Celery terminal

Start Celery from an XFCE terminal when a visible Playwright browser is required, and confirm `echo "$DISPLAY"` is not empty.

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

---

## 8. First application run

1. Open the Android app or browser frontend.
2. Register or sign in.
3. Complete the applicant profile.
4. Upload the current résumé PDF.
5. Review truthful reusable answers in the Answer Policy Vault.
6. Search for jobs and approve an exact posting.
7. Open the application record.
8. Generate or review the cover letter.
9. Press **Dry Run (Preview)** once.
10. Allow JobTomatik to resolve the source listing into the employer or ATS target.
11. Complete an unavoidable navigation, login, CAPTCHA, MFA, or verification action through the retained handoff when requested.
12. Let JobTomatik resume and inspect the employer confirmation evidence.

The source listing and employer target are stored separately. A LinkedIn or Job Bank discovery URL must not be treated as the application form itself.

---

## 9. Build the Android APK

JobTomatik's Android CI toolchain is standardized on:

- Node.js 20;
- Temurin Java 21;
- Gradle 8.11.1;
- Android Gradle Plugin 8.7.2;
- Android SDK API 35;
- Build Tools 35.0.0.

Build locally:

```bash
cd ~/JobTomatik/frontend
npm ci --include=optional
npm run android:prepare
cd android
./gradlew --no-daemon lintDebug assembleDebug
```

Output:

```text
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

If Gradle reports `Unsupported class file major version 69`, the environment is using Java 25. Set `JAVA_HOME` and `PATH` to JDK 21 before running Gradle.

---

## 10. Autonomy promotion model

The intended adapter progression is:

```text
unsupported
→ detect_only
→ dry_run
→ human_reviewed_submit
→ certified_autonomous
```

Promotion should be based on evidence, including:

- correct target resolution;
- truthful answer-policy execution;
- correct résumé and document selection;
- zero false-positive submitted records;
- duplicate and replay prevention;
- confirmation evidence;
- recovery after crashes and browser interruptions;
- application caps, quiet hours, circuit breakers, exclusions, and kill switches;
- incident-response and rollback testing.

The existence of these gates does not change the project goal. They are the machinery used to reach reliable autonomous operation.

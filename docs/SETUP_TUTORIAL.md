# JobTomatik v1.00: Complete Setup and Operating Tutorial

This guide starts from a clean Android device and ends with a working JobTomatik installation capable of searching jobs, preparing applications, running safe previews, opening retained-browser handoffs, and recording employer confirmation evidence.

The reference v1 setup uses:

- **Regular Termux** for Git, Node.js, and the optional browser frontend;
- **Ubuntu PRoot inside Termux** for Python, Redis, FastAPI, Celery, and Playwright Chromium;
- **The JobTomatik Android APK** as the normal user interface;
- `http://127.0.0.1:8010` as the same-device backend URL.

The APK is not a standalone server. Redis, FastAPI, Celery, and Playwright must be running when JobTomatik performs searches, generates work, or fills an application.

---

## 1. Safety boundary before installation

JobTomatik v1 is a supervised assistant, not a blind auto-apply bot.

Keep these values disabled:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
DEV_MOCK_JOBS=false
```

Normal v1 operation is:

```text
search → approve job → create application → review materials → Dry Run
→ manual handoff when required → explicit employer confirmation → evidence
```

Never run the same application again after an employer has displayed a clear “application received” or “thank you for applying” page.

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

Regular Termux usually looks similar to:

```text
 ~/
```

Ubuntu PRoot usually looks similar to:

```text
root@localhost:~#
```

Paths are different:

| Environment | Repository path | Main purpose |
|---|---|---|
| Termux host | `/data/data/com.termux/files/home/JobTomatik` or `~/JobTomatik` | React/Vite client |
| Ubuntu PRoot | `/root/JobTomatik` | FastAPI, Redis, Celery, Playwright |

A Python virtual environment created in Ubuntu does not work in regular Termux. A Termux Node installation should not be treated as an Ubuntu package.

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
npm ci
```

Verify the frontend build:

```bash
npm run build
```

Do not start the frontend yet. Finish the backend first.

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

## 6. Create the backend environment file

Still inside Ubuntu:

```bash
cd /root/JobTomatik/backend
cp ../.env.example .env
```

Generate a strong local secret:

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
```

Copy the generated value, then edit:

```bash
nano .env
```

Use this local baseline:

```env
DATABASE_URL=sqlite:///./jobtomatik.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=PASTE_THE_LONG_RANDOM_VALUE_HERE
ANSWER_VAULT_KEY=
ACCESS_TOKEN_EXPIRE_MINUTES=10080
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://localhost,http://localhost,capacitor://localhost

AI_PROVIDER=template
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5

SENDGRID_API_KEY=
FROM_EMAIL=noreply@jobtomatik.com

DEV_MOCK_JOBS=false
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false

UPLOAD_DIR=uploads
JOBTOMATIK_BROWSER_NODE_ID=local-node
HANDOFF_STORAGE_DIR=handoff_sessions
```

Save in nano with `Ctrl+O`, Enter, then leave with `Ctrl+X`.

### Important encryption note

After creating Answer Policy Vault records, keep `SECRET_KEY` and `ANSWER_VAULT_KEY` stable. Changing the encryption key can make previously encrypted values unreadable.

---

## 7. Initialize and test the backend

Activate the environment whenever a new Ubuntu terminal starts:

```bash
cd /root/JobTomatik/backend
source .venv/bin/activate
```

Compile the Python code:

```bash
python -m compileall -q app tests
```

Run tests when installing a new release:

```bash
pytest -q
```

Run database migrations:

```bash
alembic upgrade head
```

The API also performs additive compatibility checks for older local databases at startup.

---

## 8. Start Redis

Inside Ubuntu:

```bash
redis-server --daemonize yes 2>/dev/null || true
redis-cli ping
```

Required output:

```text
PONG
```

When Celery prints `Connection refused`, Redis is not running. Start Redis before restarting Celery.

---

## 9. Start the FastAPI backend

Use one Ubuntu terminal:

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
redis-server --daemonize yes 2>/dev/null || true
uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8010 \
  --log-level info
```

Expected output:

```text
Application startup complete.
Uvicorn running on http://127.0.0.1:8010
```

Test from another terminal:

```bash
curl http://127.0.0.1:8010/health
```

Expected shape:

```json
{"status":"ok","service":"JobTomatik API","version":"1.0.0"}
```

Keep this terminal open.

---

## 10. Start the Celery worker

Open a second Termux session, enter Ubuntu, and run:

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
redis-cli ping
celery -A app.celery_app worker \
  --loglevel=info \
  --pool=solo \
  -Q applications,celery,scraping,followup
```

Wait for:

```text
Connected to redis://localhost:6379/0
celery@localhost ready.
```

### Why `--pool=solo` is recommended

A multi-process prefork worker may launch multiple Chromium controllers at the same time. On Android/PRoot this increases memory use and can close the page while the API is trying to capture or control it. The solo worker processes one browser task at a time and is the reference v1 configuration.

Keep this terminal open.

---

## 11. Optional: start the browser frontend

The APK is preferred for ordinary use. For development, open a third regular Termux session outside Ubuntu:

```bash
cd ~/JobTomatik/frontend
VITE_API_URL=http://127.0.0.1:8010 npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

The browser and APK use the same backend database when both point to port 8010.

---

## 12. Install the JobTomatik APK

Open the repository’s Releases page and download:

```text
JobTomatik-v1.00.apk
```

Android may ask you to allow installs from your browser or file manager. Enable that permission only for the installation source you trust, install the APK, then optionally disable the permission again.

### Signing note

Open `BUILD-INFO.txt` from the release:

- `release` signing means the repository’s permanent signing secrets were configured;
- `development` signing means the APK is suitable for personal installation, but a future APK signed by another key may require uninstalling the old client first.

The backend database and résumé files are outside the APK, so reinstalling the client does not delete the Ubuntu backend database. Browser-local settings and login state may be cleared.

---

## 13. Connect the APK to the backend

Open JobTomatik.

When the API connection screen appears, enter:

```text
http://127.0.0.1:8010
```

Do not enter:

```text
http://127.0.0.1:8010/api
```

Test the connection. The backend terminal should log a request to `/health` or an `/api/...` route.

If the APK cannot connect:

1. confirm Uvicorn is still running;
2. run `curl http://127.0.0.1:8010/health` in Termux;
3. confirm the URL contains port `8010` and no `/api` suffix;
4. restart the APK after changing the stored API URL.

---

## 14. Create the first account and profile

1. Register with an email and password.
2. Open **Profile**.
3. Enter the legal name, preferred contact information, LinkedIn URL, portfolio URL when applicable, and other reusable profile fields.
4. Upload the current résumé PDF.
5. Save the profile.

The résumé must remain readable at the stored backend path. Do not delete the file from `backend/uploads/` while applications depend on it.

---

## 15. Configure the Answer Policy Vault

Open **Settings → Answer Policy Vault**.

Create only truthful reusable answers. Typical categories include:

- work authorization and sponsorship;
- willingness to relocate;
- salary expectation;
- referral source;
- optional demographic answers;
- employer-specific custom questions.

For sensitive or context-dependent questions, use **Ask every time**, **Skip**, or a non-disclosure option instead of inventing an answer.

Exact-option fields are verified against the employer’s current choices. For example, a policy value of `Man` will not silently map to an employer option labeled `Male`; the form pauses rather than guessing.

---

## 16. Search and approve a job

1. Open **Job Search**.
2. Enter the target role, location, and filters.
3. Run the search.
4. Open **Queue**.
5. Review the employer, title, location, source URL, and description.
6. Approve only the exact posting you intend to prepare.
7. Open the generated application record.

Job-search sources are best effort. Always verify the original posting before entering applicant data.

---

## 17. Prepare the application

On the application page:

1. review the title, employer, and original URL;
2. regenerate the cover letter when necessary;
3. verify the résumé attached to the profile;
4. resolve any open policy questions;
5. press **Dry Run (Preview)** once.

The page may show `applying` while Celery is filling the form. Watch the Celery terminal for:

```text
Task app.tasks.applications.submit_application_task[...] received
```

A complex form can take several minutes. Do not press Dry Run repeatedly while the state is `applying`.

---

## 18. Use the secure handoff

When a protected step appears, JobTomatik keeps the Chromium process alive and displays:

```text
Action required: CAPTCHA verification
Open secure handoff
```

Open it and interact with the browser image.

Available controls include:

- direct click inside the browser image;
- refresh image;
- type a secure value;
- **Replace and submit**;
- **Request new code**;
- **Go back**;
- **Reload page**;
- keyboard controls;
- **Start over**;
- **I completed the challenge**.

### Verification-code flow

1. Focus the code field by clicking it in the browser image.
2. Press **Request new code** when the old code has expired.
3. Wait for the newest email or SMS.
4. Paste only the newest code into JobTomatik.
5. Press **Replace and submit**.

That action selects the old field contents, replaces them, and presses Enter in one step. It prevents a valid code from being appended to an expired value.

### CAPTCHA flow

Complete the CAPTCHA manually in the retained browser. JobTomatik does not solve or bypass it.

---

## 19. Confirm a successful submission

A strong confirmation contains an explicit employer success signal, for example:

```text
Thank you for applying.
Your application has been received.
```

The final URL may also contain `/confirmation`.

When that page is visible, press:

```text
I completed the challenge
```

JobTomatik should:

1. recognize the confirmation page;
2. record sufficient submission evidence;
3. resolve the manual review;
4. mark the application `applied`;
5. move its automation state through `submitted` to `confirmed`;
6. close the retained browser;
7. hide further Dry Run and submit controls for that record.

Do not submit again after this state.

---

## 20. Follow up and update status

After submission, use the application page to:

- add notes;
- record recruiter details;
- schedule a follow-up;
- change status to interviewing, offer, rejected, or withdrawn;
- inspect submission evidence.

SendGrid is optional. Without a configured API key, email operations may be prepared or logged rather than delivered.

---

## 21. Build the APK locally

A desktop Linux/macOS/Windows machine with Android SDK is the easiest local build environment.

From the repository:

```bash
cd frontend
npm ci
npm run build:apk:debug
```

Output:

```text
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

Lint and assemble directly:

```bash
cd frontend
npm run android:prepare
cd android
./gradlew --no-daemon lintDebug assembleDebug
```

The Gradle wrapper downloads Gradle 8.11.1 from the official Gradle distribution service.

### Release signing

Generate and preserve a private signing key outside the repository:

```bash
keytool -genkeypair -v \
  -keystore jobtomatik-release.jks \
  -alias jobtomatik \
  -keyalg RSA \
  -keysize 4096 \
  -validity 10000
```

Build with environment variables:

```bash
export JOBTOMATIK_KEYSTORE_PATH=/secure/path/jobtomatik-release.jks
export JOBTOMATIK_KEYSTORE_PASSWORD='YOUR_STORE_PASSWORD'
export JOBTOMATIK_KEY_ALIAS='jobtomatik'
export JOBTOMATIK_KEY_PASSWORD='YOUR_KEY_PASSWORD'

cd frontend
npm run build:apk:release
```

Output:

```text
frontend/android/app/build/outputs/apk/release/app-release.apk
```

Never commit the keystore or passwords.

---

## 22. Configure permanent GitHub release signing

Create these repository Actions secrets:

```text
JOBTOMATIK_KEYSTORE_BASE64
JOBTOMATIK_KEYSTORE_PASSWORD
JOBTOMATIK_KEY_ALIAS
JOBTOMATIK_KEY_PASSWORD
```

Create the base64 value on Linux:

```bash
base64 -w 0 jobtomatik-release.jks
```

On macOS:

```bash
base64 < jobtomatik-release.jks | tr -d '\n'
```

Paste the single-line result into `JOBTOMATIK_KEYSTORE_BASE64`.

When all four secrets are available, the release workflow builds a permanently signed release APK. Otherwise it publishes a development-signed installable APK and states that fact in `BUILD-INFO.txt`.

---

## 23. Upgrade JobTomatik

Update the Ubuntu backend copy:

```bash
proot-distro login ubuntu
cd /root/JobTomatik
git checkout main
git pull --ff-only origin main
cd backend
source .venv/bin/activate
python -m pip install -r requirements.txt
alembic upgrade head
```

Update the Termux frontend copy:

```bash
exit 2>/dev/null || true
cd ~/JobTomatik
git checkout main
git pull --ff-only origin main
cd frontend
npm ci
```

Restart Uvicorn and Celery after every backend update.

Install the new APK over the old one only when both builds use the same signing key.

---

## 24. Backup and recovery

Stop Uvicorn and Celery before a consistent backup.

Back up at least:

```text
/root/JobTomatik/backend/jobtomatik.db
/root/JobTomatik/backend/.env
/root/JobTomatik/backend/uploads/
/root/JobTomatik/backend/handoff_sessions/   only when diagnosing an active handoff
Your private Android signing keystore
```

Example local backup:

```bash
cd /root/JobTomatik/backend
tar -czf /root/jobtomatik-backup-$(date +%Y%m%d-%H%M).tar.gz \
  jobtomatik.db .env uploads
```

Do not upload the backup to a public issue or repository.

---

## 25. Troubleshooting

### `source .venv/bin/activate: No such file or directory`

You are in the wrong directory or wrong environment.

Inside Ubuntu:

```bash
cd /root/JobTomatik/backend
source .venv/bin/activate
```

Outside Ubuntu, `/root/JobTomatik` does not exist.

### `No command uvicorn found`

You are probably in regular Termux or the virtual environment is not active.

```bash
proot-distro login ubuntu
cd /root/JobTomatik/backend
source .venv/bin/activate
which uvicorn
```

### Celery says `Cannot connect to redis://localhost:6379/0`

```bash
redis-server --daemonize yes
redis-cli ping
```

Wait for `PONG`, then restart Celery.

### The task stays queued

Confirm Celery shows:

```text
celery@localhost ready.
```

Confirm its queues include:

```text
applications
celery
scraping
followup
```

### The application stays `applying`

Do not queue another attempt. Check the Celery terminal. A browser task can take several minutes. If the worker crashed, restart Redis and Celery, then use the stale-attempt recovery process before retrying.

### The handoff panel never appears

Check the Celery result for:

```text
browser_handoff_retained
```

Use the current `main` branch, restart both Uvicorn and Celery, and run one preview with the solo worker.

### Handoff shows `claimed` but this tab has no lease

Use **Recover secure lease** after the previous lease expires. Do not open the same handoff in multiple tabs.

### Verification code is rejected

Request a new code, focus the field, paste only the newest code, and use **Replace and submit**. Old codes often become invalid immediately after a replacement is requested.

### “The retained browser still reports an active human-verification challenge” on a thank-you page

Update to v1.00 or newer. The confirmation detector must see explicit employer success text and/or the confirmation URL. Refresh the browser image and press **I completed the challenge** once.

### `Real application submission is disabled`

This is the expected safety gate when the red direct-submit action is used while `ALLOW_REAL_APPLICATION_SUBMIT=false`. Use Dry Run and the documented supervised flow. Do not enable the flag merely to remove the message.

### APK cannot reach the backend

Verify:

```bash
curl http://127.0.0.1:8010/health
```

Then set the app URL to exactly:

```text
http://127.0.0.1:8010
```

### Browser displays a CORS error

Add the exact UI origin to `CORS_ORIGINS`, separated by commas, then restart Uvicorn. Do not use `*` with credentialed requests.

### Android build tries to use `/tmp/gradle-8.11.1-all.zip`

Your repository is outdated. Pull `main`. v1.00 uses the official Gradle wrapper URL.

### Android build asks for `/home/user/JobTomatik/jobtomatik-release.jks`

Your repository is outdated. Pull `main`. Signing is now supplied through environment variables or private Gradle properties.

### New APK will not install over the old APK

The signing certificates differ. Preserve backend data, uninstall the old client, then install the new APK. Configure permanent signing secrets before the next public release to avoid repeating this.

---

## 26. Verification checklist

Before calling the installation ready:

```text
[ ] Ubuntu repository is on current main
[ ] Termux repository is on current main
[ ] Backend virtual environment activates
[ ] redis-cli ping returns PONG
[ ] Uvicorn health endpoint returns version 1.0.0
[ ] Celery says ready and uses --pool=solo
[ ] Frontend npm build passes
[ ] Résumé uploads successfully
[ ] Answer Policy Vault contains only approved truthful values
[ ] Dry Run fills a supported test application
[ ] Handoff opens and refreshes its browser image
[ ] Confirmation evidence closes the handoff
[ ] Confirmed applications hide new submission controls
[ ] ALLOW_REAL_APPLICATION_SUBMIT remains false
[ ] AUTOPILOT_ENABLED remains false
[ ] Database and signing key backups exist
```

Once every item is checked, JobTomatik v1.00 is ready for normal supervised use.

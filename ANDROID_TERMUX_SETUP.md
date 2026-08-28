# Android backend setup for login/register testing

The Android app must be able to reach a running JobTomatik backend before login
or registration can succeed. The frontend adds `/api` automatically, so enter the
base URL only.

For the canonical same-device Android/Termux setup, use:

```text
http://127.0.0.1:8010
```

Do **not** use port `3000` as the Backend API URL. Port 3000 is the React/Vite
frontend development server. Sending APK authentication through that frontend
proxy can produce a misleading HTTP 500 when the proxy cannot reach FastAPI.

## Recommended local Android setup

Native Termux Python can use very new Android Python builds that do not always
have compatible wheels for packages such as `pydantic-core`, Playwright, Pillow,
or PostgreSQL drivers. For local phone testing, use Ubuntu/proot with Python 3.11
or run the backend on another computer/server.

Inside the backend folder, install the Android-friendly API requirements when you
only need login/register/basic API routes:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
pip install --prefer-binary -r requirements.android-server.txt
```

Create a local `.env` for SQLite testing:

```bash
cat > .env <<'ENV'
DATABASE_URL=sqlite:///./jobtomatik.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=dev-secret-change-later
ANTHROPIC_API_KEY=
SENDGRID_API_KEY=
FROM_EMAIL=noreply@jobtomatik.local
RAPIDAPI_KEY=
UPLOAD_DIR=uploads
ENV
mkdir -p uploads
```

Start the same-device Android backend:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

The repository root helper performs the same setup and launch:

```bash
bash termux-start.sh
```

Test the exact backend health endpoint before trying auth in the app:

```bash
curl http://127.0.0.1:8010/api/system/health
```

Expected response:

```json
{"status":"ok","service":"JobTomatik API","version":"2.0.0"}
```

Then open the app login screen, expand **API connection**, tap **Reset** or set
`http://127.0.0.1:8010`, tap **Test connection**, and try signup/login.

## Backend running on another computer

When FastAPI runs on another computer, bind it to the network and use that
computer's LAN address:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Example APK Backend API URL:

```text
http://192.168.1.25:8000
```

## Notes

- Do not add `/api` to the API connection field.
- On Android, `127.0.0.1` is correct only when the backend runs on the same device.
- Port `8010` is the repository's canonical same-device Termux backend port.
- Port `8000` is the standard Docker or remote-computer backend port.
- Port `3000` is frontend-only and must not be saved as the APK Backend API URL.
- Playwright automation is not included in `requirements.android-server.txt` and
  should run on a normal Linux backend/worker.

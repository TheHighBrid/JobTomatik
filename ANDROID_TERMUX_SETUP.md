# Android backend setup for login/register testing

The Android app must be able to reach a running JobTomatik backend before login
or registration can succeed. The frontend adds `/api` automatically, so enter the
base URL only, for example `http://127.0.0.1:8000`.

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

Start the backend:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Test health before trying auth in the app:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","service":"JobTomatik API"}
```

Then open the app login screen, expand **API connection**, set
`http://127.0.0.1:8000`, tap **Test connection**, save, and try signup/login.

## Notes

- Do not add `/api` to the API connection field.
- On Android, `localhost` only works when the backend is running on the same
  device. If the backend runs on a computer, use that computer's LAN IP, such as
  `http://192.168.1.25:8000`.
- Playwright automation is not included in `requirements.android-server.txt` and
  should run on a normal Linux backend/worker.

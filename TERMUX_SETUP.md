# Running JobTomatik backend on Android (Termux)

Three copy-paste blocks. That's it.

---

## Block 1 — Install proot Ubuntu (run once in Termux)

```bash
pkg update -y && pkg install -y proot-distro
proot-distro install ubuntu
```

---

## Block 2 — Enter Ubuntu and run the setup script

Every time you want to start the backend:

```bash
proot-distro login ubuntu -- bash -c "
cd ~ &&
[ -d JobTomatik ] || git clone https://github.com/TheHighBrid/JobTomatik.git &&
cd JobTomatik &&
git pull --ff-only origin main 2>/dev/null || true &&
bash termux-start.sh
"
```

Wait for:
```
JobTomatik backend starting on port 8000
```

---

## Block 3 — Test (open a second Termux tab)

```bash
curl http://127.0.0.1:8000/health
```

Expected response:
```json
{"status":"ok","service":"JobTomatik API"}
```

If you see that, the backend is running.

---

## Set the API URL in the app

Open the JobTomatik app → Login screen → **API connection** field:

```
http://127.0.0.1:8000
```

Do **not** add `/api`. Then sign up or log in.

---

## Notes

- Uses **SQLite** locally — no PostgreSQL needed on Android
- Playwright (browser automation) is not available on Android; form-filling runs in dry-run only
- Cover letter generation works without `ANTHROPIC_API_KEY` (uses a template fallback)
- Redis starts automatically inside Ubuntu; if it fails the app still works for login/signup

## Restarting after a reboot

Just run Block 2 again. The `.env` and database are preserved between runs.

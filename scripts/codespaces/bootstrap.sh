#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
BACKEND_ENV="$ROOT_DIR/backend/.env"

cd "$ROOT_DIR"

printf '\n==> Preparing JobTomatik Codespaces workbench\n'

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

PYTHON_BIN="$VENV_DIR/bin/python" bash scripts/verify.sh bootstrap

if [[ ! -f "$BACKEND_ENV" ]]; then
  cp .env.example "$BACKEND_ENV"
  "$VENV_DIR/bin/python" - "$BACKEND_ENV" <<'PY'
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
replacements = {
    "DATABASE_URL=sqlite:///./jobtomatik.db": (
        "DATABASE_URL=postgresql://jobtomatik:jobtomatik_pass@127.0.0.1:5432/jobtomatik"
    ),
    "REDIS_URL=redis://localhost:6379/0": "REDIS_URL=redis://127.0.0.1:6379/0",
    "SECRET_KEY=replace-with-at-least-32-random-characters": (
        f"SECRET_KEY={secrets.token_urlsafe(48)}"
    ),
    "APPLICATION_BROWSER_HEADLESS=false": "APPLICATION_BROWSER_HEADLESS=true",
    "VITE_API_URL=http://127.0.0.1:8010": "VITE_API_URL=/api",
}
for old, new in replacements.items():
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
PY
  printf 'Created backend/.env with fail-safe Codespaces defaults.\n'
else
  printf 'Keeping existing backend/.env unchanged.\n'
fi

mkdir -p .codespaces/logs .codespaces/run
chmod +x scripts/codespaces/*.sh

cat <<'EOF'

JobTomatik workbench is ready.

Start or repair the local stack:
  bash scripts/codespaces/start.sh

Check services:
  bash scripts/codespaces/doctor.sh

Run the pre-commit gate:
  PYTHON_BIN=.venv/bin/python bash scripts/verify.sh fast
EOF

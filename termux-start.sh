#!/usr/bin/env bash
# JobTomatik backend — one-shot Termux (Ubuntu proot) setup and start
# Run this INSIDE proot-distro Ubuntu, not in bare Termux
# Usage: bash termux-start.sh

set -euo pipefail
cd "$(dirname "$0")/backend"

# ── 1. System deps (idempotent) ──────────────────────────────────────────────
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3-pip \
    build-essential libssl-dev libffi-dev zlib1g-dev \
    redis-server curl 2>/dev/null || true

PYTHON=$(command -v python3.11 || command -v python3)

# ── 2. Python venv ───────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
    $PYTHON -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip wheel setuptools -q

# ── 3. Install Termux-safe requirements ─────────────────────────────────────
pip install --prefer-binary --no-cache-dir -q -r requirements.termux.txt

# ── 4. .env (SQLite — no PostgreSQL needed) ─────────────────────────────────
if [ ! -f .env ]; then
    SECRET=$(python - <<'PY'
import secrets; print(secrets.token_urlsafe(48))
PY
)
    cat > .env <<EOF
DATABASE_URL=sqlite:///./jobtomatik.db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=${SECRET}
ANTHROPIC_API_KEY=
SENDGRID_API_KEY=
FROM_EMAIL=noreply@jobtomatik.local
RAPIDAPI_KEY=
UPLOAD_DIR=uploads
EOF
    echo "Created .env with SQLite + random SECRET_KEY"
fi

mkdir -p uploads

# ── 5. Start Redis ───────────────────────────────────────────────────────────
service redis-server start 2>/dev/null || redis-server --daemonize yes 2>/dev/null || true
sleep 1

# ── 6. Verify import ────────────────────────────────────────────────────────
python - <<'PY'
from app.main import app
print("✓ Backend imports OK")
PY

# ── 7. Start ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo " JobTomatik backend starting on port 8010"
echo " Test: curl http://127.0.0.1:8010/health"
echo " App API URL: http://127.0.0.1:8010"
echo "═══════════════════════════════════════════"
echo ""
uvicorn app.main:app --host 127.0.0.1 --port 8010

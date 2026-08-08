#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
ROLE="${1:-}"
shift || true

case "$ROLE" in
  api|worker|beat)
    ;;
  *)
    cat >&2 <<'EOF'
Usage: bash scripts/jobtomatik-runtime.sh <api|worker|beat> [extra arguments]

Examples:
  bash scripts/jobtomatik-runtime.sh api
  bash scripts/jobtomatik-runtime.sh worker
  bash scripts/jobtomatik-runtime.sh beat
EOF
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || {
  echo "git is required to derive the JobTomatik runtime revision" >&2
  exit 2
}

if [[ -z "${JOBTOMATIK_RUNTIME_REVISION:-}" ]]; then
  JOBTOMATIK_RUNTIME_REVISION="$(git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null || true)"
fi
if [[ ! "$JOBTOMATIK_RUNTIME_REVISION" =~ ^[0-9a-fA-F]{7,64}$ ]]; then
  echo "Unable to derive a valid JobTomatik runtime commit SHA" >&2
  exit 2
fi

export JOBTOMATIK_RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION,,}"
export JOBTOMATIK_EXPECTED_REVISION="${JOBTOMATIK_EXPECTED_REVISION:-$JOBTOMATIK_RUNTIME_REVISION}"
export JOBTOMATIK_RUNTIME_ROLE="$ROLE"

if [[ "$JOBTOMATIK_EXPECTED_REVISION" != "$JOBTOMATIK_RUNTIME_REVISION" ]]; then
  echo "JOBTOMATIK_EXPECTED_REVISION must equal JOBTOMATIK_RUNTIME_REVISION" >&2
  exit 2
fi

PYTHON_BIN="${JOBTOMATIK_PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" && -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python is required to launch the JobTomatik runtime" >&2
  exit 2
fi

cd "$BACKEND_DIR"
"$PYTHON_BIN" scripts/check_runtime_identity.py --require-sensitive

printf 'Launching JobTomatik %s at revision %s\n' "$ROLE" "$JOBTOMATIK_RUNTIME_REVISION"

case "$ROLE" in
  api)
    exec "$PYTHON_BIN" -m uvicorn app.main:app \
      --host 127.0.0.1 \
      --port "${JOBTOMATIK_API_PORT:-8010}" \
      --log-level "${JOBTOMATIK_API_LOG_LEVEL:-info}" \
      "$@"
    ;;
  worker)
    exec "$PYTHON_BIN" -m celery -A app.celery_app worker \
      --loglevel="${JOBTOMATIK_CELERY_LOG_LEVEL:-info}" \
      --pool=solo \
      --concurrency=1 \
      -Q applications,celery,scraping,followup \
      "$@"
    ;;
  beat)
    exec "$PYTHON_BIN" -m celery -A app.celery_app beat \
      --loglevel="${JOBTOMATIK_CELERY_LOG_LEVEL:-info}" \
      "$@"
    ;;
esac

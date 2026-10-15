#!/usr/bin/env bash
# Fresh, disposable production-topology validation. Never targets an existing stack.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null
docker info >/dev/null
revision="$(git rev-parse HEAD)"
project="jt5-smoke-${GITHUB_RUN_ID:-local}-$$"
evidence="${JT5_SMOKE_EVIDENCE_DIR:-verification-artifacts/jt5-onehost-operational}"
mkdir -p "$evidence"
secrets_file="$(mktemp)"
chmod 600 "$secrets_file"
python - "$revision" > "$secrets_file" <<'PY'
import secrets
import sys
for name in ('POSTGRES_PASSWORD', 'SECRET_KEY', 'ANSWER_VAULT_KEY'):
    print(name + '=' + secrets.token_hex(32))
print('JOBTOMATIK_RUNTIME_REVISION=' + sys.argv[1])
for name in ('ALLOW_REAL_APPLICATION_SUBMIT', 'ALLOW_REAL_FOLLOWUP_SEND',
             'AUTOPILOT_ENABLED', 'GREENHOUSE_SUPERVISED_PILOT_ENABLED',
             'LEVER_SUPERVISED_PILOT_ENABLED'):
    print(name + '=false')
print('AI_PROVIDER=template')
PY
# Prevent inherited host settings, tokens or email keys from entering the CI stack.
unset POSTGRES_PASSWORD SECRET_KEY ANSWER_VAULT_KEY JOBTOMATIK_RUNTIME_REVISION
unset ALLOW_REAL_APPLICATION_SUBMIT ALLOW_REAL_FOLLOWUP_SEND AUTOPILOT_ENABLED
unset GREENHOUSE_SUPERVISED_PILOT_ENABLED LEVER_SUPERVISED_PILOT_ENABLED
unset ANTHROPIC_API_KEY SENDGRID_API_KEY AI_PROVIDER ONEHOST_API_PORT ONEHOST_API_BIND_ADDRESS
dc() { docker compose --env-file "$secrets_file" -p "$project" -f docker-compose.onehost-production.yml "$@"; }
cleanup() {
    status=$?
    trap - EXIT
    dc ps --format json > "$evidence/containers.json" 2>/dev/null || true
    # Redact generated secrets before writing any retained logs.
    dc logs --no-color 2>&1 | python -c '
import pathlib, sys
values = [line.split("=", 1)[1] for line in pathlib.Path(sys.argv[1]).read_text().splitlines()
          if line.startswith(("POSTGRES_PASSWORD=", "SECRET_KEY=", "ANSWER_VAULT_KEY="))]
data = sys.stdin.read()
for value in values:
    data = data.replace(value, "[REDACTED]")
sys.stdout.write(data)
' "$secrets_file" > "$evidence/redacted.log" || true
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    rm -f "$secrets_file"
    exit "$status"
}
trap cleanup EXIT
printf '%s\n' "$revision" > "$evidence/revision.txt"
dc config -q
test "$(dc config --services | sort | tr '\n' ' ')" = "backend celery_worker db redis "
dc build >/dev/null
dc up -d --wait --wait-timeout 120 db redis
dc run --rm --no-deps backend python -m alembic upgrade head
dc up -d --wait --wait-timeout 180
for phase in before after; do
    dc exec -T -e JT5_ISOLATED_SMOKE=1 backend python -m scripts.smoke_onehost_operational api "$phase" | tee "$evidence/api-$phase.json"
    dc exec -T -e JT5_ISOLATED_SMOKE=1 celery_worker python -m scripts.smoke_onehost_operational browser "$phase" | tee "$evidence/browser-$phase.json"
    # Mandatory native-owner integration, including after the complete restart.
    # All fixture URLs are intercepted; pytest uses its own synthetic test DB.
    dc exec -T -e APP_ENV=test -e REQUIRE_OWNER_DISPLAY_TESTS=1 \
        -e JT5_OWNER_EVIDENCE_DIR="/tmp/owner-handoff-$phase" \
        backend python -m pytest -q tests/test_owner_handoff_runtime.py
    dc cp "backend:/tmp/owner-handoff-$phase" "$evidence/owner-handoff-$phase"
    dc exec -T backend python -c '
from app.celery_app import celery_app
stats = celery_app.control.inspect(timeout=10).stats()
assert stats and len(stats) == 1
assert next(iter(stats.values()))["pool"]["max-concurrency"] == 1
print("single worker concurrency=1 verified")'
    if [[ "$phase" = before ]]; then
        # Preserve all volumes; restart each dependency through the actual boot chain.
        dc stop celery_worker backend redis db
        dc up -d --wait --wait-timeout 180
    fi
done
printf '%s\n' 'Production Compose isolated operational smoke passed (including restart).'

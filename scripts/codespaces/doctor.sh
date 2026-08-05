#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_TESTS=false

if [[ "${1:-}" == "--test" ]]; then
  RUN_TESTS=true
fi

cd "$ROOT_DIR"

printf 'JobTomatik Codespaces doctor\n'
printf '%-18s %s\n' 'Workspace' "$ROOT_DIR"
printf '%-18s %s\n' 'Python' "$(.venv/bin/python --version 2>&1 || true)"
printf '%-18s %s\n' 'Node' "$(node --version 2>&1 || true)"
printf '%-18s %s\n' 'npm' "$(npm --version 2>&1 || true)"
printf '%-18s %s\n' 'Java' "$(java -version 2>&1 | head -n 1 || true)"
printf '%-18s %s\n' 'GitHub CLI' "$(gh --version 2>&1 | head -n 1 || true)"
printf '%-18s %s\n' 'Docker' "$(docker --version 2>&1 || true)"
printf '%-18s %s\n' 'Compose' "$(docker compose version 2>&1 || true)"
printf '%-18s %s\n' 'PostgreSQL CLI' "$(psql --version 2>&1 || true)"
printf '%-18s %s\n' 'Redis CLI' "$(redis-cli --version 2>&1 || true)"
printf '%-18s %s\n' 'Playwright' "$(.venv/bin/python -m playwright --version 2>&1 || true)"

printf '\nDocker services\n'
docker compose ps 2>/dev/null || true

printf '\nApplication health\n'
if curl -fsS http://127.0.0.1:8000/api/system/ready >/dev/null 2>&1; then
  printf 'API:      ready\n'
else
  printf 'API:      unavailable\n'
fi

if curl -fsS http://127.0.0.1:3000 >/dev/null 2>&1; then
  printf 'Frontend: ready\n'
else
  printf 'Frontend: unavailable\n'
fi

if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -Fq PONG; then
  printf 'Redis:    ready\n'
else
  printf 'Redis:    unavailable\n'
fi

if docker compose exec -T db pg_isready -U jobtomatik >/dev/null 2>&1; then
  printf 'Postgres: ready\n'
else
  printf 'Postgres: unavailable\n'
fi

printf '\nRecent logs\n'
for log_file in .codespaces/logs/*.log; do
  [[ -e "$log_file" ]] || continue
  printf '\n--- %s ---\n' "$log_file"
  tail -n 12 "$log_file" || true
done

if $RUN_TESTS; then
  printf '\nRunning canonical fast verification...\n'
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python" bash scripts/verify.sh fast
fi

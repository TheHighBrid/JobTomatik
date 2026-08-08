#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${JOBTOMATIK_RUNTIME_REVISION:-}" ]]; then
  command -v git >/dev/null 2>&1 || {
    echo "git is required to derive JOBTOMATIK_RUNTIME_REVISION" >&2
    exit 2
  }
  JOBTOMATIK_RUNTIME_REVISION="$(git rev-parse HEAD 2>/dev/null || true)"
fi

if [[ ! "$JOBTOMATIK_RUNTIME_REVISION" =~ ^[0-9a-fA-F]{7,64}$ ]]; then
  echo "Unable to derive a valid JobTomatik runtime commit SHA" >&2
  exit 2
fi

export JOBTOMATIK_RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION,,}"
export JOBTOMATIK_EXPECTED_REVISION="${JOBTOMATIK_EXPECTED_REVISION:-$JOBTOMATIK_RUNTIME_REVISION}"

if [[ "$JOBTOMATIK_EXPECTED_REVISION" != "$JOBTOMATIK_RUNTIME_REVISION" ]]; then
  echo "JOBTOMATIK_EXPECTED_REVISION must equal JOBTOMATIK_RUNTIME_REVISION" >&2
  exit 2
fi

printf 'JobTomatik runtime revision: %s\n' "$JOBTOMATIK_RUNTIME_REVISION"
printf 'JobTomatik expected revision: %s\n' "$JOBTOMATIK_EXPECTED_REVISION"

if [[ $# -eq 0 ]]; then
  set -- up
fi
exec docker compose "$@"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
command -v docker >/dev/null || { echo "Docker is required for the Compose proof" >&2; exit 2; }
export JOBTOMATIK_RUNTIME_REVISION="$(git rev-parse HEAD)"
mkdir -p "$ROOT_DIR/verification-artifacts"
export ONEHOST_EVIDENCE_DIR="$(mktemp -d "$ROOT_DIR/verification-artifacts/onehost-fixture.XXXXXX")"
fixture_project="jt-onehost-${GITHUB_RUN_ID:-local}-$$"
compose=(docker compose --env-file /dev/null --project-name "$fixture_project" --file docker-compose.onehost-fixture.yml)
cleanup() { "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

"${compose[@]}" config --format json > "$ONEHOST_EVIDENCE_DIR/compose.json"
"${compose[@]}" build backend 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/build.log"
"${compose[@]}" run --rm -T backend python -m pytest -q \
  tests/test_onehost_fixture_gate.py tests/test_ats_flow_safety.py \
  tests/test_control_engine_playwright.py 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/tests.log"
"${compose[@]}" run --rm -T backend 2>&1 | tee "$ONEHOST_EVIDENCE_DIR/proof.log"
printf 'Fixture proof and traces: %s\n' "$ONEHOST_EVIDENCE_DIR"

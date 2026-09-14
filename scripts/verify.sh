#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLCHAIN_FILE="$ROOT_DIR/.jobtomatik-toolchain.env"
MODE="${1:-fast}"
INSTALL_DEPS=false

if [[ "${2:-}" == "--install" || "${1:-}" == "--install" ]]; then
  INSTALL_DEPS=true
  [[ "${1:-}" == "--install" ]] && MODE="fast"
fi

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

step() {
  printf '\n==> %s\n' "$*"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command '$1' is not installed or not on PATH."
}

[[ -f "$TOOLCHAIN_FILE" ]] || fail "Missing $TOOLCHAIN_FILE"
# shellcheck disable=SC1090
source "$TOOLCHAIN_FILE"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

# Verification must be independent of an interactive shell's deployment mode.
# Runtime deployments choose their own APP_ENV values; local gates preserve development defaults.
unset APP_ENVIRONMENT
export APP_ENV=development
export DATABASE_URL="${DATABASE_URL:-sqlite:///./jobtomatik-verification.db}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export SECRET_KEY="${SECRET_KEY:-jobtomatik-development-secret}"
export AI_PROVIDER=template
export DEV_MOCK_JOBS=false
export ALLOW_REAL_APPLICATION_SUBMIT=false
export ALLOW_REAL_FOLLOWUP_SEND=false
export AUTOPILOT_ENABLED=false
export ENABLE_RESUMABLE_HANDOFFS=false
export REQUIRE_BROWSER_TESTS="${REQUIRE_BROWSER_TESTS:-1}"

cleanup() {
  rm -f \
    "$ROOT_DIR/backend/jobtomatik-verification.db" \
    "$ROOT_DIR/backend/jobtomatik-migration-verification.db" \
    "$ROOT_DIR/backend/alembic-verification.ini"
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage: bash scripts/verify.sh [mode] [--install]

Modes:
  device         Report a read-only, device-aware verification plan (no version gate).
  toolchain      Validate and print the canonical toolchain.
  bootstrap      Install backend, Playwright Chromium, and frontend dependencies.
  fast           Pre-commit gate: toolchain, compile, focused safety tests, frontend tests.
  backend-tests  Full backend and browser test suite only.
  migration      Alembic migration smoke test only.
  dependencies   Validate installed Python packages and audit backend/frontend dependencies.
  safety         Fail-safe settings and canonical adapter maturity only.
  backend        Backend tests, migration smoke test, and safety manifest.
  frontend       Frontend runtime tests and production build.
  deployment     Docker Compose rendering and fail-safe default verification.
  android        Capacitor synchronization, Gradle lint, APK assembly, identity/version checks.
  full           Run dependency, backend, frontend, deployment, and Android gates in order.

Add --install to install Python/Playwright/npm dependencies before the selected mode.
EOF
}

check_base_toolchain() {
  step "Validate canonical Python and Node toolchain"
  require_command "$PYTHON_BIN"
  require_command node
  require_command npm

  local python_version node_version node_major
  python_version="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  [[ "$python_version" == "$JOBTOMATIK_PYTHON_MAJOR_MINOR" ]] || \
    fail "Python $JOBTOMATIK_PYTHON_MAJOR_MINOR is required; found $python_version via $PYTHON_BIN."

  node_version="$(node --version | sed 's/^v//')"
  node_major="${node_version%%.*}"
  [[ "$node_major" == "$JOBTOMATIK_NODE_MAJOR" ]] || \
    fail "Node $JOBTOMATIK_NODE_MAJOR.x is required; found $node_version."
  "$PYTHON_BIN" - "$node_version" "$JOBTOMATIK_NODE_MIN_VERSION" <<'PY' || \
    fail "Node $JOBTOMATIK_NODE_MIN_VERSION or newer is required; found $node_version."
import re
import sys


def version(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise SystemExit(1)
    return tuple(int(part) for part in match.groups())

raise SystemExit(0 if version(sys.argv[1]) >= version(sys.argv[2]) else 1)
PY

  printf 'Python: %s\n' "$($PYTHON_BIN --version 2>&1)"
  printf 'Node:   %s\n' "$(node --version)"
  printf 'npm:    %s\n' "$(npm --version)"
}

check_android_toolchain() {
  step "Validate canonical Android toolchain"
  require_command java
  local java_major wrapper agp
  java_major="$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.specification.version/ {print $2; exit}')"
  [[ "$java_major" == "$JOBTOMATIK_JAVA_MAJOR" ]] || \
    fail "Java $JOBTOMATIK_JAVA_MAJOR is required; found ${java_major:-unknown}."

  wrapper="$ROOT_DIR/frontend/android/gradle/wrapper/gradle-wrapper.properties"
  agp="$ROOT_DIR/frontend/android/build.gradle"
  grep -Fq "gradle-$JOBTOMATIK_GRADLE_VERSION-bin.zip" "$wrapper" || \
    fail "Gradle wrapper is not pinned to $JOBTOMATIK_GRADLE_VERSION."
  grep -Fq "com.android.tools.build:gradle:$JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION" "$agp" || \
    fail "Android Gradle Plugin is not pinned to $JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION."
  grep -Eq "compileSdkVersion = $JOBTOMATIK_ANDROID_API$" "$ROOT_DIR/frontend/android/variables.gradle" || \
    fail "Android compile SDK is not $JOBTOMATIK_ANDROID_API."
  grep -Eq "targetSdkVersion = $JOBTOMATIK_ANDROID_API$" "$ROOT_DIR/frontend/android/variables.gradle" || \
    fail "Android target SDK is not $JOBTOMATIK_ANDROID_API."

  printf 'Java:   %s\n' "$(java -version 2>&1 | head -n 1)"
  printf 'Gradle: %s (wrapper)\n' "$JOBTOMATIK_GRADLE_VERSION"
  printf 'AGP:    %s\n' "$JOBTOMATIK_ANDROID_GRADLE_PLUGIN_VERSION"
  printf 'Android API / Build Tools: %s / %s\n' "$JOBTOMATIK_ANDROID_API" "$JOBTOMATIK_ANDROID_BUILD_TOOLS"
}

bootstrap() {
  check_base_toolchain
  step "Install backend dependencies"
  "$PYTHON_BIN" -m pip install -r "$ROOT_DIR/backend/requirements.txt"
  step "Install Playwright Chromium and Linux system dependencies"
  "$PYTHON_BIN" -m playwright install --with-deps chromium
  step "Install frontend dependencies"
  (cd "$ROOT_DIR/frontend" && npm ci --engine-strict)
}

backend_fast() {
  step "Lint backend"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m ruff check app scripts tests)
  step "Compile backend"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m compileall -q app tests)
  step "Run focused backend safety tests"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m pytest -q --tb=short \
    tests/test_reproducible_verification_contract.py \
    tests/test_control_policy_vault_safety.py \
    tests/test_ats_maturity.py \
    tests/test_operations_policy.py \
    tests/test_supervised_submission_approval.py \
    tests/test_supervised_followup.py)
}

backend_full() {
  local report_path="$ROOT_DIR/backend/verification-pytest-output.txt"
  local status

  step "Lint backend"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m ruff check app scripts tests)
  step "Compile backend"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m compileall -q app tests)
  step "Run full backend and browser suite"

  set +e
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m pytest -q --tb=short --maxfail=5 -ra >"$report_path" 2>&1)
  status=$?
  set -e

  cat "$report_path"
  return "$status"
}

migration_smoke() {
  step "Run Alembic migration smoke test"
  cp "$ROOT_DIR/backend/alembic.ini" "$ROOT_DIR/backend/alembic-verification.ini"
  sed -i.bak \
    's#sqlalchemy.url = .*#sqlalchemy.url = sqlite:///./jobtomatik-migration-verification.db#' \
    "$ROOT_DIR/backend/alembic-verification.ini"
  rm -f "$ROOT_DIR/backend/alembic-verification.ini.bak"
  (cd "$ROOT_DIR/backend" && DATABASE_URL=sqlite:///./jobtomatik-migration-verification.db \
    "$PYTHON_BIN" -m alembic -c alembic-verification.ini upgrade head)
}

frontend_tests() {
  step "Run frontend runtime tests"
  (cd "$ROOT_DIR/frontend" && npm test)
}

frontend_full() {
  frontend_tests
  step "Build frontend production bundle"
  (cd "$ROOT_DIR/frontend" && npm run build)
}

dependency_check() {
  step "Validate installed backend dependency consistency"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m pip check)
  step "Audit pinned backend dependencies"
  (cd "$ROOT_DIR/backend" && "$PYTHON_BIN" -m pip_audit \
    -r requirements.txt --progress-spinner off)
  step "Audit frontend runtime dependencies at high severity"
  (
    cd "$ROOT_DIR/frontend"
    npm ci --engine-strict --ignore-scripts --no-audit --no-fund
    local report
    report="$(mktemp)"
    trap 'rm -f "$report"' EXIT
    npm audit --omit=dev --json >"$report" || true
    "$PYTHON_BIN" "$ROOT_DIR/scripts/validate_npm_audit.py" "$report"
  )
}

safety_manifest() {
  step "Verify fail-safe settings and canonical adapter maturity"
  (
    cd "$ROOT_DIR/backend"
    ALLOW_REAL_APPLICATION_SUBMIT=false \
    ALLOW_REAL_FOLLOWUP_SEND=false \
    GREENHOUSE_SUPERVISED_PILOT_ENABLED=false \
    LEVER_SUPERVISED_PILOT_ENABLED=false \
    AUTOPILOT_ENABLED=false \
    ENABLE_RESUMABLE_HANDOFFS=false \
    "$PYTHON_BIN" - <<'PY'
from app.config import get_settings
from app.services.ats_manifest import ats_certification_manifest
from app.services.operations_policy import operations_readiness_manifest

settings = get_settings()
operations = operations_readiness_manifest()
ats = ats_certification_manifest()
adapters = {item["name"]: item for item in ats["adapters"]}

assert settings.allow_real_application_submit is False
assert settings.allow_real_followup_send is False
assert settings.greenhouse_supervised_pilot_enabled is False
assert settings.lever_supervised_pilot_enabled is False
assert settings.enable_resumable_handoffs is False
assert operations["real_submission_enabled"] is False
assert operations["autopilot_enabled"] is False
assert ats["autonomous_adapters"] == []
assert all(item["autonomous_submission_allowed"] is False for item in adapters.values())
assert {name: item["maturity"] for name, item in adapters.items()} == {
    "greenhouse": "dry_run",
    "lever": "dry_run",
    "ashby": "dry_run",
    "smartrecruiters": "detect_only",
    "workday": "detect_only",
}
print("Fail-safe settings, outbound communication, and canonical maturity verified")
PY
  )
}

deployment_check() {
  step "Validate repository Docker Compose defaults"
  require_command docker
  local rendered
  local -a clean_env=(
    env
    -u ALLOW_REAL_APPLICATION_SUBMIT
    -u ALLOW_REAL_FOLLOWUP_SEND
    -u GREENHOUSE_SUPERVISED_PILOT_ENABLED
    -u LEVER_SUPERVISED_PILOT_ENABLED
    -u ENABLE_RESUMABLE_HANDOFFS
    -u AUTOPILOT_ENABLED
  )

  (cd "$ROOT_DIR" && "${clean_env[@]}" docker compose config --quiet)
  rendered="$(cd "$ROOT_DIR" && "${clean_env[@]}" docker compose config)"
  grep -Fq 'ALLOW_REAL_APPLICATION_SUBMIT: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve ALLOW_REAL_APPLICATION_SUBMIT=false."
  grep -Fq 'ALLOW_REAL_FOLLOWUP_SEND: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve ALLOW_REAL_FOLLOWUP_SEND=false."
  grep -Fq 'GREENHOUSE_SUPERVISED_PILOT_ENABLED: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve GREENHOUSE_SUPERVISED_PILOT_ENABLED=false."
  grep -Fq 'LEVER_SUPERVISED_PILOT_ENABLED: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve LEVER_SUPERVISED_PILOT_ENABLED=false."
  grep -Fq 'ENABLE_RESUMABLE_HANDOFFS: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve ENABLE_RESUMABLE_HANDOFFS=false."
  grep -Fq 'AUTOPILOT_ENABLED: "false"' <<<"$rendered" || \
    fail "Compose default does not preserve AUTOPILOT_ENABLED=false."
}

android_check() {
  check_android_toolchain
  step "Build and synchronize Capacitor Android project"
  (cd "$ROOT_DIR/frontend" && npm run android:prepare)
  chmod +x "$ROOT_DIR/frontend/android/gradlew"
  step "Run Android lint and assemble debug APK"
  (cd "$ROOT_DIR/frontend/android" && ./gradlew --no-daemon lintDebug assembleDebug)

  local apk aapt badging
  apk="$ROOT_DIR/frontend/android/app/build/outputs/apk/debug/app-debug.apk"
  [[ -s "$apk" ]] || fail "Android APK was not produced at $apk."
  [[ -n "${ANDROID_HOME:-}" ]] || fail "ANDROID_HOME is required for APK identity verification."
  aapt="$ANDROID_HOME/build-tools/$JOBTOMATIK_ANDROID_BUILD_TOOLS/aapt"
  [[ -x "$aapt" ]] || fail "Missing Android aapt at $aapt. Install Build Tools $JOBTOMATIK_ANDROID_BUILD_TOOLS."
  badging="$($aapt dump badging "$apk")"
  grep -Fq "package: name='ca.jobtomatik.app'" <<<"$badging" || fail "Unexpected Android application ID."
  grep -Fq "versionCode='210'" <<<"$badging" || fail "Unexpected Android versionCode."
  grep -Fq "versionName='2.1.0'" <<<"$badging" || fail "Unexpected Android versionName."
}

case "$MODE" in
  -h|--help|help)
    usage
    ;;
  bootstrap)
    bootstrap
    ;;
  device)
    bash "$ROOT_DIR/scripts/audit-device-readiness.sh"
    ;;
  toolchain)
    check_base_toolchain
    check_android_toolchain
    ;;
  fast)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    backend_fast
    frontend_tests
    safety_manifest
    ;;
  backend-tests)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    backend_full
    ;;
  migration)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    migration_smoke
    ;;
  dependencies)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    dependency_check
    ;;
  safety)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    safety_manifest
    ;;
  backend)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    backend_full
    migration_smoke
    safety_manifest
    ;;
  frontend)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    frontend_full
    ;;
  deployment)
    check_base_toolchain
    deployment_check
    ;;
  android)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    android_check
    ;;
  full)
    $INSTALL_DEPS && bootstrap
    check_base_toolchain
    dependency_check
    backend_full
    migration_smoke
    safety_manifest
    frontend_full
    deployment_check
    android_check
    ;;
  *)
    usage >&2
    fail "Unknown verification mode '$MODE'."
    ;;
esac

printf '\nVerification mode %s passed.\n' "$MODE"
#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only planner for choosing the cheapest truthful verification lane on the
# current host. Environment overrides make its classification testable in CI.
ARCH="${JOBTOMATIK_AUDIT_ARCH:-$(uname -m)}"
PREFIX_VALUE="${JOBTOMATIK_AUDIT_PREFIX:-${PREFIX:-}}"
PROOT_VALUE="${JOBTOMATIK_AUDIT_PROOT:-${PROOT_DISTRO:-${PROOT_LOADER:-}}}"

has_command() {
  if [[ -n "${JOBTOMATIK_AUDIT_COMMANDS:-}" ]]; then
    [[ ",${JOBTOMATIK_AUDIT_COMMANDS}," == *",$1,"* ]]
  else
    command -v "$1" >/dev/null 2>&1
  fi
}

is_arm=false
[[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && is_arm=true
is_termux=false
[[ "$PREFIX_VALUE" == *"com.termux"* ]] && is_termux=true
is_proot=false
[[ -n "$PROOT_VALUE" ]] && is_proot=true

browser=missing
for candidate in chromium chromium-browser google-chrome; do
  if has_command "$candidate"; then browser="$candidate"; break; fi
done

java_state=missing
has_command java && java_state=available
docker_state=missing
has_command docker && docker_state=available

profile=standard_linux
if $is_termux && $is_arm; then
  profile=termux_arm64
elif $is_proot && $is_arm; then
  profile=ubuntu_proot_arm64
elif $is_arm; then
  profile=linux_arm64
fi

cat <<EOF
JOBTOMATIK_DEVICE_READINESS_V1
profile=$profile
architecture=$ARCH
termux=$is_termux
proot=$is_proot
chromium=$browser
java=$java_state
docker=$docker_state
EOF

case "$profile" in
  termux_arm64)
    cat <<'EOF'
recommended_runtime=Termux-native Chromium plus the Ubuntu/proot API-worker stack
recommended_gate=bash backend/scripts/android_frontend_guard.sh check
defer=Playwright-managed Chromium, Docker Compose, and Gradle APK builds
EOF
    ;;
  ubuntu_proot_arm64|linux_arm64)
    cat <<'EOF'
recommended_runtime=SQLite, Redis, API, worker, Beat, Vite, and external Termux Chromium CDP
recommended_gate=python -m pytest -q tests/test_android_runtime_scripts.py tests/test_external_cdp_runtime.py tests/test_campaign_day_gates.py
defer=Docker Compose and on-device Gradle unless their toolchains are explicitly installed
EOF
    ;;
  *)
    cat <<'EOF'
recommended_runtime=canonical Linux development and verification stack
recommended_gate=bash scripts/verify.sh fast
defer=none; run unavailable deployment or Android lanes on CI and record them separately
EOF
    ;;
esac

cat <<'EOF'
safety=This audit never enables submission, outreach, autopilot, or adapter promotion.
EOF

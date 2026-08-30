#!/usr/bin/env bash
# JobTomatik Android project preparer.
# Canonical toolchain versions live in .jobtomatik-toolchain.env.
# This helper prepares the Capacitor Android project; it does not publish an APK.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLCHAIN_FILE="$ROOT_DIR/.jobtomatik-toolchain.env"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [[ ! -f "$TOOLCHAIN_FILE" ]]; then
  echo "Missing canonical toolchain file: $TOOLCHAIN_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$TOOLCHAIN_FILE"

command -v node >/dev/null 2>&1 || { echo "Node.js is required." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required." >&2; exit 1; }
command -v java >/dev/null 2>&1 || { echo "Java is required." >&2; exit 1; }

echo "==> Canonical JobTomatik Android toolchain"
echo "    Node:          >= ${JOBTOMATIK_NODE_MIN_VERSION} within major ${JOBTOMATIK_NODE_MAJOR}"
echo "    Java:          ${JOBTOMATIK_JAVA_MAJOR}"
echo "    Gradle:        ${JOBTOMATIK_GRADLE_VERSION}"
echo "    Android API:   ${JOBTOMATIK_ANDROID_API}"
echo "    Build tools:   ${JOBTOMATIK_ANDROID_BUILD_TOOLS}"
echo ""
echo "==> Detected"
echo "    Node: $(node --version)"
echo "    npm:  $(npm --version)"
echo "    Java: $(java -version 2>&1 | head -n 1)"
echo ""

cd "$FRONTEND_DIR"

echo "==> Installing locked frontend dependencies with npm ci..."
npm ci

echo "==> Building React and synchronizing Capacitor Android..."
npm run android:prepare

echo ""
echo "==> Android project prepared. Choose an assembly path:"
echo ""
echo "  Development APK:"
echo "    cd frontend && npm run build:apk:debug"
echo "    Output: frontend/android/app/build/outputs/apk/debug/app-debug.apk"
echo ""
echo "  Android lint:"
echo "    cd frontend && npm run android:lint"
echo ""
echo "  Release variant (external signing material may be required):"
echo "    cd frontend && npm run build:apk:release"
echo "    Output: frontend/android/app/build/outputs/apk/release/"
echo ""
echo "  Android Studio:"
echo "    cd frontend && npm run android:open"
echo ""
echo "This helper does not publish, tag, or authorize real submission."

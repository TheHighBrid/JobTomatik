#!/usr/bin/env bash
# JobTomatik APK builder
# Requires: Node 18+, Java 17+, Android SDK, Capacitor CLI

set -euo pipefail

FRONTEND_DIR="$(cd "$(dirname "$0")/frontend" && pwd)"
cd "$FRONTEND_DIR"

echo "==> Installing frontend dependencies..."
npm install

echo "==> Building React app..."
npm run build

echo "==> Syncing to Capacitor Android..."
npx cap sync android

echo ""
echo "==> Build complete. Choose how to finish:"
echo ""
echo "  Option A — Android Studio (recommended first time):"
echo "    npx cap open android"
echo "    Then in Android Studio: Build > Generate Signed Bundle/APK"
echo ""
echo "  Option B — Gradle command line (CI/headless):"
echo "    cd android && ./gradlew assembleDebug"
echo "    APK will be at: android/app/build/outputs/apk/debug/app-debug.apk"
echo ""
echo "  Option C — Release APK (needs keystore):"
echo "    cd android && ./gradlew assembleRelease"
echo ""

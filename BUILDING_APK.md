# Building the JobTomatik Android APK

This document describes the current v2 Android build path. The canonical toolchain is defined in `.jobtomatik-toolchain.env`; if a version in this document ever disagrees with that file, the toolchain file wins.

## Canonical toolchain

| Tool | Current verified contract |
|---|---|
| Python | 3.11 |
| Node.js | 20.19.0 or newer within major 20 |
| npm | 10.8.2 package-manager contract |
| Java | 21 |
| Gradle | 9.5.1 wrapper |
| Android Gradle Plugin | 8.13.2 |
| Android SDK | API 35 |
| Android build tools | 35.0.0 |

The v2 candidate Android identity is `versionCode 200` and `versionName "2.0.0"`. Release identity is checked by CI and must remain aligned with the root `VERSION` file and frontend package metadata.

## Release safety boundary

- APKs, AABs, keystores, and signing files are build artifacts. Do not commit them. `.gitignore` intentionally excludes `*.apk`, `*.aab`, `*.jks`, and related signing material.
- A PR or local debug APK is not the final v2 release asset.
- The final v2 publication path uses `.github/workflows/build-v2-release-candidate.yml` to build one exact-source candidate and the owner-only publisher to download and verify those exact prebuilt bytes. The publisher must not rebuild after approval.
- Real application submission and recruiter follow-up permissions are independent runtime controls. Building an APK does not authorize either one.

## 1. Install the verified toolchain

Use the versions in `.jobtomatik-toolchain.env`. For a reproducible frontend install, use the lockfile:

```bash
cd frontend
npm ci
```

Do not substitute a dependency-refresh operation when preparing a release candidate. Dependency changes belong in their own reviewed commit with a regenerated lockfile and fresh verification.

## 2. Choose the backend runtime you are actually using

### Managed Android / Termux / Ubuntu PRoot

The managed Android default API base is:

```text
http://127.0.0.1:8010
```

This is also the frontend fallback used by `frontend/src/api/client.js`. An operator-saved API URL remains authoritative, so another valid reachable backend can be used when deliberately configured.

For a direct local backend launch that should match the Android default:

```bash
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

For the physical Android managed runtime, use the repository's Termux/Ubuntu PRoot launcher and runtime acceptance procedures rather than replacing them with an ad-hoc foreground server.

### Docker Compose

Docker Compose intentionally exposes its backend on host port `8000`:

```bash
docker compose up -d db redis backend celery_worker celery_beat frontend
```

The Compose frontend is configured for `http://localhost:8000`. A physical phone cannot use the computer's `127.0.0.1` as though it were the computer, so configure the app's API connection control to a backend address that is actually reachable from that device when using a separate host.

### CORS

CORS is explicit and credential-compatible. Wildcards are rejected. The development defaults include the local web and Capacitor origins defined by `CORS_ORIGINS` in `.env.example`.

If a deliberate deployment introduces another browser origin, add that exact origin to `CORS_ORIGINS`. Do not replace the list with `*`.

## 3. Prepare the Android project

From the frontend directory:

```bash
cd frontend
npm ci
npm run android:prepare
```

`android:prepare` builds the React frontend and synchronizes the generated web assets into the existing Capacitor Android project.

The root helper performs the same preparation with the canonical dependency install:

```bash
./build-apk.sh
```

The helper prepares the Android project and prints the available assembly commands. It does not publish anything.

## 4. Build and verify a development APK

The repository's standard debug path is:

```bash
cd frontend
npm run build:apk:debug
```

Run Android lint with:

```bash
npm run android:lint
```

The debug APK is produced at:

```text
frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

A connected-device development install can use:

```bash
adb install -r frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

For a release candidate, prefer the repository CI workflow rather than treating a locally assembled debug APK as publishable evidence.

## 5. Build a release variant locally when needed

Release signing material is never stored in source control. `frontend/android/app/build.gradle` accepts these environment variables:

```text
JOBTOMATIK_KEYSTORE_PATH
JOBTOMATIK_KEYSTORE_PASSWORD
JOBTOMATIK_KEY_ALIAS
JOBTOMATIK_KEY_PASSWORD
```

With valid signing material configured outside the repository:

```bash
cd frontend
npm ci
npm run build:apk:release
```

The release output is under:

```text
frontend/android/app/build/outputs/apk/release/
```

If signing variables are absent, do not describe the result as `release_signed`. The release tooling distinguishes `release_signed` from `development_signed` and records the actual signing mode.

## 6. Android Studio

To inspect or build the already prepared project in Android Studio:

```bash
cd frontend
npm run android:open
```

The command builds and synchronizes the frontend before opening the Android project.

## 7. Exact v2 release candidate

The final publishable candidate is evidence-bound, not whichever APK happens to be newest on a workstation.

The release flow is:

1. freeze the exact source revision after the required Day 41 evidence is complete;
2. run `.github/workflows/build-v2-release-candidate.yml` on that exact source;
3. retain the candidate workflow run ID, source revision, APK SHA-256, signing mode, and candidate metadata;
4. pass the Day 42 publication-readiness evaluator against that exact candidate;
5. provide the owner authorization bound to the exact source, exact APK hash, and exact candidate workflow run;
6. let the owner-only publisher download and verify that exact prebuilt artifact without rebuilding it.

A passing PR build, debug APK, or manually assembled release variant does not substitute for this chain.

## Troubleshooting

### Cannot reach backend API

- Managed Android defaults to `http://127.0.0.1:8010` on the same Android device.
- Docker Compose uses host port `8000`.
- If the backend is on another machine, configure a reachable address rather than that machine's loopback address.
- Confirm the backend health endpoint before debugging the APK.

### Cleartext HTTP

The current Android development/local runtime permits cleartext traffic because the managed local backend is HTTP. Public production deployments should use HTTPS and must still pass the release security and configuration gates. Do not weaken unrelated network or CORS controls to work around a connectivity mistake.

### CORS error

Do not enable wildcard CORS. Add only the exact required origin to `CORS_ORIGINS` and keep the existing Capacitor/local origins that the deployment needs.

### White screen or stale frontend assets

```bash
cd frontend
npm run android:prepare
```

Then rebuild the desired APK variant.

### Android SDK or Java mismatch

Re-check `.jobtomatik-toolchain.env`. The current verified contract is Java 21, Android API 35, and Android build tools 35.0.0.

### Release signing failure

Verify that all four `JOBTOMATIK_KEYSTORE_*` / key variables are supplied from secure external storage and point to the intended signing identity. Never commit a keystore or password to make a local build pass.

# JobTomatik Verification Guide

JobTomatik uses one verification entry point for local work and CI:

```bash
bash scripts/verify.sh <mode>
```

The canonical versions are stored in `.jobtomatik-toolchain.env`. The script fails early when Python, Node, Java, Gradle, Android Gradle Plugin, or Android SDK expectations drift.

## Clean checkout

Install dependencies once:

```bash
bash scripts/verify.sh bootstrap
```

The bootstrap mode installs:

- Python dependencies from `backend/requirements.txt`;
- Playwright Chromium;
- frontend dependencies through `npm ci`.

Android SDK packages and Docker remain host-level prerequisites.

## Modes

| Mode | Purpose |
|---|---|
| `toolchain` | Validate and print canonical toolchain versions |
| `fast` | Compile backend, run focused safety tests, run frontend runtime tests, verify maturity and fail-safe defaults |
| `backend-tests` | Run the complete backend and browser test suite while retaining a pytest report |
| `migration` | Run the Alembic migration smoke test only |
| `safety` | Verify all live gates are disabled and adapter maturity remains canonical |
| `backend` | Run backend tests, migration smoke test, and safety manifest |
| `frontend` | Run frontend tests and production build |
| `deployment` | Render Docker Compose and verify fail-safe defaults |
| `android` | Prepare Capacitor, run Gradle lint and assembly, and verify APK identity/version |
| `full` | Run all subsystem gates in deterministic dependency order |

Install dependencies immediately before any mode with `--install`:

```bash
bash scripts/verify.sh full --install
```

## Safety behaviour

The verification process globally disables real submission, scheduled autopilot, and live resumable handoffs:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
AUTOPILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
```

Platform pilot variables remain available to internal configuration regression tests, but the dedicated `safety` gate explicitly runs with both Greenhouse and Lever pilot flags set to `false` and verifies their resolved settings. The outer real-submission gate remains disabled throughout the test suite.

Verification never issues approvals, opens a real-submission path, promotes adapter maturity, or clicks final submit.

## CI topology

`.github/workflows/reproducible-verification.yml` runs independent lanes for:

1. fast pre-commit checks;
2. full backend, browser, migration, and safety checks;
3. frontend tests and production build;
4. deployment configuration;
5. Android lint, build, and APK verification.

The backend lane uploads `verification-pytest-output.txt` on success or failure. The release-gate job passes only when every lane succeeds.

## Canonical toolchain

- Python 3.11
- Node.js 20
- Temurin Java 21
- Gradle 9.5.1
- Android Gradle Plugin 8.13.2
- Android API 35
- Android Build Tools 35.0.0

Update `.jobtomatik-toolchain.env`, the affected repository configuration, tests, documentation, and CI in the same pull request when intentionally changing any version.

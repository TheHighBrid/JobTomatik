# JobTomatik v1.00 Final Audit

Date: 2026-07-21

## Release decision

JobTomatik v1.00 is approved for **supervised local use** after all required CI gates pass. It is not approved for autonomous real submission.

## Audit scope

- backend API, configuration, state transitions, evidence, and tests;
- Redis/Celery worker routing and Android/PRoot operation;
- retained-browser handoff lifecycle and confirmation reconciliation;
- React user interface and completed-application controls;
- Capacitor Android project, Gradle wrapper, signing, lint, and APK assembly;
- Docker configuration;
- secret handling, CORS, backups, and release artifacts;
- installation, operation, recovery, and upgrade documentation.

## Material findings corrected

| Finding | Severity | Resolution |
|---|---:|---|
| Gradle wrapper referenced `/tmp/gradle-8.11.1-all.zip` | High | Replaced with validated official Gradle 8.11.1 distribution URL |
| Public Gradle file contained a machine path and signing passwords | Critical | Removed; signing now comes from environment variables or private Gradle properties |
| `build:apk` never assembled an APK | High | Added debug/release assembly and lint scripts |
| Android package and project versions were inconsistent | Medium | Canonicalized to `1.0.0`, Android version code `100` |
| Android app backups were enabled for applicant-facing client data | Medium | Disabled application backup |
| Credentialed CORS accepted every origin | High | Replaced wildcard with explicit browser and Capacitor defaults plus environment override |
| Backend default sender leaked a separate project identity | Low | Replaced with `noreply@jobtomatik.com` |
| Docker worker listened to `default` instead of the canonical `celery` queue | Medium | Aligned queue list with runtime configuration |
| Confirmed application pages still exposed new submission controls | High | Hidden Dry Run, direct submit, supervised submit, and stale handoff controls after submission |
| Repository lacked a complete installation and recovery guide | High | Added `docs/SETUP_TUTORIAL.md` |
| Repository lacked Android build and release automation | High | Added APK CI plus the v1 release workflow |

## Safety invariants retained

- `ALLOW_REAL_APPLICATION_SUBMIT=false` by default.
- `GREENHOUSE_SUPERVISED_PILOT_ENABLED=false` by default.
- `AUTOPILOT_ENABLED=false` by default.
- No ATS adapter is `certified_autonomous`.
- CAPTCHA, anti-bot, login, MFA, assessment, identity, legal ambiguity, and unsupported controls remain human-review boundaries.
- Employer confirmation evidence is required before automatic submitted/confirmed reconciliation.
- Android signing keys and passwords are excluded from source control.

## Required release gates

The release branch must pass:

1. full backend pytest suite;
2. Python compilation;
3. Alembic migration smoke test;
4. retained-browser certification;
5. frontend production build;
6. Docker Compose validation and fail-safe flag checks;
7. Android Gradle wrapper validation;
8. Android `lintDebug`;
9. Android APK assembly;
10. APK package, version code, and version name inspection;
11. SHA-256 generation for the final asset.

## Accepted boundaries for v1.00

- The APK is a client and requires a running backend, Redis, and Celery worker.
- Local cleartext HTTP is permitted for `127.0.0.1:8010`; remote deployments must use HTTPS.
- A development-signed CI APK may require uninstall/reinstall when permanent signing is introduced.
- Docker is suitable for core services, but local-CDP handoff affinity is best supported by the single-node Android/Ubuntu reference setup.
- Public job-source scraping remains best effort and every posting must be verified at its original source.

## Operator checklist

- Preserve `.env`, database, uploads, and signing-key backups.
- Run Celery with `--pool=solo` on Android/PRoot.
- Keep Redis running before starting Celery.
- Use the exact API base URL without `/api`.
- Review Answer Policy Vault entries for truthfulness before every new employer workflow.
- Do not repeat a confirmed application.
- Read release `BUILD-INFO.txt` before installing an APK update.

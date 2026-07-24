# Changelog

All notable JobTomatik changes are recorded here.

## [Unreleased]

### Product direction

- Declared fully autonomous, evidence-backed real submission as the final JobTomatik operating goal.
- Clarified that the supervised v1 workflow is a foundation and rollout stage, not the permanent product ceiling.
- Reframed real-submission, autopilot, and adapter-maturity controls as progressive release gates.
- Preserved confirmation evidence, duplicate prevention, idempotency, circuit breakers, caps, and kill switches as safeguards for both supervised and autonomous operation.

## [1.0.0] - 2026-07-21

### Added

- Secure retained-browser handoffs for CAPTCHA, anti-bot, login, and MFA boundaries.
- Browser-image interaction, secret-safe typing, lease recovery, and heartbeat renewal.
- Verification-code recovery controls: request new code, go back, reload, start over, and replace-and-submit.
- Explicit Greenhouse confirmation-page detection using final URL and employer success text.
- Submission evidence recording and automatic `submitted` → `confirmed` state reconciliation.
- Answer Policy Vault with encrypted reusable answers and exact-option verification.
- Deterministic custom-question policies for company-specific application fields.
- Greenhouse supervised-submission preflight, payload hashing, and one-time approval records.
- Adapter health metrics, operational alerts, application events, and evidence review tools.
- Android Capacitor client with local backend URL configuration.
- Portable Android CI and release build automation.
- Complete Android/Termux/Ubuntu setup tutorial.

### Changed

- Confirmed applications no longer display new Dry Run or submit controls.
- Greenhouse confirmation evidence now overrides a vanished CAPTCHA response field.
- Android version is standardized as `1.0.0` with version code `100`.
- The Gradle wrapper now downloads from the official Gradle distribution service.
- CORS defaults are restricted to documented browser and Capacitor origins.
- Android application backups are disabled to reduce exposure of local applicant data.
- The Android APK scripts now run Gradle assembly instead of stopping after Capacitor synchronization.

### Fixed

- Handoff sessions not appearing after CAPTCHA detection.
- Stale terminal handoff records blocking later retained sessions.
- Celery startup-hook dependence in Android/PRoot environments.
- CAPTCHA boundaries being lost when another review item was returned first.
- Verification codes being appended to expired values.
- Confirmation pages being incorrectly reported as active human-verification challenges.
- Local-only Gradle wrapper and keystore paths preventing reproducible Android builds.

### Security and operating controls

- Removed committed Android signing passwords and machine-specific keystore paths.
- Release signing now uses environment variables or private Gradle properties.
- Expanded ignore rules for APKs, AABs, keystores, certificates, and local signing configuration.
- Established conservative development defaults for real submission, supervised pilots, and unattended automation while certification progresses.
- Preserved fail-closed behavior for unsupported controls, uncertain confirmation, and explicit human-verification boundaries.

### Current v1 maturity

- The Android APK is a client and requires a running JobTomatik backend, Redis, and Celery worker.
- Greenhouse, Lever, and Ashby are currently at `dry_run` maturity.
- SmartRecruiters and Workday are currently at `detect_only`.
- Adapter promotion continues through `human_reviewed_submit` toward `certified_autonomous`.
- A development-signed CI APK may require reinstalling when moving to a permanently signed build.

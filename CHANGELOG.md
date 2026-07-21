# Changelog

All notable JobTomatik changes are recorded here.

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

### Security

- Removed committed Android signing passwords and machine-specific keystore paths.
- Release signing now uses environment variables or private Gradle properties.
- Expanded ignore rules for APKs, AABs, keystores, certificates, and local signing configuration.
- Kept real submission, supervised pilots, and unattended automation disabled by default.
- Preserved fail-closed behavior for unsupported controls, uncertain confirmation, and human-verification boundaries.

### Known boundaries

- The Android APK is a client and requires a running JobTomatik backend, Redis, and Celery worker.
- Greenhouse, Lever, and Ashby remain at `dry_run` maturity.
- SmartRecruiters and Workday remain `detect_only`.
- No adapter is certified for autonomous submission in v1.00.
- A development-signed CI APK may require reinstalling when moving to a permanently signed build.

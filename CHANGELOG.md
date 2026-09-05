# Changelog

All notable JobTomatik changes are recorded here.

## [Unreleased]

No unreleased changes are currently separated from the `2.1.0` candidate lineage.

## [2.1.0] - candidate

### Reliability and supervised submission

- Hardened Lever operator-assisted final submission after the physical Maple pilot.
- Detect passive hCaptcha verification without attempting to solve or bypass it, and require normal-browser completion when a retained CDP submit cannot be verified safely.
- Preserved emergency-stop and runtime safety ordering before any retained-browser final action.
- Added fail-closed reentrancy protection around final-submit confirmation verification so a wrapper cycle cannot exhaust the Python stack after a consequential action.
- Preserved exact target verification, explicit owner authorization, durable final-action claiming, confirmation evidence, and no-automatic-retry behavior after uncertain consequential actions.

### Release identity and Android

- Set the canonical JobTomatik product candidate to `2.1.0`.
- Set Android application identity to version name `2.1.0` and version code `210` for `ca.jobtomatik.app`.
- Expose `2.1.0` consistently through backend metadata, health, readiness, certification defaults, and current operator documentation.
- Keep the private frontend npm package version independent at `1.0.0`; it remains an implementation manifest rather than the shipped product version.
- Make the normal Android APK workflow build-only with read-only repository permissions.
- Verify APK application ID, version code, version name, source commit, and SHA-256 before retaining the build artifact.

### Publication safety

- Preserve the historical `v2.0.0` release as immutable rather than reusing or overwriting its tag or assets.
- Reserve `v2.1.0` as the successor release identity.
- Require an explicit owner command on the narrow release-authorization surface before public `v2.1.0` publication can begin.
- Freeze one exact `main` source SHA before the owner-authorized release build, record it in release evidence, and refuse publication if `main` moves before the release is created.
- Refuse to overwrite an existing `v2.1.0` tag or GitHub Release and keep release asset overwrite disabled.
- Keep release publication separate from merge, normal APK CI, certification readiness, runtime submission authority, and autopilot enablement.

### Certification and operations

- Bind the current Certification Center, certification API default, release-track evaluator, owner acknowledgment phrases, and Phase 10 runbook to immutable release identity `v2.1.0`.
- Align Phase 12 runtime-attestation documentation with build-only APK CI and exact-source owner-authorized publication.
- Add regression coverage preventing current operator, certification, Android, and release-provenance surfaces from drifting back to older release identities.
- Preserve exact-head evidence, independent review, account isolation, runtime attestation, kill switches, and conservative consequential-action defaults.

## [1.0.0] - 2026-07-21

### Product direction

- Declared fully autonomous, evidence-backed real submission as the final JobTomatik operating goal.
- Clarified that the supervised v1 workflow is a foundation and rollout stage, not the permanent product ceiling.
- Reframed real-submission, autopilot, and adapter-maturity controls as progressive release gates.
- Preserved confirmation evidence, duplicate prevention, idempotency, circuit breakers, caps, and kill switches as safeguards for both supervised and autonomous operation.

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

# Changelog

All notable JobTomatik changes are recorded here.

## [Unreleased]

Changes after the v2.0.0 release candidate belong here. Do not move a change into the v2.0.0 entry unless it is present on the exact tagged release commit.

## [2.0.0]

**Release state:** publication is exact-artifact and evidence gated. This changelog entry describes the v2.0.0 release contract; the GitHub release exists only after the Day 41 audit, Day 42 readiness report, and owner-only publisher complete successfully on the exact release commit.

### Bounded autonomy

- Added policy-bounded unattended job discovery, queue prioritization, application scheduling, and recovery.
- Added rolling application caps, quiet hours, employer/platform exclusions, rate limits, and circuit-breaker enforcement.
- Added exact adapter-maturity checks so unattended real submission is available only to an adapter with retained `certified_autonomous` evidence on the exact release lineage.
- Kept real follow-up sending independently gated from application submission.
- Preserved fail-closed human handoffs for CAPTCHA, MFA, identity checks, assessments, ambiguous required questions, and missing approved applicant answers.

### Submission safety and evidence

- Hardened application state transitions and terminal-state evidence requirements.
- Expanded durable idempotency and duplicate protection across queue replay, retries, worker restarts, and canonical posting identity.
- Bound consequential submission attempts to exact applicant, posting, adapter/version, documents, answer set, runtime revision, and authorization context.
- Required strong employer confirmation before recording successful submitted/confirmed states.
- Preserved `submission_uncertain` for ambiguous final outcomes and prohibited silent automatic retry.
- Added durable non-reclaiming live-attempt reservations so uncertain browser outcomes cannot replenish an attempt budget.

### Adapter certification and live authorization

- Added strict exact-head post-shadow promotion contracts.
- Added bounded owner-authorized live windows with exact adapter, adapter version, runtime revision, validity window, and attempt-cap binding.
- Added worker-side revalidation before consequential browser work.
- Added Day 40 second-wave continuation/certification requirements for zero duplicate and false-positive submission states, queue prioritization, cap enforcement, follow-up scheduling, and evidence reconciliation.
- Planned v2.0.0 scope keeps Greenhouse and Ashby at `dry_run`, SmartRecruiters and Workday at `detect_only`, and permits Lever 1.1.0 to reach `certified_autonomous` only when the strict retained promotion evidence passes.

### Android runtime reliability

- Added exact managed-runtime revision attestation covering API, worker, Beat, frontend, application queue, Redis, and Chromium/CDP state.
- Hardened Android process cleanup against stale/recycled PIDs and unrelated Termux process termination.
- Hardened Celery worker/Beat lifetime and queue ownership checks.
- Added deterministic Android runtime dispatch acceptance and current-head end-to-end acceptance gates.
- Added physical long-duration Android shadow campaigns with retained runtime identity, memory/process telemetry, evidence hashes, and strict post-run certification.

### Shadow endurance and policy verification

- Added staged physical shadow endurance certification, including 8-hour and 24-hour campaigns.
- Added diagnostic production-policy telemetry during shadow execution without allowing diagnostic production state to authorize or block the shadow scheduler.
- Corrected Day 38 daily-cap verification to the actual rolling previous-24-hour semantics instead of a false UTC-midnight reset assumption.
- Added quiet-hour transition, rolling-window membership rollover, continuous-cycle coverage, worker stability, policy-escape, retry, duplicate, and evidence-integrity gates.
- Prevented CI fixtures or elapsed calendar dates from substituting for genuine physical-runtime evidence.

### Release, recovery, and compatibility

- Added strict Day 41 release-candidate audit requirements for data, security, privacy, dependencies, migrations, Android identity, release provenance, and secret scanning.
- Added non-destructive SQLite backup/restore verification that opens the source database read-only and validates a separate restored copy.
- Added frozen-v1 database migration compatibility verification using isolated checkouts, isolated dependencies, a temporary SQLite database, and synthetic sentinel data.
- Added rollback and kill-switch evidence requirements to the release dossier.
- Added v2.00 known-boundaries, operator, release-note, and evidence-bound checklist documentation.

### Exact-artifact Android release provenance

- Made pull-request Android APK builds read-only and incapable of publishing a release.
- Added an owner-triggered exact-current-main candidate builder that creates one prepublication APK and records its source commit, SHA-256, signing identity, Day 41 audit reference, and candidate workflow run ID.
- Added a read-only Day 42 publication-readiness evaluator bound to the exact candidate, exact release matrix, maturity manifest, repository state, release documents, and owner approval.
- The publisher downloads and verifies the approved prebuilt candidate, then publishes those exact bytes rather than rebuilding the APK after approval.
- Bound final publication to exact source commit, exact APK SHA-256, exact candidate workflow run ID, and retained Day 42 readiness SHA-256.
- Added immutable `v2.0.0` tag checks, exact-SHA `target_commitish`, release-asset overwrite refusal, source-commit metadata, APK badging, signing-certificate output, and candidate metadata retention.

### Android identity

- Android application ID: `ca.jobtomatik.app`.
- Android version name: `2.0.0`.
- Android version code: `200`.
- Final signing mode must be reported truthfully as `release_signed` or `development_signed`.

### Operating boundaries

- Autonomous submission remains bounded by production caps, quiet hours, exclusions, circuit breakers, duplicate prevention, current runtime identity, approved answer policy, and any required live-window authorization.
- Publication itself never promotes adapter maturity or enables real application/follow-up flags.
- JobTomatik does not bypass third-party CAPTCHA, MFA, anti-bot, identity, or assessment controls.

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
- Release signing uses environment variables or private Gradle properties.
- Expanded ignore rules for APKs, AABs, keystores, certificates, and local signing configuration.
- Established conservative development defaults for real submission, supervised pilots, and unattended automation while certification progresses.
- Preserved fail-closed behavior for unsupported controls, uncertain confirmation, and explicit human-verification boundaries.

### v1 maturity

- The Android APK is a client and requires a running JobTomatik backend, Redis, and Celery worker.
- Greenhouse, Lever, and Ashby were released at `dry_run` maturity.
- SmartRecruiters and Workday were released at `detect_only`.
- Adapter promotion continues through retained certification evidence rather than release documentation alone.

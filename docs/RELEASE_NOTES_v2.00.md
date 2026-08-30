# JobTomatik v2.00 Release Notes

> **Pre-release document.** This file is prepared ahead of the final release audit. It must not be represented as a published v2.00 release until the Day 41 audit, Day 42 exact-artifact readiness gate, and owner publication action have all completed successfully.

JobTomatik v2.00 is the bounded-autonomy release. It extends the supervised v1 foundation with durable policy enforcement, evidence-backed autonomous scheduling, exact runtime attestation, long-duration shadow certification, bounded live-pilot controls, and an exact-artifact Android release path.

## Release scope

The release contract permits autonomous real submission only for adapters that have independently reached `certified_autonomous` on the exact release commit. The planned v2.00 maturity scope is:

| Adapter | Version | Release maturity | Autonomous real submission |
| --- | --- | --- | --- |
| Lever | 1.1.0 | `certified_autonomous` only after the retained Day 39 promotion gate passes | Bounded by production policy and active live authorization |
| Greenhouse | 1.1.1 | `dry_run` | No |
| Ashby | 1.1.0 | `dry_run` | No |
| SmartRecruiters | 1.1.0 | `detect_only` | No |
| Workday | 1.1.0 | `detect_only` | No |

If the Lever promotion gate has not passed on the final exact release commit, the release documents and maturity manifest must be revised before publication. Publication itself never promotes adapter maturity.

## What changed since v1.00

### Bounded autonomous operation

- Added policy-bounded unattended scheduling with application caps, quiet hours, exclusion rules, rate limits, and circuit-breaker enforcement.
- Added continuous discovery, queue prioritization, recovery, notification, and follow-up planning under explicit runtime policy profiles.
- Preserved fail-closed behavior for CAPTCHA, MFA, identity verification, assessments, ambiguous required questions, uncertain confirmation, and missing approved answers.
- Kept real follow-up sending separately gated from application submission.

### Submission safety and evidence

- Strengthened application-state transitions and rejection of unsupported direct terminal-state writes.
- Added durable idempotency and duplicate-submission protections across retries, worker restarts, queue replay, and canonical posting identity.
- Bound consequential attempts to exact applicant, posting, adapter, documents, answers, runtime revision, and authorization context.
- Required strong employer evidence before a successful application may be represented as submitted or confirmed.
- Preserved `submission_uncertain` as a fail-closed state when confirmation cannot be proven.

### Runtime and Android reliability

- Added exact runtime-revision attestation for API, worker, Beat, frontend, browser, queue, and Android-managed process identity.
- Hardened Android process cleanup against stale/recycled PIDs and unrelated Termux process termination.
- Hardened worker/Beat lifetime management and Android Redis queue ownership.
- Added deterministic Android runtime acceptance and current-head end-to-end acceptance gates.
- Added long-duration physical Android shadow certification with retained hashes and exact runtime identity.

### Shadow and promotion certification

- Added staged shadow campaigns, including strict multi-hour and 24-hour endurance evidence.
- Added policy-transition telemetry for quiet-hour and rolling previous-24-hour production-cap behavior without allowing diagnostic production policy to control shadow execution.
- Added exact-head post-shadow promotion contracts that cannot be satisfied by synthetic CI fixtures alone.
- Added bounded live-window authorization with durable, non-reclaiming attempt reservations and exact runtime/adapter binding.
- Added second-wave live-pilot admission and certification gates requiring zero duplicate or false submission states.

### Release and recovery hardening

- Added non-destructive SQLite backup/restore verification for the release audit.
- Added frozen-v1 database migration compatibility verification using synthetic data and isolated databases.
- Added rollback, kill-switch, dependency, migration, privacy, security, and previous-release compatibility requirements to the Day 41 release dossier.
- Split Android release publication into an exact-commit candidate build, read-only Day 42 readiness gate, and owner-only exact-artifact publisher.
- The final publisher downloads and verifies the approved prebuilt APK rather than rebuilding after approval.
- Release publication is bound to exact source commit, exact APK SHA-256, exact candidate workflow run, and retained Day 42 readiness hash.

## Android artifact

JobTomatik v2.00 uses:

- application ID: `ca.jobtomatik.app`
- version name: `2.0.0`
- version code: `200`
- target Android SDK: `35`

Every final release bundle must retain:

- `JobTomatik-v2.00.apk`
- `JobTomatik-v2.00.sha256`
- `SOURCE-COMMIT.txt`
- `BUILD-INFO.txt`
- `APK-BADGING.txt`
- `APK-SIGNING.txt`
- `CANDIDATE-METADATA.json`
- `DAY42-READINESS-SHA256.txt`

The signing mode must be labeled truthfully as either `release_signed` or `development_signed`.

## Important operating boundaries

JobTomatik does not bypass CAPTCHA, MFA, identity verification, anti-bot challenges, assessments, or other third-party security controls. It pauses when a human action is genuinely required and resumes only when the retained session remains valid.

Autonomous submission does not mean unrestricted submission. Real attempts remain subject to adapter certification, active authorization, production caps, quiet hours, employer exclusions, approved answer policies, circuit breakers, duplicate protection, and strong confirmation evidence.

See `docs/KNOWN_BOUNDARIES_v2.00.md` for the complete release boundary and `docs/OPERATOR_GUIDE_v2.00.md` for operating procedures.

## Upgrade notes

- Review the release `BUILD-INFO.txt` and `APK-SIGNING.txt` before installing.
- A development-signed APK may not upgrade in place over an APK signed with a different key.
- Preserve the JobTomatik database and evidence ledger during application rollback.
- Run migrations against a backup or copy before any attempted schema downgrade.
- Do not reuse a stale live-pilot authorization after upgrading to a different runtime commit.

## Publication proof

The final GitHub release is valid only when the `v2.0.0` tag, release target commit, APK source commit, candidate metadata, APK SHA-256, signing identity, Day 42 readiness report, README/CHANGELOG scope, and maturity manifest all resolve to the same audited release state.

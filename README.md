# JobTomatik v2.00

**A bounded-autonomy job-search and application system with evidence-backed submission, fail-closed recovery, and exact-artifact release controls.**

> **Release-candidate source.** The repository can contain v2.00 candidate code before the `v2.0.0` GitHub release exists. A published v2.00 release is valid only after the Day 41 release audit, Day 42 exact-artifact readiness gate, owner publication authorization, and immutable `v2.0.0` release all pass on the same exact source revision.

JobTomatik discovers and ranks jobs, prepares truthful application materials, resolves employer/ATS targets, fills supported forms, preserves retained-browser handoffs, records submission evidence, prevents duplicate attempts, schedules policy-bounded work, and tracks follow-up activity.

## Bounded autonomy

JobTomatik v2.00 is designed for hands-off operation where the exact adapter, runtime, policy, and retained certification evidence permit it. Autonomous operation remains bounded by:

- adapter maturity and exact adapter version;
- approved applicant profile and answer policies;
- exact runtime revision;
- duplicate and idempotency protection;
- rolling application caps and quiet hours;
- employer/platform exclusions and rate limits;
- global and platform kill switches;
- circuit breakers;
- bounded live-window authorization when required;
- strong employer confirmation evidence;
- fail-closed handling of ambiguous or uncertain outcomes.

JobTomatik does not attempt to bypass CAPTCHA, MFA, anti-bot challenges, identity verification, assessments, or other third-party security controls. When a genuine human action is required, the system pauses and may resume only when the retained session remains valid and bound to the same target.

## v2.00 adapter scope

Adapter maturity is an operational certification state, not a marketing label:

```text
unsupported
→ detect_only
→ dry_run
→ human_reviewed_submit
→ certified_autonomous
```

The v2.00 release contract allows the following maximum scope:

| Adapter | Version | v2.00 release boundary | Autonomous real submission |
| --- | --- | --- | --- |
| Lever | 1.1.0 | `certified_autonomous` only after the strict retained Day 39 promotion gate passes on the exact release lineage | Only while current production policy and bounded live authorization permit it |
| Greenhouse | 1.1.1 | `dry_run` | No |
| Ashby | 1.1.0 | `dry_run` | No |
| SmartRecruiters | 1.1.0 | `detect_only` | No |
| Workday | 1.1.0 | `detect_only` | No |
| Generic sites | n/a | `unsupported` or manual handoff | No |

If final retained evidence supports a lower maturity, the lower maturity is authoritative and this table must be reconciled before publication. Publishing a release never promotes an adapter by itself.

## Core v2.00 capabilities

| Area | v2.00 capability |
| --- | --- |
| Authentication, profile, résumé | Applicant profile and document management |
| Job discovery and scoring | Continuous/public-source discovery with queue prioritization |
| Answer Policy Vault | Approved reusable answers with provenance and fail-closed ambiguity handling |
| Material preparation | Truthful tailored material generation from approved applicant data |
| Employer/ATS target resolution | Source listing separated from canonical employer application target |
| Retained browser handoff | CAPTCHA, MFA, login, identity, and other unavoidable human boundaries |
| Duplicate prevention | Durable canonical-target and idempotency controls across retries/restarts |
| Submission evidence | Strong employer evidence required before successful terminal state |
| Uncertain outcomes | `submission_uncertain` remains non-retryable until explicit review |
| Autonomy scheduler | Caps, quiet hours, exclusions, rate limits, circuit breakers, queue policy |
| Runtime attestation | Exact API/worker/Beat/frontend/browser/queue/runtime revision verification |
| Shadow certification | Strict physical Android endurance evidence, including 24-hour policy transitions |
| Live authorization | Exact-revision, exact-adapter, bounded, durable authorization and attempt reservation |
| Follow-up planning | Scheduling and review independently gated from real outbound sending |
| Release provenance | Exact-commit prebuilt APK candidate and owner-only exact-artifact publisher |

## Architecture

```text
Android / Browser UI
        │
        ▼
React + Capacitor client
        │  HTTP API
        ▼
FastAPI backend ─── SQLite/PostgreSQL
        │
        ├── Redis
        ├── Celery worker + Beat
        └── Playwright / Chromium retained-browser runtime
```

Application-target flow:

```text
source listing
→ canonical target resolution
→ employer / ATS application target
→ certified adapter or bounded browser agent
→ confirmation evidence
→ audited application state
```

## Android runtime

The reference Android execution model uses Termux plus Ubuntu PRoot. The canonical managed backend checkout is `/root/JobTomatik` inside Ubuntu PRoot. Do not treat a second native Termux checkout as the authoritative backend runtime.

The installed Android client normally talks to:

```text
http://127.0.0.1:8010
```

The complete setup guide is in [docs/SETUP_TUTORIAL.md](docs/SETUP_TUTORIAL.md).

### Managed backend shell

```bash
proot-distro login ubuntu --shared-tmp
cd /root/JobTomatik/backend
source .venv/bin/activate
```

Use the repository's managed Android stack and runtime-acceptance commands for normal startup and certification. Manual process commands are primarily for diagnosis because runtime admission depends on exact process identity, queue ownership, browser/CDP state, and source-revision attestation.

## Runtime safety rules

A successful frontend build or reachable API is not enough to authorize unattended work. Relevant release/campaign gates may require verification of:

- API process identity;
- Celery worker identity and application queue ownership;
- Celery Beat identity;
- Redis application database/queue behavior;
- frontend source revision;
- Chromium/CDP availability;
- managed Android runtime fingerprint;
- exact source revision;
- no stale/foreign PID ownership;
- no live safety switch escape.

A runtime acceptance receipt from an older source revision is stale after an update.

## Submission safety

A click is not a submission result. JobTomatik records a successful submission only after accepted confirmation evidence.

When evidence is missing or ambiguous:

- the application remains fail closed;
- an uncertain live attempt is not silently retried;
- a consumed or reserved authorization slot is not automatically reclaimed;
- duplicate protection remains active;
- operator review must reconcile employer-side evidence before state changes.

Never manually convert an uncertain application into a retryable state merely to restore throughput.

## Human-review boundaries

JobTomatik pauses rather than guessing when it encounters:

- CAPTCHA or anti-bot challenge;
- MFA or applicant-controlled verification code;
- identity/document verification;
- employer assessment;
- ambiguous required control;
- missing sensitive/legal answer policy;
- conflicting applicant data;
- unsupported required form state;
- uncertain employer confirmation.

See [docs/KNOWN_BOUNDARIES_v2.00.md](docs/KNOWN_BOUNDARIES_v2.00.md) for the complete release boundary.

## Production controls

Conservative defaults remain important even in a bounded-autonomy release:

```env
ALLOW_REAL_APPLICATION_SUBMIT=false
ALLOW_REAL_FOLLOWUP_SEND=false
AUTOPILOT_ENABLED=false
DEV_MOCK_JOBS=false
```

Real submission authority is not derived from one environment variable. The active adapter maturity, runtime identity, production policy, kill-switch state, circuit breakers, and any required persisted live authorization are independently revalidated.

Real follow-up sending is separately gated from application submission.

## Verification

The canonical toolchain is declared in `.jobtomatik-toolchain.env` and enforced by `scripts/verify.sh`.

Bootstrap a clean checkout:

```bash
bash scripts/verify.sh bootstrap
```

Fast gate:

```bash
bash scripts/verify.sh fast
```

Subsystem gates:

```bash
bash scripts/verify.sh backend
bash scripts/verify.sh frontend
bash scripts/verify.sh dependencies
bash scripts/verify.sh deployment
bash scripts/verify.sh android
```

Full deterministic verification:

```bash
bash scripts/verify.sh full
```

The canonical release toolchain uses Python 3.11, Node.js 20, Temurin Java 21, Gradle 9.5.1, Android Gradle Plugin 8.13.2, Android API 35, and Build Tools 35.0.0.

## v2.00 release process

The final Android release deliberately separates build, readiness, and publication.

### 1. Exact-commit candidate build

`.github/workflows/build-v2-release-candidate.yml` builds one prepublication candidate from an exact current `main` commit and records:

- APK SHA-256;
- source commit;
- APK package/version identity;
- signing certificate identity;
- canonical signing mode (`release_signed` or `development_signed`);
- Day 41 audit reference;
- candidate workflow run ID;
- `publication_authorized=false`.

It cannot publish a GitHub release.

### 2. Day 42 read-only readiness

The Day 42 evaluator binds the exact candidate to:

- strict Day 41 audit;
- final exact-head workflow matrix;
- truthful maturity manifest;
- current repository/tag state;
- final release documents;
- separate owner authorization for the exact source commit, APK SHA-256, and candidate run ID.

A passing report may set `publication_eligible=true`; it still records that publication has not occurred.

### 3. Owner-only exact-artifact publication

`.github/workflows/publish-v1-command.yml` downloads the exact prebuilt candidate from the approved workflow run, verifies its bytes and provenance, rechecks `main` and immutable tag state, and publishes those exact bytes.

The publisher does **not** rebuild the APK after owner approval.

Final release bundle:

```text
JobTomatik-v2.00.apk
JobTomatik-v2.00.sha256
SOURCE-COMMIT.txt
BUILD-INFO.txt
APK-BADGING.txt
APK-SIGNING.txt
CANDIDATE-METADATA.json
DAY42-READINESS-SHA256.txt
```

See [docs/operations/DAY_42_V2_RELEASE.md](docs/operations/DAY_42_V2_RELEASE.md) and [docs/RELEASE_CHECKLIST_v2.00.md](docs/RELEASE_CHECKLIST_v2.00.md).

## Download and signing verification

Use the repository **Releases** page for published artifacts:

- https://github.com/TheHighBrid/JobTomatik/releases

For v2.00, verify that tag `v2.0.0`, release target commit, `SOURCE-COMMIT.txt`, APK checksum, candidate workflow metadata, and signing certificate all agree before installing.

A `development_signed` APK is valid only when described as development-signed. An APK signed by a different key may not upgrade in place over an existing installation.

## Operations and recovery

Primary operating documents:

- [v2.00 operator guide](docs/OPERATOR_GUIDE_v2.00.md)
- [v2.00 known boundaries](docs/KNOWN_BOUNDARIES_v2.00.md)
- [recovery and incident response](docs/operations/recovery-incident-response.md)
- [Day 41 release audit](docs/operations/DAY_41_RELEASE_CANDIDATE_AUDIT.md)
- [Day 42 release procedure](docs/operations/DAY_42_V2_RELEASE.md)

For a suspected duplicate, wrong target, unexpected live submission, guessed required answer, policy escape, or critical clustered defect, disable real submission and autopilot first, preserve evidence, and follow the incident runbook. Do not delete application state or evidence as part of containment.

## Docker development start

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

Local-CDP retained-browser handoffs require the API and browser worker to share reachable session affinity. The managed Android/Ubuntu single-node runtime is the reference physical certification environment.

## Android APK development build

```bash
cd frontend
npm ci
npm run build:apk:debug
```

A release build requires signing material supplied outside source control:

```bash
export JOBTOMATIK_KEYSTORE_PATH=/secure/path/jobtomatik-release.jks
export JOBTOMATIK_KEYSTORE_PASSWORD='...'
export JOBTOMATIK_KEY_ALIAS='jobtomatik'
export JOBTOMATIK_KEY_PASSWORD='...'
npm run build:apk:release
```

No private keystore, signing key, or signing password belongs in the repository.

## Repository guide

```text
backend/                         FastAPI, Celery, policies, evidence, migrations, tests
frontend/                        React client and Capacitor Android project
scripts/verify.sh                Canonical local/CI verification entry point
docs/SETUP_TUTORIAL.md           Installation guide
docs/OPERATOR_GUIDE_v2.00.md     v2 operator procedures
docs/KNOWN_BOUNDARIES_v2.00.md   v2 operating limits
docs/RELEASE_NOTES_v2.00.md      v2 release notes
docs/RELEASE_CHECKLIST_v2.00.md  Evidence-bound release checklist
evidence/                        Certification and campaign evidence
.github/workflows/               CI, runtime, candidate-build, and release automation
CHANGELOG.md                      Version history
SECURITY.md                       Security and secret-handling policy
```

## API reference

Interactive OpenAPI documentation is available at `/docs` on the running backend. Common routes include authentication/profile, job discovery, application state, handoffs, evidence review, and operations readiness. Runtime and promotion endpoints remain bounded by their exact gate contracts rather than README instructions.

## Release history

See [CHANGELOG.md](CHANGELOG.md).

JobTomatik v1.00 established the supervised retained-browser and evidence foundation. JobTomatik v2.00 adds bounded-autonomy scheduling, stronger exact-revision runtime safety, physical shadow certification, bounded live authorization, and exact-artifact release provenance.

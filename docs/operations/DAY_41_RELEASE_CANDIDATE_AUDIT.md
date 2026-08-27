# Day 41: Release Candidate Audit and Recovery Drill

Day 41 is an offline release-candidate audit. Live mode must be disabled before the audit begins and must remain disabled throughout it. A Day 41 pass makes one exact commit eligible for the Day 42 publication gate; it does not publish, tag, or re-enable live submission.

## Entry prerequisite

Day 40 must first produce a strict second-wave certification with:

- `passed=true`;
- `day41_entry_eligible=true`;
- exact release-candidate revision;
- retained report SHA-256;
- sustained zero duplicate submissions and zero false submitted states;
- the live window closed after the second wave;
- real application submission disabled after the wave;
- real follow-up sending disabled.

## Disable live mode first

Before collecting release-audit evidence, verify on the exact release candidate:

- no live-pilot authorization is active;
- `ALLOW_REAL_APPLICATION_SUBMIT=false`;
- `ALLOW_REAL_FOLLOWUP_SEND=false`;
- autopilot is disabled for the audit;
- the exact runtime revision is known and matches the release candidate.

Do not run a release audit against a moving runtime.

## Exact-head workflow matrix

The Day 41 dossier requires the release matrix to bind one exact 40-character commit as both `revision` and `current_head`. Required successful workflows include backend tests, stabilization, reproducible verification, CodeQL, current-head end-to-end acceptance, Android runtime dispatch, Android static frontend artifact, Android APK, certification/scale, submission-evidence certification, full-stack shadow campaigns, and the Day 39/40 tooling gates.

The Day 40 certification revision and Day 41 release-matrix revision must be identical. A code change after Day 40 requires the affected exact-head gates to be rerun and the release audit must bind the new commit truthfully.

## Data, security, privacy, dependencies, and migration

Retain machine-readable results for:

- data-integrity audit;
- security audit and CodeQL;
- privacy audit;
- `bash scripts/verify.sh dependencies`;
- `pip check`;
- production-only npm audit;
- migration smoke test;
- Android candidate verification;
- release-provenance verification;
- source/artifact secret scan;
- rotation of test-only secrets used by release verification;
- explicit proof that no production secret entered source control or release artifacts.

Do not rotate or expose production credentials merely to satisfy a checklist.

## Non-destructive database restore drill

For the Android SQLite runtime, the Day 41 restore drill opens the source database read-only, creates a point-in-time backup, restores that backup into a separate database file, and compares integrity, foreign-key checks, schema hashes, table counts, and a hashed logical dump.

It does not write to the live database and does not retain row contents in the report.

Run from the Ubuntu PRoot checkout using the actual SQLite database path:

```bash
cd /root/JobTomatik/backend
export JOBTOMATIK_RUNTIME_MODE=android_managed
.venv/bin/python scripts/run_day41_database_restore_drill.py \
  --database <ACTUAL_SQLITE_DATABASE_PATH> \
  --work-dir .runtime/day41-restore-drill \
  --output evidence/day41-database-restore-drill.json
```

Required compact result:

```json
{
  "passed": true,
  "source_database_modified_by_drill": false
}
```

The retained report SHA-256 becomes one input to the strict Day 41 release dossier.

## Recovery drills

The release dossier additionally requires retained, hashed proof for:

- rollback drill;
- kill-switch drill;
- database restore drill;
- previous-release compatibility drill.

A drill is not considered complete merely because a script exists. The exact release candidate must have retained pass evidence for each required drill.

## Candidate Android artifact

The candidate artifact must bind the exact release commit and retain:

- APK SHA-256;
- build-identity SHA-256;
- signing-certificate SHA-256;
- an explicit signing mode of `release_signed` or `development_signed`;
- reproducible candidate-build proof;
- `publication_authorized=false` during Day 41;
- `release_tag_created=false` during Day 41.

A development-signed APK is acceptable only when labeled truthfully. Day 41 must not pretend a development key is a production signing key.

## Release documents

Finalize, but do not publish prematurely:

- release notes;
- known boundaries;
- operator guide;
- incident runbook;
- CHANGELOG entry;
- README release/autonomy scope.

The documented adapter maturity and autonomy scope must match the actual manifests at the exact candidate commit.

## Signed/reviewed release checklist

The final Day 41 checklist must bind:

- release version `v2.0.0`;
- exact candidate revision;
- checklist SHA-256;
- non-empty review reference.

The strict evaluator consumes the Day 40 certification, release matrix, runtime shutdown state, audit results, drill results, candidate artifact identity, release-document status, and checklist:

```bash
cd backend
python scripts/build_day41_release_candidate_audit.py \
  --day40-certification <DAY40_CERTIFICATION_JSON> \
  --release-matrix <EXACT_HEAD_RELEASE_MATRIX_JSON> \
  --runtime-state <LIVE_MODE_DISABLED_RUNTIME_JSON> \
  --audit-results <AUDIT_RESULTS_JSON> \
  --recovery-drills <RECOVERY_DRILLS_JSON> \
  --candidate-artifact <ANDROID_CANDIDATE_JSON> \
  --release-documents <RELEASE_DOCUMENTS_JSON> \
  --checklist <CHECKLIST_JSON>
```

A genuine pass returns:

```json
{
  "passed": true,
  "day42_entry_eligible": true,
  "publication_authorized": false,
  "release_tag_authorized": false
}
```

## CI boundary

CI for this preparatory branch may prove the audit and restore tooling work, but it must explicitly retain:

```json
{
  "real_day41_audit_claimed": false,
  "day41_complete": false,
  "day42_entry_eligible": false,
  "release_published": false,
  "release_tag_created": false
}
```

Day 42 publication remains a separate exact-commit, owner-authorized action.

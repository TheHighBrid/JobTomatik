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

## Frozen-v1 previous-release compatibility drill

JobTomatik v1.00 records the frozen release source commit as:

`6f7f9fa6a7d3c63516cde381410ac188364dba36`

Day 41 must prove that the exact v2 candidate can consume a database created by that frozen release without destroying existing schema or data. The dedicated workflow is:

`.github/workflows/day41-v1-compatibility-drill.yml`

The drill uses two isolated checkouts and two isolated Python environments. It:

1. checks out the exact Day 41 candidate and frozen v1 source;
2. creates a temporary SQLite database with the frozen v1 Alembic chain;
3. inserts one synthetic user sentinel into the v1 database;
4. records the complete v1 table/column schema;
5. runs the candidate Alembic chain against that same temporary database;
6. requires the migrated database to reach the candidate script heads exactly;
7. verifies every v1 table and every v1 column still exists;
8. verifies the synthetic user row is byte-for-byte equivalent across the stable fields used by the probe;
9. runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check`;
10. queries the migrated v1 sentinel through the current candidate ORM.

The temporary database is deleted after the drill. The live Android database is never opened, copied, or mutated by this workflow, and no real row contents are retained.

The reusable command is:

```bash
cd <CANDIDATE_CHECKOUT>/backend
<CANDIDATE_PYTHON> scripts/run_day41_previous_release_compatibility.py \
  --previous-checkout <FROZEN_V1_CHECKOUT> \
  --candidate-checkout <CANDIDATE_CHECKOUT> \
  --previous-python <FROZEN_V1_PYTHON> \
  --candidate-python <CANDIDATE_PYTHON> \
  --output evidence/day41-previous-release-compatibility.json
```

Required result:

```json
{
  "passed": true,
  "previous_release_revision": "6f7f9fa6a7d3c63516cde381410ac188364dba36",
  "live_database_touched": false,
  "synthetic_data_only": true
}
```

Feed its exact `report_sha256` to the Day 41 recovery-drill input as `previous_release_compatibility_report_sha256`, with `previous_release_compatibility_passed=true` only when the retained report itself passed.

## Recovery drills

The release dossier additionally requires retained, hashed proof for:

- rollback drill;
- kill-switch drill;
- database restore drill;
- frozen-v1 previous-release compatibility drill.

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

CI for preparatory branches may prove the audit, restore, and compatibility tooling work, but it must never claim that the genuine Day 41 release audit is complete merely because synthetic CI passed.

Day 42 publication remains a separate exact-commit, exact-artifact, owner-authorized action.

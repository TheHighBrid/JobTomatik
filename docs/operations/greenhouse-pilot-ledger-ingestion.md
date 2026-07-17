# Greenhouse pilot ledger ingestion

This gate appends independently confirmed Phase B submissions while preserving the artifact-backed Phase A baseline.

It is evidence-only. It does not open a browser, contact an employer, enable live submission, enable scheduled automation, change adapter maturity, or provide a release approval reference.

## Evidence layers

Readiness merges two sources:

1. `evidence/greenhouse-phase-a-baseline.csv`, a checked-in read-only index of 30 qualifying dry runs across 30 employers.
2. `evidence/greenhouse-pilot-ledger.jsonl`, a writable runtime ledger containing only independently confirmed supervised submissions.

The baseline is digest-pinned and never rewritten by runtime ingestion.

## Trust boundary

The ingestion endpoint does not accept a pilot-record body from the client. It rebuilds the supervised record from server-side state:

- the authenticated user's application
- the consumed exact-payload supervised approval
- concrete retained submission evidence
- a currently valid accepted evidence review
- the application idempotency key

An application must already be in the `confirmed` automation state.

## Concurrency and replay

The Phase B JSONL ledger is protected by a process-level file lock.

- readers use a shared lock
- ingestion uses an exclusive lock
- writes use a same-directory temporary file and atomic replacement
- exact replay is ignored
- conflicting evidence for an existing `run_id`, including a baseline run ID, fails closed
- only the first successful ingestion creates an application event
- the published readiness digest covers the merged baseline and runtime records

## Runtime files

Defaults:

- `evidence/greenhouse-phase-a-baseline.csv`
- `evidence/greenhouse-pilot-ledger.jsonl`
- `evidence/greenhouse-pilot-readiness.json`
- `evidence/greenhouse-pilot-readiness.md`

They can be changed with:

- `GREENHOUSE_PILOT_BASELINE_PATH`
- `GREENHOUSE_PILOT_LEDGER_PATH`
- `GREENHOUSE_PILOT_READINESS_JSON_PATH`
- `GREENHOUSE_PILOT_READINESS_MARKDOWN_PATH`

The runtime ledger directory must be writable by the API process and shared by every API replica that may ingest records. The baseline should be deployed read-only.

## Endpoints

### Ingest one confirmed application

`POST /api/greenhouse-pilot-ledger/applications/{application_id}/ingest`

The response includes:

- whether a new runtime record was added
- the canonical supervised record
- the current readiness summary
- baseline, runtime, and combined record counts
- baseline, runtime, and combined SHA-256 digests

### Read readiness

`GET /api/greenhouse-pilot-ledger/readiness`

This authenticated endpoint returns the merged canonical readiness summary and evidence digests. With an empty Phase B ledger it begins at 30 qualifying dry runs, 30 distinct employers, and zero supervised confirmations.

## Promotion boundary

Runtime ingestion never supplies `release_approval_reference`. Therefore it cannot independently make `human_reviewed_submit_ready=true`.

The final release approval remains a separate explicit issue or review reference after every evidence gate has passed.

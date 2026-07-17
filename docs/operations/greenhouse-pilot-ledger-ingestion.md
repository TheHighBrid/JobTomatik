# Greenhouse pilot ledger ingestion

This gate appends independently confirmed runtime submissions to the canonical issue #24 pilot ledger.

It is evidence-only. It does not open a browser, contact an employer, enable live submission, enable scheduled automation, change adapter maturity, or provide a release approval reference.

## Trust boundary

The ingestion endpoint does not accept a pilot-record body from the client. It rebuilds the record from server-side state:

- the authenticated user's application
- the consumed exact-payload supervised approval
- concrete retained submission evidence
- a currently valid accepted evidence review
- the application idempotency key

An application must already be in the `confirmed` automation state.

## Concurrency and replay

The JSONL ledger is protected by a process-level file lock.

- readers use a shared lock
- ingestion uses an exclusive lock
- writes use a same-directory temporary file and atomic replacement
- exact replay is ignored
- conflicting evidence for an existing `run_id` fails closed
- only the first successful ingestion creates an application event

## Runtime files

Defaults:

- `evidence/greenhouse-pilot-ledger.jsonl`
- `evidence/greenhouse-pilot-readiness.json`
- `evidence/greenhouse-pilot-readiness.md`

They can be changed with:

- `GREENHOUSE_PILOT_LEDGER_PATH`
- `GREENHOUSE_PILOT_READINESS_JSON_PATH`
- `GREENHOUSE_PILOT_READINESS_MARKDOWN_PATH`

The configured directory must be writable by the API process and shared by every API replica that may ingest records.

## Endpoints

### Ingest one confirmed application

`POST /api/greenhouse-pilot-ledger/applications/{application_id}/ingest`

The response includes:

- whether a new record was added
- the canonical supervised record
- the current readiness summary
- record count
- SHA-256 digest of the ledger

### Read readiness

`GET /api/greenhouse-pilot-ledger/readiness`

This authenticated endpoint returns the canonical readiness summary and current ledger digest.

## Promotion boundary

Runtime ingestion never supplies `release_approval_reference`. Therefore it cannot independently make `human_reviewed_submit_ready=true`.

The final release approval remains a separate explicit issue or review reference after every evidence gate has passed.

# Greenhouse Phase A evidence baseline

Phase A of issue #24 is complete: 30 qualifying dry runs across 30 distinct employers.

## Reconstruction source

The baseline was rebuilt from ten retained `greenhouse-supervised-live-certification-report` GitHub Actions artifacts covering workflow runs:

- 29564193285
- 29580076615
- 29583871808
- 29584244980
- 29602318645
- 29602763789
- 29603278294
- 29603472784
- 29603695441
- 29603886075

Artifact IDs, SHA-256 digests, and retained record counts are listed in `backend/evidence/greenhouse-phase-a-sources.csv`.

## Versioned evidence files

- `backend/evidence/greenhouse-phase-a-baseline.csv`
- `backend/evidence/greenhouse-phase-a-sources.csv`
- `backend/evidence/greenhouse-phase-a-readiness.json`
- `backend/evidence/greenhouse-phase-a-readiness.md`

Pinned baseline SHA-256:

`14634de4146eb828e394137d351f69270773d957a17899656ccc7577257c3729`

## Verified invariants

- exactly 30 unique run IDs
- exactly 30 distinct normalized employer names
- every record is a Greenhouse `dry_run`
- every record qualifies for the representative matrix
- every record has `final_submit_clicked=false`
- every record is linked to a retained workflow run
- no supervised record is present
- no approval or release reference is present

The qualifying records include safe CAPTCHA handoffs. A handoff record qualifies because the form reached the certified post-fill, pre-action boundary without clicking final submit.

## Runtime accounting

Readiness merges two sources:

1. The checked-in read-only Phase A baseline.
2. The writable Phase B JSONL ledger containing independently confirmed supervised submissions.

Runtime ingestion never copies or rewrites Phase A. It writes only the new supervised record to the runtime ledger under an exclusive lock. The readiness digest covers the merged record set.

## Promotion boundary

The baseline satisfies only the two Phase A count gates. Greenhouse remains `dry_run` until all Phase B requirements pass, including ten independently confirmed supervised submissions and a separate explicit release approval reference.

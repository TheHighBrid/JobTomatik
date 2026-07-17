# Greenhouse Phase A Baseline

Baseline SHA-256: `14634de4146eb828e394137d351f69270773d957a17899656ccc7577257c3729`

## Progress

- Qualifying dry runs: **30 / 30**
- Distinct dry-run employers: **30 / 30**
- Confirmed supervised submissions: **0 / 10**
- Total retained records: **30**

## Safety invariants

- Every baseline record is reconstructed from a retained GitHub Actions artifact.
- Every record is `dry_run`.
- Every record has `qualifies_for_dry_run_matrix=true`.
- Every record has `final_submit_clicked=false`.
- No supervised submission record is included.
- No release approval reference is included.

## Decision

`human_reviewed_submit` promotion remains **BLOCKED** pending 10 independently confirmed supervised submissions and a separate explicit release approval.

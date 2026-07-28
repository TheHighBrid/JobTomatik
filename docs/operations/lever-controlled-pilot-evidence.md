# Lever Controlled Pilot Evidence

This document tracks evidence only for issue #86, proposed PR 6. It does not enable live submission, issue approvals, alter adapter maturity, or claim a completed pilot.

## Current retained evidence

The committed Phase A baseline currently contains two artifact-backed dry runs.

### PointClickCare

- Role: (Canada) - Junior Site Reliability Engineer
- Lever site: `pointclickcare`
- Posting ID: `218d6a04-8e57-4034-84a8-2393e07f66d0`
- Region: `global`
- Workflow run: `30309867130`
- Artifact ID: `8669932175`
- Artifact digest: `98859a562c2b546d612d7b4e53284c17da1910e6037e98b206972f1a35d37d0d`
- Certification report digest: `b0227f5ec7351c37f439ee5cac388fe9d47f43410ffa380653a98b6411a7d904`
- Result: declared CAPTCHA handoff at `post_fill_pre_action`
- Final submit clicked: `false`

### Lever

- Role: API Engineer
- Lever site: `lever`
- Posting ID: `065f4538-7347-4207-909f-4ea68f63b4af`
- Region: `eu`
- Workflow run: `30337038142`
- Artifact ID: `8679562746`
- Artifact digest: `c72bf99c62394393ef98100f3c5deee2b6bdcaa839d163bd0d9dc03a60d711e2`
- Certification report digest: `6ca77acba08e6e909157ede3483414d648cee6263a0af4c769ae77a1b1efa6e6`
- Result: declared CAPTCHA handoff at `post_fill_pre_action`
- Final submit clicked: `false`

Both records qualify for the Phase A matrix because the adapter reached a declared manual challenge boundary without clicking final submit. Neither record counts as a real application or a Phase B submission.

## Current readiness

- Phase A qualifying dry runs: 2 of 30
- Distinct Lever sites: 2 of 30
- Regions: global and EU covered
- Phase B confirmed supervised submissions: 0 of 10
- Canonical Lever maturity: `dry_run`
- Pilot evidence complete: false
- Promotion ready: false

No `backend/evidence/lever-pilot-ledger.jsonl` file is committed because no independently reviewed real Lever submission exists yet. The runtime ledger must be created only by the locked ingestion path after a real, explicitly chosen application has consumed one exact `lvsup-*` approval and produced strong confirmation evidence.

## Evidence acceptance rules

A Phase A row may be added only when the retained report and source artifact prove all of the following:

1. the target is an exact hosted Lever `/apply` URL;
2. site, posting ID, region, and adapter version are recorded;
3. the report artifact has an immutable source reference and SHA-256 digest;
4. résumé upload was verified where the form exposed an upload control;
5. no required unknown answer was guessed;
6. `final_submit_clicked=false`;
7. the result is either `ready_to_submit` with `dry_run_passed`, or a declared manual challenge handoff with `needs_review`.

A Phase B record may be added only through the locked runtime ingestion boundary after:

1. the user explicitly chooses the real application;
2. one exact, short-lived `lvsup-*` approval is issued and consumed;
3. no second final-submit click occurs for that approval;
4. strong confirmation evidence is retained;
5. evidence platform, payload hash, target identity, and approval reference match;
6. independent evidence review is accepted;
7. duplicate detection remains clear.

## Stop conditions

Pause evidence collection immediately after any duplicate submission, wrong-target approval, cross-company or cross-posting navigation, ambiguous confirmation, guessed required answer, or three clustered adapter failures inside the configured circuit-breaker window.

## Promotion boundary

Completing Phase A and Phase B evidence does not promote Lever automatically. Promotion requires a separate reviewed change with an explicit approval reference. The evidence PR must not change the canonical maturity or enable either live-submission flag.

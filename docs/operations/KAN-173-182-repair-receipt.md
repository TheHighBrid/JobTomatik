# KAN-173 through KAN-182 repair receipt

Date: 2026-09-27

## Assignment and repository state

Owner requested repair of five failed CI runs, KAN-173 through KAN-182, test isolation, public verification mocking, truthful physical-run evidence, and `/thanks` classification.

- Repository: TheHighBrid/JobTomatik
- Original PR: #571, open at inspection
- Base: `e433e899fbd302ff2965c60d731c2be4b0734f7c`
- Main inspected: `78a1e55664bfc4f9b574bd2fffc46e63e6eaee68`, already an ancestor
- Repair branch: `fix/kan-173-182-ci-review`
- Validated code head: `9090638efe17e003289385c62d469bf64b2fe257`
- Implementation commits: `1ae859f`, `6ac27d2`, `9090638`

## Confirmed failures and repairs

All five uploaded archives report the same underlying failures. Three tests fail in the full backend runs: submit discovery, Phase 4 candidate gate, and Day 35 operations rehearsal. The release gates fail downstream.

The submit test double returned no elements from `query_selector_all`, which is the API used by `find_first_action`. The corrected double now represents the intended submit element. The original failure was independently reproduced before editing.

The two evidence-gate failures arise from `lever:fixture_regression_sha256_drift` after adding the new certification-loop test. The recorded regate preserves historical hashes, binds the updated fixture corpus, and records that the separately tested handoff route fix is outside the adapter-source digest corpus.

| Review item | Resolution |
| --- | --- |
| KAN-173, KAN-174, KAN-175 | Removed blank lines following function docstrings (D202). |
| KAN-176 | Module summary starts on the second line (D213). |
| KAN-177, KAN-178 | Shorter evidence instructions with explicit owner deferral/escalation, without permitting fabrication or security bypass. |
| KAN-179 | Disputed sub-gates have recorded evidence, owner decision, review date, and certification limits. |
| KAN-180, KAN-181 | Short instructions distinguish verified contradictions from unresolved evidence and define escalation. |
| KAN-182 | Explicit artifact requirements and local-test fallback triggers replace the vague conditional. |
| Global test state | Fixture restores public callbacks, mutable reason collections, and installer globals after each case. |
| Private verification mock | Public `verify_browser_handoff_completion` is mocked before isolated installation. |
| `/thanks` classification | Added route fragment and asserted URL signal plus evidence type; `/apply` remains a success banner, and route-only text is not success. |
| Physical-run claim | Aggregate 30+ claim marked uncorroborated; ledger links the retained Zopa observation and records missing per-run provenance. No observations invented. |

## Validation

Runtime: local Python 3.12 environment. This is not Android physical acceptance and is not the GitHub Python 3.11 runner.

Environment: `DATABASE_URL=sqlite:///./ci-test.db REDIS_URL=redis://localhost:6379/0 SECRET_KEY=ci-only-secret-key AI_PROVIDER=template DEV_MOCK_JOBS=false ALLOW_REAL_APPLICATION_SUBMIT=false`.

Commands:

```sh
python -m pytest -q tests/test_jt001_lever_post_hcaptcha_gate.py tests/test_lever_certification_loop_contract.py tests/test_operator_assisted*.py tests/test_browser_handoff*.py tests/test_lever*.py tests/test_phase4*.py tests/test_day35_operations_rehearsal.py --tb=short --maxfail=5
ruff check --select D202,D213 backend/tests/test_jt001_lever_post_hcaptcha_gate.py
git diff origin/pr-571 --check
```

- Regression suite: **265 passed, 12 skipped**, 283 warnings, 62.06 seconds.
- Skips: Chromium/retainable Chromium unavailable in this environment.
- D202/D213 lint: passed.
- Diff whitespace checks: passed.
- `build_phase4_candidate_gate` at validated code head: `gate_passed=true`, `drift=[]`, runtime safety true, real submission and autopilot disabled.
- `verify_freeze_source_provenance`: `verified=true`, `errors=[]`.
- The full backend suite and physical-device flow were not executed in this repair session.

## Scope and original publication blocker

Changed files: `AGENTS.md`, `backend/app/services/browser_handoff.py`, both JT-001/Lever certification-loop test files, `backend/evidence/day28-phase4-version-freeze.json`, `backend/evidence/lever-native-chrome-observation-ledger.md`, `docs/EVIDENCE_DRIVEN_PLANNING.md`, and this receipt.

Existing adapter source, historical physical evidence, maturity, target verification, submission authorization, duplicate handling, security boundaries, and runtime flags remain intact.

GitHub push was rejected by automatic approval review. The stated reason was that publishing to the GitHub remote requires explicit publication authorization despite the repair request. No alternative publication route was attempted. No follow-up PR was created, no merge was performed, and Jira statuses were not changed.

Recommended next action: obtain explicit permission to push this repair branch and open a follow-up PR targeting `fix/jt-001-lever-post-hcaptcha-gate`. Run GitHub CI with browser dependencies before integrating into #571. Update Jira after the published fix is verifiable.

## Publication follow-up

The owner explicitly authorized publishing the repair branch on 2026-09-27. Command-line Git lacked credentials, so the connected GitHub integration was used. The original source commit was replayed with an identical Git tree as `84948964264043620d9886904a57145f6e2bd117`. The regate validation reference now points to that published source commit. The local validation SHAs above remain a record of the original execution. Commit IDs change with API authorship; the repair code and test contents do not.

Next integration action: open a follow-up PR into `fix/jt-001-lever-post-hcaptcha-gate`, run GitHub CI, and review before merging. No merge or Jira completion is claimed by this publication.

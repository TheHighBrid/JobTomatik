# OneHost Gate 3: human handoff and reconciliation contract

Owner direction adopted on 2026-10-05, America/Toronto.

Recovery Gate 2 is proven on merged `main` by the one-use public Greenhouse
no-submit proof-v2. Gate 3 does not repeat or broaden that proof. Gate 3 proves
that JobTomatik can pause an application at a genuine human boundary, expose the
same retained browser safely to the authenticated owner, resume the same
application, and reconcile a confirmed outcome without duplicate or replay risk.

## Scope

Gate 3 certifies the existing OneHost retained-browser handoff architecture:

`FastAPI -> handoff API -> authenticated owner lease -> same Playwright-owned Chromium process/context/controlled target -> bounded human interaction -> resume/reconciliation -> durable evidence/state`

The implementation already contains retained browser identity, encrypted browser
endpoint storage, owner-scoped handoff records, one-time resume-token disclosure,
short-lived leases, target verification, screenshot frames, bounded browser
actions, confirmation detection, evidence persistence, application-state
reconciliation and replay guards. Gate 3 must exercise these paths together with
real Chromium and retained evidence. A collection of unit tests is not enough.

## Non-goals and safety boundaries

Gate 3 is synthetic and must not submit a real employer application.

Do not:

- dispatch or rerun either consumed Gate 2 public proof identity;
- contact a real ATS for a final submission;
- bypass CAPTCHA, MFA, login, assessment, identity or anti-bot controls;
- infer or invent sensitive, legal, demographic, sponsorship, work-authorization,
  consent or identity answers;
- enable autonomous submit, global live submit or platform-pilot flags merely to
  satisfy the proof;
- promote Greenhouse or any adapter maturity;
- add Android/ADB/PRoot/native-Chrome execution work;
- reconstruct a second browser session and call that a resume.

The fixture may emulate a human-boundary page and an employer confirmation page.
All employer-side state in the proof must remain local and synthetic.

## Gate 3 proof identity

Every proof run must bind evidence to:

- exact Git commit SHA;
- source/tree digest where available;
- one Gate 3 proof-run identifier;
- one synthetic application identifier;
- retained browser session id;
- browser node id;
- browser process id;
- controlled target id;
- browser profile path hash or equivalent identity, without leaking secrets;
- initial, handoff and resumed page fingerprints.

A PASS is invalid if browser identity or the controlled target cannot be matched
across the automation -> handoff -> resume transition.

## Required positive path

The synthetic proof must perform all of the following in one retained browser:

1. Launch Chromium under JobTomatik ownership and record process/session/context
   identity before navigation.
2. Navigate only to a loopback fixture and fill a synthetic application through
   the production form-filling/ATS primitives appropriate to the fixture.
3. Reach a deterministic synthetic human boundary before final submission.
4. Persist a handoff snapshot and create an owner-scoped manual handoff record.
5. Prove that unauthenticated access and an invalid/replayed lease cannot obtain
   a frame or perform an action.
6. Bootstrap exactly once, exchange the one-time resume token for a lease, and
   obtain a screenshot frame through the authenticated handoff API.
7. Perform one bounded synthetic human action through the handoff API.
8. Reattach to the retained Chromium endpoint and prove the same browser process,
   browser session, controlled target and page/application identity are still in
   use. A new Chromium launch or reconstructed form is a failure.
9. Resume automation on that same retained application.
10. Drive the local fixture to an explicit synthetic confirmation state without
    contacting an external ATS.
11. Persist sufficient confirmation evidence before application state is allowed
    to become submitted/confirmed.
12. Complete or resolve the handoff/review state and mark automatic retry false.
13. Verify that a second approval, replayed final action, duplicate queue attempt
    or duplicate application attempt is rejected.
14. Terminate the retained browser and fixture and prove no tracked child process
    remains.

## Required negative controls

At minimum, the proof must independently demonstrate fail-closed behavior for:

- bad or replayed resume token;
- bad, expired or stolen lease token;
- controlled target id mismatch;
- current URL/target binding mismatch;
- browser process/endpoint identity drift;
- ambiguous post-action outcome;
- insufficient confirmation evidence;
- second approval for the same retained final-action boundary;
- replay of a consumed final action;
- duplicate application/submission attempt;
- unexpected external HTTP mutation or WebSocket attempt from the fixture proof;
- browser death before resume.

Each negative case must retain enough diagnostics to distinguish an expected
refusal from harness failure.

## Evidence bundle

A Gate 3 run retains, with secrets and sensitive values redacted:

- summary JSON with PASS/FAIL and violations;
- exact source SHA and proof id;
- handoff/application ids and browser identity tuple;
- event/state-transition ledger;
- API step results for bootstrap, claim, frame, action, completion and replay
  attempts;
- before/handoff/after screenshots;
- sanitized DOM snapshots or equivalent page evidence;
- Playwright trace;
- network observations proving the synthetic boundary;
- submission-evidence rows and their ordering relative to state promotion;
- approval/attempt/retry/duplicate decisions;
- browser/fixture teardown evidence;
- test and runner logs.

## PASS criteria

Gate 3 is PROVEN only if an independently reviewable exact-head run establishes:

- same-process, same-context, same-controlled-target continuity;
- owner-authenticated handoff access with one-time/replay protections;
- safe resume after the synthetic human action;
- confirmation evidence persisted before terminal success state;
- no false submitted/confirmed state;
- no duplicate/replayed final action;
- all required negative controls fail closed;
- no external employer submission occurred;
- clean browser/fixture teardown;
- retained artifact bundle is complete and internally consistent.

A green workflow alone is not the verdict. The retained evidence must be
independently reviewed.

## After Gate 3

Gate 3 does not itself authorize a real application. After Gate 3 is proven, a
separate owner decision may authorize one exact supervised Greenhouse application
for the next physical OneHost acceptance milestone. That later run must bind the
exact employer/role, payload, approval and final action and must preserve all
sensitive-answer, security, confirmation, duplicate and retry boundaries.

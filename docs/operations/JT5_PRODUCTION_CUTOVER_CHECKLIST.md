# JT5 production cutover checklist

**Purpose:** prepare JobTomatik to live-submit real applications through the JT5 Apply path, with evidence for every required protection. This checklist is for the JT5 release and OneHost cutover; it does not replace the owner’s final production enablement decision.

## Release candidate

- [ ] Record the JT5 branch, PR, and exact candidate commit SHA.
- [ ] Confirm the candidate contains the owner Apply UI, target-bound execution, and no reserve-only API.
- [ ] Confirm the candidate keeps the existing target identity and fail-closed classification checks.
- [ ] Keep #681 in draft until the exact candidate satisfies every evidence gate below.

## Verification evidence

Record links to the exact commit’s workflow runs and retain their logs/artifacts.

- [ ] Exact-head JT5 focused tests and full backend suite pass.
- [ ] Full backend, post-merge stabilization, and reproducible verification runs pass on the same exact head. Resolve failures and rerun after each code change.
- [ ] Four-gate regression evidence passes: authentication, owner isolation, atomic duplicate prevention, and uncertain-outcome handling.
- [ ] Invalid targets and target identity drift fail closed.
- [ ] Greenhouse and Lever fixture execution reaches the JT5 worker without restoring removed pilot or approval ceremonies.
- [ ] Confirmed success cannot be automatically replayed; uncertain outcomes require reconciliation and are not retried automatically.
- [ ] Frontend and Android checks pass for the same candidate.
- [ ] Security, dependency, and deployment configuration checks pass.

## OneHost validation

Use the supported topology in [OneHost production deployment](ONEHOST_PRODUCTION_DEPLOYMENT.md). Capture the exact tested revision and artifacts for each result.

- [ ] Validate Docker Compose configuration and safe defaults.
- [ ] Confirm API, PostgreSQL, Redis, single Celery worker, and persistent browser state start healthy on the target host.
- [ ] Run startup recovery checks and verify interrupted live or unknown attempts become uncertain without replay.
- [ ] Run the documented OneHost cutover, startup recovery, and retained-browser handoff checks.
- [ ] Verify authenticated owner Apply and read-only status polling against controlled test fixtures on OneHost.
- [ ] Verify the final effective environment keeps global live submit and autopilot disabled until the owner’s cutover decision.
- [ ] Record host revision, image/build identifiers, check results, and any unresolved issue.

## Owner-controlled live enablement

Live submission is the product goal. Enable it only after the evidence above is complete and the owner selects the production target and time.

- [ ] Owner reviews the exact candidate SHA and evidence links.
- [ ] Owner approves production configuration changes for the intended target.
- [ ] Enable the live-submit flag through the approved secret/configuration process; do not commit secrets.
- [ ] Keep unrelated automation flags at their reviewed values.
- [ ] For the first live Apply, verify the employer, role, canonical target URL, and application identity before dispatch.
- [ ] Observe the returned attempt reference and status through confirmation or explicit uncertain reconciliation.
- [ ] Preserve execution evidence and verify no duplicate attempt was created.
- [ ] If the outcome is uncertain, stop automatic retries and reconcile the same attempt before another action.

## Release record

- Candidate PR: #681
- Candidate SHA: `c2752b1e07db86df9f0caff508cb846e055be3ef` (update if the branch advances)
- Exact-head CI evidence: pending at time of writing
- OneHost validation evidence: pending
- Owner live-enable decision: pending
- Release notes / version / tag: pending until verification and main landing

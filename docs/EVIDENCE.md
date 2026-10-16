# Evidence ledger

**Collected:** 2026-10-16. This ledger distinguishes freshly retrieved GitHub metadata from prior operational reports and unknowns. Tests are not employer receipts.

## Source identity

| Item | Exact identity | Evidence type |
|---|---|---|
| Main at refresh | `6aac5b33701db6d13952f86c1faaeca76d66810f` | Fresh Git checkout and #704 merge metadata |
| Integrated implementation | `1a8a0c7be8476894c51dfba5e62ea7a8b936d5fd` | Fresh #704 head/check metadata |
| Implementation / merge tree | `81ce6d286e7f94dedeb2db388c1c7c35b6873024` | Git tree equivalence, also recorded in coordination receipt |
| Pending #706 correction | `f3ac627a60a33ca1e5f49cf06b3a48492cf7aba2` | Fresh PR metadata; draft, open, not deployed per record |
| Machine-readable check snapshot | [2026-10-16-project-snapshot.json](evidence/2026-10-16-project-snapshot.json) | Retrieved check names, conclusions and URLs |

## Integration and regression evidence

At the integrated #704 implementation head, the freshly retrieved check collection contains **25 successful checks, two skipped, zero failed or running**. This is an exact-head check count, not a number of unique test cases or workflows.

| Evidence | Link | Claim it supports |
|---|---|---|
| JT5 focused / full backend | [run 38825519326](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519326) | Execution regressions on the implementation head |
| Production Compose / mobile handoff | [run 38825519351](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519351) | Controlled startup/restart and synthetic native/mobile behavior |
| Queue round trip | [run 38825519357](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519357) | Applications queue canary path |
| Owned browser proof | [run 38825519213](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519213) | Fixture browser execution on Compose |
| Backend / frontend / Android / release gate | [run 38825519338](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519338) | Build, migration and configured gate results |
| Exact-head acceptance | [run 38825519071](https://github.com/TheHighBrid/JobTomatik/actions/runs/38825519071) | Candidate acceptance check |
| Codacy | [check 116732307582](https://github.com/TheHighBrid/JobTomatik/runs/116732307582) | Successful quality result on that head |

The two skipped checks are `public-proof` and `publish-static-runtime (main only)`. Neither is presented as a passing production proof.

## Pending correction

[#706](https://github.com/TheHighBrid/JobTomatik/pull/706) reports 40 focused regressions passing for release flag enforcement and withdrawal. Fresh GitHub checks show 21 successes, Codacy `action_required`, and one skipped `public-proof` check. See [the Codacy result](https://github.com/TheHighBrid/JobTomatik/runs/116798332314). It is not all green and is not in the deployed implementation. Do not infer that a false production flag currently blocks the integrated JT5 path.

## Operational evidence on OVH

The following are **reported host observations**, retained in [#704](https://github.com/TheHighBrid/JobTomatik/pull/704) and [coordination receipt 6205074007](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6205074007):

- API and worker image/source attestation matched implementation `1a8a0c7`; static UI matched the candidate.
- Public health/readiness returned 200; authenticated application, JT5 status and handoff reads returned 200.
- PostgreSQL contention returned 423 in 24 ms with zero writes or browser actions.
- The temporary global database lock timeout was removed after the NOWAIT deployment.
- Before restart, all four queues and active application/open handoff counts were zero.
- Database/configuration snapshots and rollback images were retained on the host.
- Live submission, autopilot, follow-up and pilot flags were recorded false.

The subsequent [integration receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6207500359) records #704 merged after 25 successful/two skipped checks and confirms tree equivalence. Earlier PR descriptions that say integration was pending are superseded by actual merge metadata.

Desktop Commander freshly reported all three recorded devices offline during this refresh. Container health, current environment, invoices, backup contents and host hardware were not freshly inspected. Offline administration does not by itself prove the application is down.

## Employer outcome boundary

The latest application record has one consumed once-only final action and zero explicit employer confirmation evidence. The owner's manual Applied selection does not change automation uncertainty. This refresh performed no employer action or retry.

Historical confirmed Android submissions are not current OneHost certification. Fixture final actions and intercepted synthetic pages do not count as real applications.

## Retention and future receipts

Keep code revision, image identity, runtime, time, target scope, command/result, artifact hash/reference, observed outcome and unresolved limits in every acceptance receipt. Link existing canonical artifacts rather than rewriting their hashes or maturity claims. CI artifact retention may expire; a link's presence is not proof that its bytes were inspected in this refresh.

Never publish tokens, secrets, raw browser profiles or applicant records to improve an evidence score. Use redacted operational summaries and controlled storage for sensitive evidence.

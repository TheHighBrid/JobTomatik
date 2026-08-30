# JobTomatik v2.00 Known Boundaries

> **Pre-release document.** These boundaries describe the v2.00 release contract. Final adapter maturity must be reconciled against retained Day 39 through Day 42 evidence before publication.

JobTomatik v2.00 provides bounded autonomy, not unrestricted browser automation. This document defines the conditions where the system must stop, defer, or remain non-autonomous.

## Adapter maturity is authoritative

Only an adapter that is `certified_autonomous` on the exact running revision may participate in unattended real submission. A repository label, README statement, elapsed calendar date, or successful dry run does not substitute for retained certification evidence.

Planned v2.00 scope:

| Adapter | Version | Maximum planned maturity | Real autonomous submission |
| --- | --- | --- | --- |
| Lever | 1.1.0 | `certified_autonomous`, contingent on final retained promotion evidence | Only inside a valid bounded live authorization and production policy |
| Greenhouse | 1.1.1 | `dry_run` | No |
| Ashby | 1.1.0 | `dry_run` | No |
| SmartRecruiters | 1.1.0 | `detect_only` | No |
| Workday | 1.1.0 | `detect_only` | No |

If the final exact-head evidence supports a lower maturity, the lower maturity wins and all release-facing documentation must be updated before publication.

## External human-verification boundaries

JobTomatik must not bypass or automate around:

- CAPTCHA or anti-bot challenges;
- MFA or one-time codes that require the applicant;
- identity or document verification;
- employer assessments;
- account-recovery or suspicious-login challenges;
- third-party consent flows requiring explicit human action.

The system may retain a browser session, expose the exact pending action, and resume afterward when the platform permits it. A stale or cross-target session must not be resumed.

## Truthful-answer boundary

JobTomatik may use only approved applicant data and answer policies. It must stop for review when a required question is:

- sensitive and not explicitly approved;
- legally consequential and not covered by a current policy;
- ambiguous;
- outside the approved answer scope;
- inconsistent with another stored answer;
- missing an exact selectable option;
- dependent on information JobTomatik cannot truthfully infer.

The system must not invent work authorization, sponsorship status, demographic answers, veteran/disability information, salary history, legal attestations, identity information, or other applicant facts.

## Confirmation boundary

An attempted submission is not a successful submission merely because a button was clicked or navigation occurred. Strong employer-side evidence is required before JobTomatik records a successful terminal state.

When confirmation is absent, contradictory, or ambiguous:

- the application remains `submission_uncertain` or another fail-closed review state;
- the attempt is not silently retried;
- the reserved live-attempt slot is not reclaimed merely because the outcome is inconvenient;
- duplicate prevention remains active until the uncertainty is resolved.

## Duplicate and retry boundary

A live attempt is bound to the exact applicant, employer, role, posting, documents, answer set, adapter version, runtime revision, and live authorization context.

JobTomatik must not automatically retry after:

- a consumed one-time approval;
- an uncertain final-submit outcome;
- a detected employer confirmation;
- a duplicate canonical posting match;
- a circuit-breaker trip;
- a runtime-revision change that invalidates the authorization.

## Production-policy boundary

Autonomous execution remains subject to production policy even when the adapter is certified. Relevant controls include:

- rolling application caps;
- quiet hours;
- weekly limits;
- employer and role exclusions;
- platform disable lists;
- rate limits;
- circuit breakers;
- global kill switches;
- live-window start/expiry;
- maximum authorized attempt count.

A global environment flag by itself is not sufficient authority for a real submission.

## Live authorization boundary

Day 39 and later live operation uses separately persisted bounded authorization. Authorization must be exact to the approved adapter, adapter version, release revision, attempt cap, validity window, and owner approval context.

Reservations are deliberately non-reclaiming after uncertain or failed consequential browser work. This prevents a failed attempt from becoming an unlimited retry budget.

## Follow-up boundary

Real follow-up sending is separately gated from application submission. A release or live-window authorization for job applications does not imply permission to send external follow-up messages.

The system may prepare schedules, drafts, and review items while outbound sending remains disabled.

## Android/runtime boundary

The supported Android execution model uses the managed runtime and exact runtime-revision attestation. A successful frontend build, native Termux command, or browser-only result does not prove the complete managed stack.

Runtime admission must verify the expected API, worker, Beat, frontend, queue, Redis database, Chromium/CDP, process identity, and exact source revision required by the relevant gate.

Stale PID files are not trusted as process ownership evidence. Cleanup must validate process identity before sending signals.

## Long-duration evidence boundary

Shadow and endurance campaigns are time-dependent evidence. CI may validate tooling but cannot counterfeit elapsed physical runtime, incident behavior, retained Android process identity, or genuine 24-hour policy transitions.

A future-day evaluator returning ready on synthetic fixtures is not proof that the physical campaign completed.

## Release boundary

The final v2.00 release must be bound to one exact source commit and one exact prebuilt APK candidate.

Publication requires:

- strict Day 41 audit pass;
- exact-head final workflow matrix;
- exact source commit equal to current `main`;
- prebuilt candidate from the controlled candidate workflow;
- exact APK SHA-256 and signing identity;
- exact candidate workflow run ID;
- truthful maturity manifest;
- final README, CHANGELOG, release notes, operator guide, and incident runbook;
- separate owner publication authorization;
- absence of an existing immutable `v2.0.0` tag/release.

The publisher must verify and publish the exact approved candidate bytes. It must not rebuild the APK after owner approval.

## Development signing boundary

When production signing secrets are unavailable, the Android artifact may be explicitly `development_signed`. Such an artifact must never be described as production-signed.

A signing-key change can prevent an in-place Android upgrade and may require uninstalling the previous APK. The signing certificate output in the release bundle is the authoritative installation identity.

## Rollback boundary

Rollback must preserve applicant data, application states, evidence, reviews, idempotency keys, and audit records. A code rollback does not justify deleting inconvenient state or converting uncertain submissions into retryable ones.

Database downgrade operations must be tested against a backup or copy before use. The preferred incident posture is to disable live execution first, preserve evidence, restore known-good code, and reconcile affected applications explicitly.

## Privacy and secret boundary

Release artifacts and source control must not contain production credentials, applicant secrets, browser-session secrets, keystores, private signing material, or raw sensitive evidence beyond the repository's approved retention model.

Release verification may use synthetic or test-only secrets. Production secrets are not rotated or exposed merely to make a test checklist look complete.

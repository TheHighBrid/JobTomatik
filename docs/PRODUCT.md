# Product contract

**Direction:** fully autonomous job hunting within approved policies and certified platform capabilities. Supervised operation is a rollout stage, not the final ceiling.

## Objective

JobTomatik discovers relevant jobs, prepares truthful applications, resolves the employer's application target, completes supported forms, submits within the owner's approved rules, verifies the outcome and manages recovery and follow-up. The owner should operate from an Android phone or browser without maintaining a phone-hosted server or routinely debugging infrastructure.

JT5 names the simplified execution contract. It is not an APK version number. One owner-authenticated Apply action reserves and dispatches a target-bound attempt. The four core protections are authentication, ownership, atomic duplicate prevention and honest uncertain-outcome reconciliation. Target integrity, privacy and operational release controls still apply. Genuine human-only challenges use the retained browser and explicit handoff.

## Feature expectations

| Feature | Final expectation | Current boundary |
|---|---|---|
| Discovery / ranking | Continuous discovery, deduplication and ranking against approved job preferences | Existing code; source coverage and reliability vary |
| Profile / answer vault | Reusable truthful applicant facts, provenance and scoped answer policies | Existing implementation; never infer sensitive answers |
| Materials | Correct tailored résumé and cover letter, bound to the application | Existing generation and review surfaces; quality depends on supplied facts |
| Target resolution | Separate listing URL from canonical employer/ATS target | JT5 target initialization and identity checks integrated |
| Form completion | Text, uploads and supported conditional controls with verified values | Adapter-specific capability; unsupported questions route to review |
| Execution | One attempt per approved action, durable queue and exact target | Integrated; release flag correction pending #706 |
| Human handoff | Secure same-browser continuity, useful blocker details and separate final action | Integrated owner viewer; site/runtime limits still apply |
| Confirmation | Record success only from explicit employer evidence | Uncertain outcomes retained; reconciliation follow-up outstanding |
| Recovery | Resume safe work; never replay a potentially submitted application | Startup recovery integrated; remaining classification/reconciliation work tracked |
| Tracking / follow-up | Accurate history, bounded scheduling and approved external messaging | Existing surfaces; production follow-up flag last recorded false |
| Unattended mode | Operate on certified adapters with caps, exclusions, backoff and stop controls | Product target, not a current general-use readiness claim |
| Android client | Stable thin client, authenticated connection and verifiable signed updates | Source candidate 2.1.1; published release and signing evidence tracked separately |

## Robustness requirements

- Authentication and ownership checks run before disclosing attempt history or allowing mutation.
- Reservations and worker claims prevent concurrent duplicate execution; confirmed and uncertain attempts do not automatically replay.
- Freeze and revalidate the resolved target and relevant payload identity before execution.
- Persist final-action intent/checkpoint before a once-only activation. A completed click is not confirmation.
- Preserve truthful outcome classification across API failure, browser loss, restart, withdrawal and manual user-status changes.
- Reconcile interrupted execution before a restarted worker consumes new work. If recovery fails, stop startup rather than consume unsafely.
- Keep one worker and the shared browser identity/profile contract until a separately tested scaling design exists.
- Protect the event loop from blocking database locks and recover transient read failures without repeating mutations.
- Match API and worker code revisions. Retain deployment, backup and rollback provenance.
- Keep credentials, applicant data, browser profiles and raw sensitive artifacts out of public Git history.
- Respect human verification, identity checks and assessments. Never bypass them or invent sensitive/legal answers.
- Apply configured caps, exclusions, rate limits and kill switches to unattended execution.

These are acceptance requirements. An item appearing here does not certify that every failure scenario already has production evidence.

## Final delivery acceptance

1. A fresh supported Linux host can be deployed from a pinned revision using the documented secret configuration and persistent volumes.
2. The Android/browser owner can discover, review and execute a supported application without terminal work.
3. The certified path produces an employer receipt, correct application state and a retained audit trail; uncertain outcomes stay uncertain.
4. Duplicate requests, lost responses and worker/browser restarts cannot cause an automatic second submission.
5. Human handoff preserves the original browser, shows the actual pending action and can recover without replay.
6. Monitoring, alert delivery, backup restore, rollback and resource behavior are demonstrated on the supported host.
7. Autonomous operation runs only within explicitly approved policies and certified capabilities. Unsupported sites remain visible and recoverable.
8. The release includes exact source/artifact identity, known limitations, operator instructions and an auditable cost record.

No universal ATS coverage, guaranteed interview outcome or fixed delivery date is promised. Readiness advances platform by platform, with evidence.

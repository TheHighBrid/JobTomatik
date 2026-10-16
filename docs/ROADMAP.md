# Roadmap and milestones

**Reviewed:** 2026-10-16. **Canonical status:** [project status](PROJECT_STATUS.md).

The roadmap follows demonstrated blockers. Earlier 42-day campaign schedules remain historical planning records, not a current delivery clock. No defensible final delivery date exists while release-control, outcome-reconciliation and supported-runtime acceptance remain open.

## Milestones

| Milestone | State | Exit evidence | Dependencies |
|---|---|---|---|
| M0: Runnable JT5 baseline | Complete for recorded implementation | Integrated execution plus isolated production Compose startup, queue/browser checks and restart evidence | #704 and evidence ledger |
| M1: Owner handoff and truthful outcome display | Integrated; runtime deployment recorded | Native/mobile fixtures, once-only final action, recovery reads, uncertainty retained | #698-#703 included in #704 |
| M2: Correct release controls and outcome semantics | In progress | #706 quality gate/integration/deployment; proven pre-browser classification; same-attempt reconciliation | Current critical path |
| M3: Supported-host operational acceptance | Partially demonstrated | Current revision attestation, backup restore, recovery scenarios, resource/uptime record and operator access | M2; online host administration |
| M4: Evidence-backed supported-platform release | Pending | Representative supported ATS evidence, genuine authorized receipt, exact APK/release provenance, documented limitations | M2-M3; platform acceptance |
| M5: Bounded unattended operation | Pending | Approved policies/caps, certified adapters, monitoring, rollback and unattended reliability evidence | M4 |
| M6: Broader platform coverage | Incremental future work | Each new adapter independently meets capability and reliability criteria | Stable shared execution contract |

## Immediate execution list

- [ ] Resolve #706's Codacy `action_required` result and complete exact-head review.
- [ ] Integrate the verified #706 correction, then deploy once host administration is available.
- [ ] Verify disabled Apply and queued-worker behavior without employer traffic; record image/source identity.
- [ ] Implement or verify evidence-backed reconciliation of the same uncertain attempt without replay.
- [ ] Separate known pre-browser safety failures from potentially submitted outcomes with regression proof.
- [ ] Inspect remaining browser-profile, timezone and diagnostic PR deltas against current main.
- [ ] Reconcile open issues with implementation and evidence; retain genuinely unresolved acceptance work.
- [ ] Capture current host specs, monthly invoice, service usage and backup/restore evidence.
- [ ] Close supported-platform and Android release acceptance with exact artifact provenance.

## Planning estimates

These are planning ranges proposed for this roadmap, not measured throughput, commitments or a guaranteed calendar. Re-estimate after each exit gate.

| Work package | Indicative engineering effort | External dependency |
|---|---|---|
| Release-control closure | 1-2 focused sessions after quality finding is understood | Host access for deployment |
| Reconciliation / failure semantics | 2-4 focused sessions | Availability of retained outcome evidence |
| Remaining PR / issue reconciliation | 1-3 focused sessions | Delta review and exact-head CI |
| Operational acceptance | Several focused sessions plus an observation window chosen from measured behavior | Host access and restore destination |
| Certified release / unattended pilot | Estimate after M2-M3 | Genuine authorization, site behavior and release evidence |

## Alternatives and fallback decisions

| Condition | Preferred response | Alternative / tradeoff |
|---|---|---|
| OVH administration offline | Continue CI, review and documentation independently; retain deployment pending | Use another already-authorized SSH/administration route if available; do not create a replacement paid server silently |
| Resource pressure | Measure memory, disk, browser lifetime and evidence growth; keep concurrency 1 | Resize the same host only after a measured need and owner cost decision |
| Browser profile locked | Preserve live retained owner session; reconcile exact-profile ownership | Integrate necessary profile lifecycle repair after proving no duplicate live owner |
| Outcome uncertain | Retain reservation and inspect same-attempt evidence | Human review if unique employer/owner evidence is required; no blind retry |
| ATS unsupported | Detect and route to a clear manual boundary | Add a fixture-backed adapter later without destabilizing certified paths |
| AI provider unavailable or costly | Use the existing template provider where adequate | Optional metered provider with an explicit budget and truthful facts |
| Host migration necessary | Reuse the OneHost Compose contract and test backup restore | Another Docker Linux provider; cold-start and restore must be proven before cutover |

DigitalOcean remains an architectural alternative, not a second required server. The earlier Oracle signup route was unsuccessful. Android/Termux server execution is retired for production; Android remains the client.

## Change discipline

Keep one bounded task and branch per lane. Reuse existing code and fixtures. Update the plan when stronger evidence changes an assumption. Do not reset application authority or weaken duplicate protection to satisfy a deadline. Completion means the milestone's exit evidence is retained and reviewed, not that its code exists.

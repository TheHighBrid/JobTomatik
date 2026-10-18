# 🔱 JOBTOMATIK JT5 | NORTH STAR PRODUCT BLUEPRINT

**Product:** JobTomatik | **Owner:** TheHighBrid (Don) | **New contributor:** Antigravity
**Blueprint baseline:** October 18, 2026 | **Status:** living contract, not certification evidence
**Canonical repository:** https://github.com/TheHighBrid/JobTomatik

## 1. Product promise

Deliver a dependable job-hunting product for a single owner that can **discover suitable jobs → rank/deduplicate → resolve the real employer application → prepare accurate answers/materials → execute certified ATS forms → preserve human handoffs where necessary → submit only under approved policy → verify employer outcomes → track/recover/follow up**. The owner should work from Android or the web, not run terminals or maintain a phone-based server. **Full bounded autonomy is the destination; supervised mode is the staged delivery path.**

The product is **not** done when a Docker container starts, a UI renders, a submit click fires, a PR is merged, or a green CI badge exists. It is done only when the supported-platform end-to-end contracts and operator release acceptance evidence are satisfied.

## 2. Architecture: OneHost, one source of truth

```text
Android thin client (Capacitor) / web UI
             | authenticated HTTPS
             v
      Caddy / TLS ingress
             |
          FastAPI
     auth, policy, owner API
       /            \
 PostgreSQL 15      Redis 7
 durable state       queue
        \             /
         Celery worker (solo, concurrency=1)
                    |
        Playwright-owned Chromium
          persistent OneHost profile
                    |
       Employer ATS (Lever / Greenhouse / others)
                    |
          Retained owner handoff
                    |
      Evidence / reconciliation / status
```

Supported topology is Docker Compose on the **existing OVHcloud Linux VPS**. API and worker share the necessary browser/runtime topology and persistent `/state`. No Celery Beat on initial safe deployment; unattended scheduler not enabled until certified. The Android app is a client. Termux/ADB/PRoot/native Android Chrome execution are historical, not the production engine. Preserve the working host and avoid cost-generating migrations without evidence and an owner decision.

Build toolchain pins: Python 3.11; Node 20 (minimum 20.19); Java 21; Gradle 9.5.1; Android Gradle plugin 8.13.2; Android API 35. Validate against `.jobtomatik-toolchain.env`, never assume the host installed every pinned tool.

## 3. Key bounded-autonomy invariants

| Domain | Non-negotiable contract |
|---|---|
| Owner authentication | Only authenticated owner can see/mutate application and handoff data. Missing/foreign targets fail closed. |
| Target/payload | Freeze and validate exact ATS identity, resolved URL, applicant data and materials; approvals cannot migrate to another target or payload. |
| Duplicate safety | Atomic claim/reservation, owner isolation, unique attempts, idempotency and no silent second queue or click. |
| Once-only final action | Persist an exact final-action checkpoint before attempting it; a click is not an employer confirmation. |
| Uncertain results | Keep `submission_uncertain`, late receipts, original reviews and evidence. Never rewrite unknown into success or replay to discover outcome. |
| Third-party limits | CAPTCHA/MFA/login/identity checks/assessments go to truthful operator handoff; no bypass or fabricated sensitive answers. |
| Worker and browser | Persistent same-session viewer, worker startup reconciliation, one owned profile/worker until an independently proven scaling architecture exists. |
| Operational flags | `ALLOW_REAL_APPLICATION_SUBMIT`, `AUTOPILOT_ENABLED`, ATS pilot/maturity gates and follow-up send controls have effective API/worker enforcement, not just environment declarations. |
| Recovery & audit | Durable logs/trace/screenshot/DOM/result receipts with revision, runtime, timestamp and artifact hashes. Reconcile, never invent. |
| Cost / privacy | No unapproved paid services; no secrets, credentials, sensitive applications or raw browser profiles in public Git history. |

## 4. Functional acceptance: vertical slices

### Slice A | Discovery and candidacy
Search approved sources, normalize posts, detect stale/duplicate jobs, apply ranked preferences and resolve canonical employer destinations. Keep URL/ATS identity and raw source provenance. Unsupported sources remain visible, not silently marked supported.

### Slice B | Application knowledge and documents
Use truthful verified profile fields, provenance, updated résumé and tailored cover letter. Bind materials to exact role. Missing or consequential answers become owner review questions, never invented answers. Separate safe generic fields from legal/sensitive consent questions.

### Slice C | API-to-worker execution
From a single owner Apply action: permission check → target/payload validation → atomic reservation → dispatch over real Redis/Celery → Playwright form entry/uploads → retained state → result/history. Negative path: duplicate request, unauthorized owner, offline worker, timeouts, invalid URL, unsupported controls and browser restart.

### Slice D | Safe handoff and exact final approval
Expose original same-browser process and pending action. Support owner intervention for unsupported controls and third-party verification without starting a second browser identity. Final-action approval is separately bound and once-only. Preapproval token disclosure, background autopilot activation and duplicate click attempts fail closed.

### Slice E | Confirmation/reconciliation
Store employer receipt where actually observed. Treat API error, server interruption or tab loss after possible submit as uncertain. Late confirmation may annotate evidence without rewriting closed history. Recover same-attempt state without repeat final actions. Never equate manual Applied with employer receipt.

### Slice F | Release, uptime and operator experience
Document deploy/restore/rollback; match API and worker source identities; HTTPS host health, client bootstrap, signing identity and in-place Android update; meaningful owner error/retry UI. Exercise backup restore, resource/budget monitoring, retention, alerting and kill switches. No developer terminal needed for ordinary owner workflow.

### Slice G | Bounded unattended campaigns
Only after supported ATS and host gates are satisfied: approved targets/policies, quotas, exclusion rules, backoff, dry-run/pilot maturity, accurate confirmation, circuit breakers, notifications and recoverable operator review. Per-adapter certification; never claim universal coverage.

## 5. Delivery gates and exit tests

| Milestone | State at snapshot | Exit evidence, not merely code presence |
|---|---|---|
| **M0** Runnable OneHost JT5 | Earlier implementation integrated | Compose/API, PostgreSQL, Redis queue, worker, owned Chromium, auth and controlled restart proved on a pinned revision. Reverify if topology changes. |
| **M1** Owner handoff and source continuity | Integrated with further runtime validation | Verified target-bound owned-browser handoff, final-action boundary, trace and UI/status coherence on relevant source/runtime. |
| **M2** Truthful outcome and effective controls | Corrective code integrated; acceptance still ongoing | Late receipt correctness, PostgreSQL deadlock regression, pre-browser vs uncertain outcomes, same-attempt reconciliation and real disabled controls all proven. |
| **M3** Supported OVH operations | Host health observed, not full site acceptance | Exact deployed revision, backups/restore, rollback, worker/browser restart, CPU/RAM/disk/evidence growth, health/alerts and TLS proof. |
| **M4** Supported ATS + Android release | In progress | Representative authorized employer evidence and safe final-action gate, precise APK source+signer+upgrade + endpoint bootstrap, owner-usable interface. No fabricated receipt. |
| **M5** Bounded autonomous launch | Not certified | Pilot with approved policies, caps, maturity gates, safety controls, rollback, sustained traceable reliability. |
| **M6** Additional adapters | Incremental | Separate per-platform contract, negatives, observations and review. |

No defensible final release date or percent complete has been certified. Show milestones with explicit pass/fail/unknown and gate evidence. Calendar pressure cannot waive safety.

## 6. Highest-impact execution sequence

**Priority P0, already active:** review and integrate genuine fixes without duplicate work; inspect latest #252 and PR #720 (Redis-dispatched durable handoff proof), #721 (Settings API recovery), #722 (future production APK HTTPS endpoint preflight), and old/stale PRs. Independently verify exact head and conflicts; only the integration lead/authorized merger decides sequence.

**Priority P0/P1, next unclaimed:** run supported runtime acceptance from owner app API connection through authenticated Apply/preview, durable queue, retained browser and honest uncertain outcome; isolate and repair first reproducible blocker. Validate current OVH compose, rollback and protected source identity. Use synthetic network-denied fixtures until real target permissions/gates are satisfied.

**Priority P1:** stabilize actual resume/URL/ATS field mapping, unsupported-control handoff and original review closure, recovery after browser/worker failures, adapter-specific certification prerequisites, mobile offline/reconnect UX; reconcile #673/#709/#683 and issues #676-#680 against current main to avoid reimplementing already merged fixes.

**Priority P2:** resource and cost ledger from actual invoices/usage, bounded autonomous scheduler/caps and follow-up eligibility only after lower gates are real. Expand Greenhouse/Lever coverage via certified proof, not benchmark screenshots.

### Scope hygiene: two useful roles

- **Implementation engineer:** claim an unowned slice, patch it end-to-end with regression + negative-path + exact-head CI and a focused PR.
- **Independent verifier:** review published PR source and workflows, reproduce claims and identify blockers; no competing branch, no self-merge, no cross-claim edits.

If existing PRs cover all P0 implementation files, start as independent verifier and then claim an unowned follow-on once integration lead clears overlap.

## 7. Runtime and release operating policy

- Production signing is protected; **build artifact identity, published release status, deployed runtime and upgrade result are separate facts**.
- Caddy HTTPS is the normal public connection. `127.0.0.1` inside Android means **that device**, not the OVH server. Never ship a loopback URL as the default for a production APK.
- Never overwrite immutable 4.0.1 release identity/versionCode 401 to introduce a new build change; use a subsequent version and an owner-approved release procedure.
- OneHost server cutovers require pinned source/image, tested migrations, application-count preservation, flags verified false unless expressly authorized, read-only health checks and restorable rollback.
- Use the smaller safe fixture route first. For real ATS interactions: owner approval is exact and bounded, third-party policies and challenges remain respected, and submit/confirmation evidence is real.

## 8. Owner acceptance checklist

A product-completion release requires **all**: repeatable pinned installation; signed Android in-place update with correct HTTPS connection; owner working auth/search/apply/handoff; retained trace; durable PostgreSQL/Redis/worker/browser operation; secure uncertainty reconciliation and duplicate prevention; at least one certified supported employer path with exact consent and actual receipt; kill switch/caps; verified backup-restore and rollback; documented operational cost and support limits. Mark unsupported ATS paths unsupported rather than claiming 100% automation.

## 9. Source-of-truth protocol

Evidence precedence: supported physical behavior > retained production-like artifacts > repeated real runtime > faithful integration/e2e tests > focused tests > architecture assumptions > earlier roadmap.

Read `AGENTS.md`, `docs/PRODUCT.md`, `docs/PROJECT_STATUS.md`, `docs/ROADMAP.md`, `docs/EVIDENCE.md`, `docs/ONEHOST_RECOVERY_CONTRACT.md`, `docs/operations/AI_COOPERATION_BOARD.md` and issue #252. This document provides direction, **not new authority** for live submits, paid services, production changes or rewriting evidence.

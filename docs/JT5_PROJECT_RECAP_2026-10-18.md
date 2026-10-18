# 🔱 JT5 ANTIGRAVITY TRANSFER | VERIFIED PROJECT RECAP

**Prepared:** 2026-10-18, approximately 15:17 America/Toronto (19:17 UTC)
**Repository:** https://github.com/TheHighBrid/JobTomatik
**Purpose:** fast, truthful engineering orientation. **Not** a replacement for current GitHub state, PR head CI, live runtime checks or issue #252 claims.

## 1. The mission and the pivot

JobTomatik is TheHighBrid's Android/web-controlled job-hunt assistant, moving toward **bounded full autonomy**, with verified applicant facts, ATS form automation, durable owner handoff, employer receipt and duplicate-safe recovery. The earlier phone-hosted Termux/PRoot/native-Chrome backend was retired for production. JT5 now uses one OVH Linux host with FastAPI, PostgreSQL 15, Redis 7, one solo Celery worker, Playwright-owned persistent Chromium, a React/Vite owner interface and a signed Capacitor Android client. No general unattended or real-submit activation is certified.

### Authority and coordination

- **Don TheHighBrid:** product, paid, production release, identity, personal answers and exact real-world action approvals.
- **Underboss GPT-5.6 Sol:** standing integration and independent verification lead.
- **Caporegime GPT-6.1 Sol:** assigned critical-path engineer/reviewer; protect its active file and PR claims.
- **Manus/Claude/Antigravity/other models:** scoped contributors. Antigravity should first claim an unowned lane on [issue #252](https://github.com/TheHighBrid/JobTomatik/issues/252).
- **Grok:** historical inactive lane, do not reassign based on old comments.

## 2. Repository state actually checked October 18

- Verified branch: `main`, protected, at **`469775a1533aabd8c0b1d72a4ac0e5a5f0acc312`** at pack generation.
- Last visible `main` commit: **#718 merged**, `build(android): advance source release identity to 4.0.1`, 2026-10-18 13:09:37 UTC.
- **#711 merged** October 17, retaining late confirmation evidence and fixing a PostgreSQL lock-order deadlock.
- **#714 merged** October 18, consolidating reviewed recovery, receipt review consistency and owner diagnostics.
- **#717 merged** October 18, testing retained Lever form/upload and owner handoff.
- **#718 merged** October 18, versionCode 401 / versionName 4.0.1 on main.
- Do not treat stale October 16 docs' `main` SHA as current. Some historical PR descriptions correctly describe earlier states but remain dated.

## 3. The current deployment, with evidence limits

- Existing host: **OVHcloud `vps-10618f0e.vps.ovh.ca`**; public endpoint `https://vps-10618f0e.vps.ovh.ca`; API health `https://vps-10618f0e.vps.ovh.ca/api/system/health`.
- October 18 [issue #252 relay receipt](https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6253631016) reports read-only OVH HTTPS/TLS/identity health 200, healthy backend, worker, PostgreSQL and Redis, Caddy ingress operating. Backend listens loopback **127.0.0.1:8000 on the host** behind Caddy; no port 8010 listener.
- Running image last reported **`jobtomatik:28b70d5`**. The deployed image and current `main` are **not claimed to match**; do not assume a PR merge changes production. Effective live submit and other pilot/follow-up release flags were reported **false**. Verify again before runtime claims.
- Host inspection October 16: Ubuntu 26.04.1 x86_64 guest, 4 vCPU, 7,746 MiB RAM, approximately 72 GB root disk with 56 GB free at inspection, no swap. These are measured guest values, not promised specs.
- **Billing unknown:** monthly VPS, backups, AI API usage and CI costs are not proven from invoices; do not invent a cost total.

## 4. Android incident: avoid solving the wrong problem

**Owner symptom:** installing the APK extracted from [GitHub Actions run #39118718585](https://github.com/TheHighBrid/JobTomatik/actions/runs/39118718585) led to **`Cannot reach backend API`** and UI base URL `http://127.0.0.1:8010`.

**Verified root cause:** the inspected ZIP (SHA-256 `a3427e9408e239a189e980318161da57a6b8770b705c2b4af6636a60734de94a`) is a **2.1.1 debug-signed** build sourced from `4cfc35ab`, using an older Termux loopback default. Android `127.0.0.1` points to the phone/tablet itself, not the OVH server. This does **not** prove the OVH backend was offline. Workflow run succeeded as a debug build; CI success is not production endpoint correctness.

**Already exists, no repeat build needed:** [protected production-signing run #39130320902](https://github.com/TheHighBrid/JobTomatik/actions/runs/39130320902), successful, source `469775a1`, built **production-signed 4.0.1 (401)**. Issue #252 relay reports APK SHA-256 `052524ae46e0b819d873183ded09278817a979671b8495b7c53f3bb4d0f5ff3c`, package `ca.jobtomatik.app`, unchanged protected signing fingerprint and a successful 4.0.0→4.0.1 **isolated Android emulator in-place upgrade** retaining synthetic application state. That proves the test environment upgrade, not the owner's real phone installation.

**Existing owner-side configuration option (not a request for repeated troubleshooting):** use API Connection URL `https://vps-10618f0e.vps.ovh.ca`, save, test and sign in when the UI is reachable. No code or repo edit is required to repair the old debug build's URL manually. Longer-term release defaults and offline recovery are active PRs below.

## 5. Most relevant active work (check latest head and CI before acting)

| PR / issue | Snapshot | Ownership / why it matters |
|---|---|---|
| [#720](https://github.com/TheHighBrid/JobTomatik/pull/720) | Open **draft**, head `2f90173e7105723f6b4a0bfc5f916520e2639147` | Sol 6.1 Mission 3.5: a synthetic authenticated API→actual Redis→Celery worker→Lever fill/upload→new DB session durable owner handoff test; negative exact-approval/no-submit checks. **1 isolated Redis test passed**, not independent deployed-worker or employer proof. Don't duplicate files. |
| [#721](https://github.com/TheHighBrid/JobTomatik/pull/721) | Open, head `ea79d82fa4227fcdc452d5da415c3ac60ceddb7a` | Settings offline/misconfigured API indefinitely hid the repair field. Scoped React fix keeps connection/test/reset/retry accessible. Local 160 frontend tests and build reported green, but dedicated browser red/green blocked by permitted remote tool; full exact-head review/CI needed. Do not overlap `frontend/src/pages/Settings.jsx`. |
| [#722](https://github.com/TheHighBrid/JobTomatik/pull/722) | Open, head `6287ef55c714eeab24dbf3e8d7800da1184a0421` | Future protected signed builds embed verified OneHost HTTPS origin, perform service/TLS preflight, assert Vite bundle identity; debug APK clearly labeled. Only workflow files `.github/workflows/android-apk.yml`, `.github/workflows/android-production-release.yml`. Requires new version after 401; existing APK immutable. |
| [#719](https://github.com/TheHighBrid/JobTomatik/pull/719) | Open, **based on older `4cfc35ab`** | Version 401 candidate already overtaken by merged #718, do not rebuild or cherry-pick blindly. Integration lead reconciles stale PR. |
| [#673](https://github.com/TheHighBrid/JobTomatik/pull/673), [#683](https://github.com/TheHighBrid/JobTomatik/pull/683), [#709](https://github.com/TheHighBrid/JobTomatik/pull/709) | Open historical/recovery/diagnostic candidates | Before repairing retained-browser or review issues #676-#680, compare diff with merged #714/current main and these claimed branches; no duplicate fixes. |
| [#672](https://github.com/TheHighBrid/JobTomatik/issues/672) | Open 72-hour filling proof | Its written frozen runtime refers to **older DigitalOcean**, while current host is OVH. Treat as a historical proof protocol, not today's deployment identity. |
| [#252](https://github.com/TheHighBrid/JobTomatik/issues/252) | Open, live coordination, **280 comments** inspected | Read newest comments first, claim new file scope, report evidence and handoff here. Do not rely on the comment count remaining constant. |

**Release note:** The last previously documented *published GitHub release* was v2.1.0 as of October 16; a successful protected 4.0.1 Actions artifact is not necessarily a published GitHub Release or an owner rollout. Verify release list separately.

## 6. What has actually been proven vs still outstanding

**Strong engineering evidence:** main includes JT5 API/owner handoff, target-bound attempts, reserved worker queue dispatch, authenticated isolation, once-only final action, no-repeat semantics, restart recovery, late receipt repair, PostgreSQL concurrency regression, Playwright owned-browser tests, Android signing/upgrade provenance and extensive fixtures. Every claim retains its specific test/runtime scope.

**Not yet generally certified:** production host matching current `main`, current end-to-end owner Android HTTPS sign-in; zero-friction Settings recovery under genuine backend failure; deployed independent worker process handoff after all new changes; supported real employer confirmation for the current OneHost runtime; same-attempt uncertain outcome closure without replay; backup restore and rollback on the current release; full bounded-autonomous campaign; final cost/uptime evidence.

**Sensitive historical application:** a Daniels Health submission was previously recorded with one final action but automation outcome `submission_uncertain`; manual user status Applied did not create an employer receipt. Do not retry, relabel as confirmed or search the employer privately without exact appropriate authority. This belongs to governed same-attempt evidence reconciliation.

**New read-only candidate:** a PolicyMe Lever form was inspected read-only on October 18 as a possible future, distinct ATS target. No production application row created, no answers uploaded, and no submission authorized; salary listed CAD $55k-$66k. This is a candidate inspection, not a command to apply.

## 7. Antigravity's best initial leverage

**Start with independent current-state/CI reconciliation of the active P0 PRs and their exact-head gates, without changing their claimed files.** If there is a clear unclaimed defect, claim it on #252. Good unclaimed follow-ons may include a targeted supported-runtime API↔Android acceptance harness, release metadata cross-check, safe worker/browser restart regression, or backup-restore proof **only after** confirming Sol/Manus are not already writing it. Prefer one meaningful blocker fixed over 20 documentation tickets.

Questions to resolve with tools, not with the owner's manual labor:

1. Is protected 4.0.1 current source exactly the installed/signed artifact, and does the next proposed build have a distinct versionCode and verified HTTPS origin?
2. Are #720, #721 and #722 required checks and independent reviews actually green at their **latest** heads, with no product safety regression?
3. Which source revision is running on OVH, and is an authorized updated image promotion already claimed? Never deploy solely because code merged.
4. Can a fully synthetic owner sign-in/discovery/preparation/handoff/recovery path pass under a real Redis serialization and independently restarted process without a submit POST?
5. What one genuine acceptance gate remains blocked after those proofs, and can Antigravity close it independently?

## 8. Critical links and handoff reference

- Repo: https://github.com/TheHighBrid/JobTomatik
- Coordination: https://github.com/TheHighBrid/JobTomatik/issues/252
- Android diagnosis: https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6253631016
- Android signed upgrade evidence: https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6250387538
- Settings offline evidence: https://github.com/TheHighBrid/JobTomatik/issues/252#issuecomment-6250521133
- Real current product contract: `AGENTS.md`, `docs/PRODUCT.md`, `docs/PROJECT_STATUS.md`, `docs/ROADMAP.md`, `docs/EVIDENCE.md`, `docs/COSTS_AND_INFRASTRUCTURE.md`, `docs/GOVERNANCE.md`.
- Production instructions: `docs/operations/ONEHOST_PRODUCTION_DEPLOYMENT.md`.

**Non-negotiable handoff:** branch/base/head SHA; exact code paths; test and runtime evidence; negative controls; PR; source/image/artifact hashes; what is unverified; what was intentionally untouched; next independent task. Protect application outcomes, approvals, secrets, release flags and other contributors' branches.

> Historical snapshot retained on 2026-10-16. This is not current operational or governance guidance. Read [current status](../PROJECT_STATUS.md) and [governance](../GOVERNANCE.md). Links below preserve their original target context.

# JobTomatik Multi-Agent Coordination Blueprint


> **Current status — 2026-10-14**
>
> This block supersedes the dated phase queue and branch snapshot below. JT5 is integrated on #681 at `c2752b1e07db86df9f0caff508cb846e055be3ef`, including owner Apply UI, bound target execution, and removal of the reserve-only route. Authentication, owner isolation, atomic duplicate prevention, target identity, and uncertain-outcome handling remain required. Focused JT5 tests and short exact-head checks passed. Full backend suites were still running at this update; therefore the evidence gate is not yet complete and #681 remains draft. The last full run found a status-response contract regression; the fix restored `applied_at`, `execution_contract`, and `automatic_retry_allowed`.
>
> **Next steps:** finish all full-backend exact-head runs and address any failures; verify four-gate and Greenhouse/Lever evidence on that same head; run OneHost cutover validation; review [JT5 production cutover checklist](../operations/JT5_PRODUCTION_CUTOVER_CHECKLIST.md) and release notes before considering main landing. The owner retains control of production live-submit enablement. Never represent a draft or unverified branch as production-ready.

**Status:** Active (objectives corrected 2026-10-13)  
**Owner (primary engine):** Grok  
**Date:** 2026-10-13  
**Scope:** JT5 cutover, OneHost reliability, approval safety, agent workflow  
**Authority:** Owner-directed; Grok is primary operator for continuity. Sol/Astra/Terra are delegated engines under this plan.

---

## 1. Objectives (non-negotiable)

**Product goal:** JobTomatik discovers, prepares, and **live-submits** real applications to employer ATS targets. That is the point of the project and of JT5.

1. **Ship JT5 so live submit works under four essential protections only** — authentication, ownership, atomic duplicate prevention, and honest uncertain-outcome handling — without pilot/lease/redundant approval bureaucracy.
2. **Never weaken target identity or fail-closed classification** while removing those redundant gates; a live submit to the wrong URL or a false “success” is a product failure.
3. **Prove the JT5 path end-to-end** (exact-head CI, four-gate regression, Greenhouse/Lever execution) so production live submit can be turned on with evidence.
4. **Preserve OneHost dry-run evidence** (retain browser, profile lifecycle) so failures on the way to live submit are diagnosable.
5. **Agent continuity** — one writer per PR head; do not merge unfinished draft JT5 to main as production-ready.

Success is measured by: the system can live-submit under the four gates; removed pilot gates stay gone; Affirm-class defects stay closed; owner can enable production submit because the path works.

**Not an objective:** “avoid live submit.” While work is incomplete it is obvious we do not fire real applications mid-fix. That is ordinary engineering practice, not a goal, and must never be written as if it competed with the product purpose.

---

## 2. Current stack (truth as of 2026-10-13)

```
main @ a4092528
├── #673 sol56/72h-retain-dry-run-failures     OneHost retain after failed dry run
│     └── #683 codex/diagnostic-handoff-text-entry   text entry UX (Grok)
├── #674 sol56/onehost-chromium-profile-lifecycle    Chromium Singleton / exit 21
├── #675 grok/fix-approval-timezone-v2              approval UTC compare (Grok)
└── #681 refactor/jt5-simplified-application-flow    JT5 trunk (DRAFT)
      ├── #686 codex/jt5-bound-target-execution      reserved URL + identity
      └── #690 fix/jt5-688-689-gate-target           lease + target init (Sol, DRAFT)
```

**Do not merge #681, #686, or #690 to main until Section 4 exit criteria are met.**

---

## 3. Priority phases

### Phase A — Stabilize without jumping ships (now)

| Priority | Workstream | Owner | Exit criteria |
|----------|------------|-------|---------------|
| A1 | JT5 syntax/CI hygiene on #681 | Grok | `jt5-focused` + `pytest` green; no syntax errors |
| A2 | #675 approval 409 + timezone | Grok | `exact-approval-gate` green; no naive/aware TypeError |
| A3 | #690 four-gate + #688/#689 | Sol (Grok audits if stalled) | Draft exits only after four-gate regression green |
| A4 | #683 handoff text (done on branch) | Grok | Wait for #673; do not merge to main alone |
| A5 | #673 / #674 OneHost | Sol primary; Grok if stalled | Rebase on current main; required checks green |

### Phase B — JT5 integration line (after A3)

| Step | Task | Owner |
|------|------|-------|
| B1 | Merge or cherry-pick verified #690 into JT5 tip | Grok (with Sol sign-off if available) |
| B2 | Rebase #686 on post-#690 JT5 tip; close identity/lease review threads | Grok |
| B3 | Explicit four-gate regression tests on JT5 head | Grok |
| B4 | Legacy gate caller deletion only from `JT5_CALLER_INVENTORY.md` delete set | Grok |
| B5 | Leave #681 draft until B1–B4 pass exact-head CI | — |

### Phase C — Main landing (only when B complete)

| Step | Task |
|------|------|
| C1 | Merge OneHost track (#673 then #683; #674 independent) if still green |
| C2 | Merge #675 if approval gate green |
| C3 | Merge #681 (JT5) with release notes and production cutover checklist so **live submit can be enabled** |
| C4 | Tag / VERSION bump only after C3 + smoke on OneHost |

### Phase D — Production cutover (later)

Controlled-target browser parity, **owner-enabled production live submit**, Affirm-class monitoring, operator diagnostics. Agents prepare the path; owner flips production submit when evidence is ready. Auto-merge to production remains owner-gated.

---

## 4. JT5 exit criteria (hard)

- [ ] #690: legacy Lever pilot lease bypassed on JT5 path only; adapter/site/posting checks retained
- [ ] #690: application target initialized before reservation; drift/identity checks retained
- [ ] Four-gate regression: auth, ownership, atomic claim, uncertain outcome — all enforced
- [ ] Greenhouse + Lever fixtures reach execution without reactivating removed pilot gates
- [ ] Invalid targets and unauthorized submissions fail closed
- [ ] Production submit flag remains owner-controlled; enable only after the gates above are green
- [ ] #681 still draft until the above are evidence-backed on exact head

---

## 5. Agent roles and task distribution

### 5.1 Grok (primary engine)

- Continuity owner: status, merge safety, PR hygiene, CI root-cause, docs
- Owns: #675, #683, JT5 CI breaks on #681, coordination docs, audits of Sol branches when stalled
- Must not: claim merge of draft JT5 as production-ready; perform real employer submits before owner enables production; bulk-delete gates outside inventory

### 5.2 Sol (Chat) / Sol 6.1 / Astra

- **Chat Sol:** design notes and long-form status; not primary implementer when continuity fails
- **Sol 6.1 / Astra:** batch implementation bursts on a **single assigned PR/branch**
  - Preferred assignment: finish **#690** (lease + target + tests) to green, then stop
  - Secondary: #673/#674 rebase + green if Grok marks them stalled
- Token pauses: each burst must end with a **handoff block** (see §6) so Grok can resume without re-discovery

### 5.3 Terra Luna (low-effort alternative)

- Use only for: mechanical test fixes, inventory updates, rebase conflict resolution, log scraping summaries
- Do **not** assign: security gate changes, identity binding, approval consumption, live paths
- Always review Terra output with Grok before push to shared JT5 branches

### 5.4 Owner

- Merge authority on main; Codacy approvals; **production live-submit enablement**
- Resolves agent conflicts when two engines touch the same PR

---

## 6. Communication protocol

### 6.1 Handoff block (required at end of every agent burst)

```text
HANDOFF
PR: #
Branch:
Head SHA:
Done: (bullets)
Not done: (bullets)
CI: (green/red + job names)
Do not touch: (files/PRs reserved for others)
Next exact step: (one sentence)
```

### 6.2 Branch rules

| Rule | Detail |
|------|--------|
| One writer per PR head | No parallel force-pushes without HANDOFF |
| JT5 children base on JT5 trunk | #686/#690 → `refactor/jt5-simplified-application-flow` |
| #683 bases on #673 branch | Not on main until #673 lands |
| No empty-file / placeholder pushes | Verify `wc -c` / markers before push |
| Draft stays draft | #681/#690 until exit criteria |

### 6.3 Conflict resolution

1. Grok published status wins over stale agent memory  
2. Inventory (`JT5_CALLER_INVENTORY.md`) wins over ad-hoc gate deletion  
3. Fail-closed security wins over convenience in tests  

---

## 7. Immediate task queue (execute in order)

1. **Grok:** Diagnose and fix #675 `test_approved_submit_endpoint_queues_reference_without_consuming_it` (409 vs 200).  
2. **Grok:** Re-check #681 `backend-full` segfault — isolate or quarantine flaky concurrent SQLite assault if it is environmental.  
3. **Sol 6.1/Astra (when available):** Drive #690 to green four-gate + exact-head; emit HANDOFF.  
4. **Grok:** Audit #690 head against issues #688/#689 and #686 review threads; list residual gaps.  
5. **Grok:** After #690 green, integrate onto JT5 tip; refresh #686.  
6. **Deferred:** Merge #673/#674/#683/#675 to main only per Phase C.

---

## 8. Productivity under token pauses

| Constraint | Mitigation |
|------------|------------|
| Sol 6.1 / Astra short runs | One PR per burst; HANDOFF mandatory; no multi-PR “finish the project” prompts |
| Grok token pauses | Persist status in this doc + project memory; resume from HANDOFF only |
| Terra low-effort | Checklist tasks only; Grok merges the result |
| Owner bandwidth | Agents never ask owner to run long patch scripts if push_files can do it; owner only for Codacy/merge/auth |

---

## 9. Explicit non-goals (this cycle)

- Treating “block all submits forever” as a feature; justified gates only  
- Merging draft #681 to main as if production-ready  
- Full legacy approval path deletion before JT5 four-gate proof  
- Rewriting OneHost and JT5 in one PR  

---

## 10. Document control

- Path: `docs/architecture/JT5_MULTI_AGENT_COORDINATION_BLUEPRINT.md`  
- Updated by: Grok (primary); other agents append dated HANDOFF sections only under `## Handoff log`  
- Related: `JT5_SIMPLIFIED_APPLICATION_EXECUTION.md`, `JT5_CALLER_INVENTORY.md`, issues #688 #689, PRs #681 #686 #690  

## Handoff log

### 2026-10-13 — Grok
- Published this blueprint.  
- Next: A2 (#675 409), then A1 residual (#681 backend-full), then audit #690 if Sol has not advanced.

### 2026-10-13 — Grok (correction)
- **Corrected objectives:** product goal is reliable **live submit** under JT5 four gates. Prior wording that read as “objective = no live submit” was wrong.

### 2026-10-13 — Grok (second correction)
- Removed any framing that put “no live submit” near objectives. Product goal is live submit only. Not submitting mid-fix is ordinary practice, not an objective.

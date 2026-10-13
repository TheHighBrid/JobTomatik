# JobTomatik Multi-Agent Coordination Blueprint

**Status:** Active  
**Owner (primary engine):** Grok  
**Date:** 2026-10-13  
**Scope:** JT5 cutover, OneHost reliability, approval safety, agent workflow  
**Authority:** Owner-directed; Grok is primary operator for continuity. Sol/Astra/Terra are delegated engines under this plan.

---

## 1. Objectives (non-negotiable)

1. **Ship JT5 without rebuilding bureaucracy** — four essential protections only: authentication, ownership, atomic duplicate prevention, uncertain-outcome handling.
2. **Never weaken target identity or fail-closed classification** while removing pilot/lease/redundant approval gates.
3. **Keep live submission off** until exact-head CI + four-gate regression are green on the JT5 integration line.
4. **Preserve OneHost dry-run evidence** (retain browser, profile lifecycle) as a separate track from JT5 merge.
5. **Maintain continuity across agents** — no overlapping branches on the same files without explicit handoff; no merge of draft JT5 until children are verified.

Success is measured by: green required checks on the intended base, no reactivation of removed pilot gates, Greenhouse/Lever can reach execution under JT5, Affirm-class timezone/approval defects closed.

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
| C3 | Merge #681 (JT5) with release notes: no live submit until production cutover checklist |
| C4 | Tag / VERSION bump only after C3 + smoke on OneHost |

### Phase D — Production cutover (later)

Controlled-target browser parity, live submit grant still owner-gated, Affirm-class monitoring, operator board read-only diagnostics. Out of scope for agent auto-merge.

---

## 4. JT5 exit criteria (hard)

- [ ] #690: legacy Lever pilot lease bypassed on JT5 path only; adapter/site/posting checks retained
- [ ] #690: application target initialized before reservation; drift/identity checks retained
- [ ] Four-gate regression: auth, ownership, atomic claim, uncertain outcome — all enforced
- [ ] Greenhouse + Lever fixtures reach execution without reactivating removed pilot gates
- [ ] Invalid targets and unauthorized submissions fail closed
- [ ] No live application submission in CI or agent runs
- [ ] #681 still draft until the above are evidence-backed on exact head

---

## 5. Agent roles and task distribution

### 5.1 Grok (primary engine)

- Continuity owner: status, merge safety, PR hygiene, CI root-cause, docs
- Owns: #675, #683, JT5 CI breaks on #681, coordination docs, audits of Sol branches when stalled
- Must not: claim merge of draft JT5; live submit; bulk-delete gates outside inventory

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

- Merge authority on main; Codacy approvals; live submit / production flags
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

- Live Affirm or any real ATS submission  
- Merging draft #681 to main  
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

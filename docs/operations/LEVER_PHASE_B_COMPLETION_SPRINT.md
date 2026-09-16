# Lever Phase B Completion Sprint

Effective: 2026-09-08

Owner acceptance rule updated: 2026-09-15

Completion recorded: 2026-09-16

Primary scoreboard: **10 / 10 supervised Lever objective completions**.

Certification runtime artifact is frozen at:

`198b197dfcece6fbf9f3edfc5a92511fd951b484`

`main` may continue to move for engineering work. The physical certification runtime must not take those updates unless an unfreeze-class safety defect is demonstrated.

## Operating contract

### Fresh candidate
A fresh Phase B candidate is a live application ID created after the certification-runtime freeze with:
- zero prior prepares;
- zero inherited manual reviews;
- zero stale Answer Vault bindings;
- zero historical recovery state.

### One prepare + one recheck
Each live candidate may consume:
1. one initial preparation; and
2. one diagnostic recheck of the existing retained review against already-approved owner policy.

A recheck does **not** remap wording, repair descriptors, rewrite persisted state, reorder reviews, add recovery behavior, or require a branch.

### Objective acceptance rule
The Phase B scoreboard measures whether the supervised Lever objective was actually achieved and proven by retained evidence. The internal validator is a verification mechanism, not the sole authority over project truth.

A run counts when owner-reviewed evidence proves the material objective, including:
- the exact employer and official Lever target were resolved and locked;
- the application form was filled through the final-submit-ready boundary;
- required controls and uploads were verified by browser readback or equivalent retained evidence;
- the run preserved the no-duplicate and exact-target safety invariants;
- the retained evidence is sufficient to distinguish successful objective completion from a partial or guessed run.

A bookkeeping, review-shape, handoff-classification, or validator defect that occurs after those facts are already proven does not erase the completed objective. Raw runtime history must remain unchanged and must never be fabricated to make a validator pass.

### Completed objective record
Maple application **247** is the first completed Phase B objective.

Wave HQ application **261** is the second completed Phase B objective. The retained run evidence proves:
- exact Wave HQ Product Designer Lever target resolution;
- Lever adapter `1.1.0`;
- **19 fields filled**;
- text controls verified through browser input-value readback;
- required radio and checkbox controls verified;
- résumé upload verified;
- `ats_final_submit_ready` reached;
- `submit_clicked` remained `false`;
- exact target identity remained locked;
- the browser handoff was retained with the controlled page target recorded.

The subsequent persisted review/handoff classification failure is a system defect in recognizing the already-proven objective state. It does not reduce the scoreboard.

On 2026-09-16 the owner-reviewed sprint continued on the frozen certification runtime and reached **10 / 10**. The final stretch included newly created retained Lever applications **262**, **263**, **264**, **265**, **266**, and **267**. Accepted rows reached the exact-target final-submit-ready boundary while automated final submission remained disabled. The runtime database and retained review details remain the authoritative evidence for individual row facts; this runbook does not synthesize or rewrite missing ledger history.

Current Phase B progress: **10 / 10 complete**.

### Quarantine rule
If further progress on a candidate requires application-specific historical-state repair, legacy persisted-review recovery, obsolete descriptors, stale vault data, duplicate shells, routing archaeology, or another record-specific implementation repair, do not mutate the retained runtime history merely to satisfy a validator. Preserve the evidence and move engineering repair to a separate lane.

Caseware application **249** remains a quarantined engineering fixture and must not be retried as a fresh Phase B candidate.

Fullscript application **246** remains permanent no-retry quarantine.

### Legitimate human gates
Missing truthful owner answers, CAPTCHA, MFA, login, assessment, identity checks, and the authorized final-submit boundary are expected human gates, not implementation defects. The same retained transaction may pause and resume after the gate without consuming another prepare.

If the posting closes or becomes unavailable while paused, retire it naturally and move to the bench. Do not engineer around natural expiry.

### Runtime freeze and unfreeze
The certification phone stays on the frozen artifact until a demonstrated cross-candidate safety defect requires unfreeze.

Valid unfreeze classes are limited to:
- false confirmation;
- duplicate-submit risk;
- approval replay;
- wrong employer/posting identity acceptance;
- inferred protected, sensitive, or legal answers;
- more than one final-submit execution for one approval;
- confirmation/evidence integrity corruption.

Operator UX friction, missing diagnostics, stale historical state, awkward wording, review-display problems, or candidate-specific recovery do not qualify.

### CI policy
Engineering fixture work defaults to focused tests only.

Run the full exact-head release matrix only when promoting a new frozen certification artifact after a valid unfreeze-class safety defect.

### Candidate runway
The active certification runway is retired after reaching **10 / 10**. Preserve completed rows and quarantines. Do not reopen retained final-submit boundaries merely to satisfy legacy counters.

### Downstream lock
The Day 39-42 and adjacent feature-work lock required **4 / 10 objective completions**. That threshold has been exceeded and the feature-work lock is **released** as of 2026-09-16.

This release does not authorize live unattended submission, enable global real-submit flags, or promote Lever maturity. Those remain controlled by their separate repository-defined release gates.

## Progress rule
The headline progress metric is the owner-reviewed Phase B objective-completion count.

Direct retained runtime evidence is authoritative for whether the objective was achieved. Internal ledger rows, validators, PRs, commits, workflow runs, test counts, and lines changed are supporting evidence. A validator defect cannot retroactively convert a proven completed objective into a failed run.

Current progress is **10 / 10 complete**.

## Post-Phase-B decision

The completion sprint is closed. Resume downstream engineering work.

Lever maturity promotion remains a separate decision. The current canonical `human_reviewed_submit` gate still requires real supervised submission confirmation evidence, duplicate-prevention proof, zero false submitted records, confirmation evidence verification, and an explicit approval reference. The 10/10 objective sprint intentionally stopped at the final-submit-ready boundary with `submit_clicked=false`, so completion of this sprint does not by itself assert those separate confirmation gates.

Until a dedicated promotion PR proves every canonical release gate, Lever remains fail-safe and no autonomous or real-submit flag is enabled.

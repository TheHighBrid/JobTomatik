# Lever Phase B Completion Sprint

Effective: 2026-09-08

Owner acceptance rule updated: 2026-09-15

Primary scoreboard: **2 / 10 supervised Lever objective completions**.

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

### Current completed objective rows
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

Current Phase B progress: **2 / 10**.

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
Maintain:
- **3 fresh ready candidates**; and
- **3 additional availability-checked bench candidates**.

A paused human-gate candidate does not block the next ready candidate.

### Downstream lock
No Day 39-42 or adjacent feature work resumes before Phase B reaches **4 / 10 objective completions**. The existing operator path is the Phase B execution path; needing a new downstream tool is not an exception to this lock.

## Progress rule
The headline progress metric is the owner-reviewed Phase B objective-completion count.

Direct retained runtime evidence is authoritative for whether the objective was achieved. Internal ledger rows, validators, PRs, commits, workflow runs, test counts, and lines changed are supporting evidence. A validator defect cannot retroactively convert a proven completed objective into a failed run.

Current progress is **2 / 10**.

## Immediate mission
Move from **2 / 10 -> 4 / 10** on the frozen certification runtime, then continue to **10 / 10**, followed by a separate Lever promotion decision.

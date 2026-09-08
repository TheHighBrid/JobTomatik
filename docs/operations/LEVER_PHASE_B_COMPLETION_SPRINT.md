# Lever Phase B Completion Sprint

Effective: 2026-09-08

Primary scoreboard: **1 / 10 independently reviewed supervised Lever confirmations**.

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

A recheck does **not** remap wording, repair descriptors, rewrite persisted state, reorder reviews, add recovery behavior, or require a branch. If code must change to advance that record, it was not a recheck.

### Quarantine rule
If further progress requires application-specific historical-state repair, legacy persisted-review recovery, obsolete descriptors, stale vault data, duplicate shells, routing archaeology, or another record-specific implementation repair, the live ID is immediately quarantined from Phase B and may only continue as a sanitized engineering fixture.

Caseware application **249** is classified as a quarantined engineering fixture and must not be retried for Phase B certification.

Fullscript application **246** remains permanent no-retry quarantine.

Maple application **247** remains the only confirmed Phase B ledger row: **1 / 10**.

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
No Day 39-42 or adjacent feature work resumes before Phase B reaches **4 / 10 confirmed**. The existing operator path is the Phase B execution path; needing a new downstream tool is not an exception to this lock.

## Progress rule
The headline progress metric is the independently reviewed Phase B confirmation ledger count.

PRs, commits, workflow runs, test counts, and lines changed are supporting evidence only. If the ledger stays at 1 / 10, certification progress stayed at 1 / 10.

## Immediate mission
Move from **1 / 10 -> 4 / 10** on the frozen certification runtime using fresh candidates, then continue to **10 / 10**, followed by a separate Lever promotion decision.

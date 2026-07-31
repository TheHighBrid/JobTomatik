# JobTomatik 42-Day Bounded-Autonomy Execution Roadmap

**Campaign window:** July 29, 2026 through September 8, 2026  
**Primary objective:** Ship JobTomatik v2.00 as a hands-off job-discovery, preparation, submission, verification, recovery, and follow-up system for adapters that have passed certification.  
**Master roadmap:** #13  
**Current Lever pilot:** #86 and Phase 2 evidence queue #161; PR #152 is merged historical evidence

## Commander’s intent

The endgame is not blind browser automation. The endgame is **bounded autonomy**:

- JobTomatik discovers and ranks jobs continuously.
- It prepares truthful, tailored application materials from approved data.
- It submits without routine user operation only through a certified adapter.
- It records strong confirmation evidence before marking an application submitted.
- It prevents duplicate submissions through durable idempotency.
- It pauses safely for CAPTCHA, MFA, identity checks, assessments, missing legal answers, and ambiguous required questions.
- It resumes from a retained session after an unavoidable human action when the platform permits it.
- It respects configured job filters, employer exclusions, application caps, quiet hours, rate limits, and platform terms.

“Hands-off” means no routine operation. It does not mean bypassing third-party security controls or inventing sensitive answers.

## Truthful starting baseline

At campaign start:

- Greenhouse: `dry_run`
- Lever: `dry_run`
- Ashby: `dry_run`
- SmartRecruiters: `detect_only`
- Workday: `detect_only`
- Lever Phase A: 0 qualifying retained dry runs out of 30 (2 retained CAPTCHA/manual-boundary rows remain nonqualifying)
- Lever Phase B: 0 independently reviewed supervised submissions out of 10
- Real submission defaults: disabled
- Autopilot default: disabled
- Retained-handoff extension default: disabled

## Daily operating rhythm

Every day follows the same six-step loop:

1. **Inspect:** Pull current main, open PRs, workflow health, roadmap issue, and evidence readiness.
2. **Build:** Complete the day’s implementation or evidence mission without waiting for routine approval.
3. **Test:** Run the smallest relevant suite first, then the full affected release gate.
4. **Verify:** Inspect generated evidence, logs, hashes, screenshots, manifests, and state transitions.
5. **Record:** Update the roadmap issue, evidence ledger, changelog, and PR description with exact facts.
6. **Close:** Leave main green, no hidden failures, no uncertain submission marked successful, and a precise next-day checkpoint.

## Execution order and gate semantics

The numbered days are dependency-ordered missions, not permission to skip ahead and not claims that calendar time alone completes work. The campaign dates are planning targets; accelerated work may prepare later-day code, fixtures, or read-only evaluators early, but a day is complete only when every prior prerequisite and its retained evidence pass. A future-day evaluator reporting `blocked_by_evidence_or_user_gate` is readiness infrastructure, not completion evidence.

For every checkpoint, use this precedence:

1. retained evidence and machine-readable gates;
2. exact-head verification results;
3. operator/user approvals explicitly required by that checkpoint;
4. documentation and issue status.

Documentation, synthetic fixtures, counters, or elapsed dates cannot substitute for a failed earlier gate. Never generate real selections, approvals, submissions, confirmation claims, or maturity promotions merely to make the schedule appear complete.

## Cross-phase prerequisite map

| Before starting | Required predecessor | Required retained proof |
|---|---|---|
| Lever Phase B (Day 15) | Lever Phase A (Day 14) | 30 qualifying distinct-site dry runs, global/EU coverage, locked provenance, zero final submits |
| Lever promotion (Day 21) | Lever Phase B (Days 16–20) | 10 exact-approved, independently reviewed confirmations; zero duplicates/false submissions; separate owner approval |
| Multi-adapter candidate selection (Day 28) | certification contract (Day 27) | versioned contract, adapter/fixture/evidence digests, recovery and breaker thresholds |
| Operations rehearsal (Day 35) | scheduler and control centre (Days 29–34) | no-submit end-to-end rehearsal, dependency/security checks, recovery evidence |
| Live unattended pilot (Day 39) | shadow runs (Days 36–38) **and** post-shadow exact-head autonomous promotion | Day 36–38 shadow evidence; exact-head release matrix; separately reviewed `certified_autonomous` approval; policy readiness; owner-authorized live configuration |
| v2.00 release (Day 42) | live pilot and release audit (Days 39–41) | exact-head full gate, signed/development-signed artifact identity, checksums, rollback proof, truthful maturity manifest |

At Phase 1, 3, 4, 5, and release gates, run `bash scripts/verify.sh dependencies` in addition to the affected deterministic lanes. Review dependency changes rather than blindly upgrading majors: keep Python pins and `package-lock.json` reproducible, run `pip check`, audit production npm packages, inspect changelogs, and rerun backend, frontend, browser, Android, migration, and security lanes affected by the update.

## Ownership rule

### Automation-owned work

JobTomatik agents should independently perform:

- repository inspection and implementation;
- test creation and execution;
- CI diagnosis and repair;
- fixture generation and sanitized evidence processing;
- documentation and runbook updates;
- issue and PR maintenance;
- dry-run exercises using synthetic profiles;
- release artifact verification;
- scheduler, monitoring, recovery, and safety implementation.

### User-gated work

User input is requested only when the agent cannot proceed safely without it:

- approval of truthful legal, consent, demographic, disability, veteran, work-authorization, sponsorship, or identity answers;
- selection and explicit approval of real applications during a supervised certification pilot;
- CAPTCHA, MFA, assessment, or identity-verification completion;
- private credentials, signing secrets, or third-party account access not already connected;
- final authorization to promote an adapter or publish a production release when the repository’s gates require it.

## Release-wide definition of done

A day is not complete until:

- relevant unit, integration, browser, frontend, Android, migration, and security checks are green;
- defaults remain fail-safe;
- every generated application outcome has a valid state and audit trail;
- duplicate, retry, crash, timeout, and uncertain-evidence paths have been exercised when affected;
- documentation matches actual behaviour;
- the master issue and active PR show exact progress, evidence, blockers, and next action.

---

# Phase 1: Control Plane and Reproducible Baseline

## Day 1, Wednesday July 29: Freeze the truthful baseline

- [ ] Inventory main, open PRs, open roadmap issues, adapter manifests, evidence ledgers, and release workflows.
- [ ] Confirm current adapter maturity and flags from code, not README claims alone.
- [ ] Produce a machine-readable baseline snapshot with commit SHA, test counts, active gates, and known blockers.
- [ ] Confirm merged PR #152 remains historical evidence and is not represented as promotion-ready.
- [ ] Add a roadmap progress section to #13 linking this plan.

**End-of-day proof:** committed baseline snapshot, green smoke suite, issue update, no maturity change.

## Day 2, Thursday July 30: One-command developer and CI reproduction

- [ ] Verify backend, frontend, browser, Android, migration, and security commands from a clean checkout.
- [ ] Add or repair a top-level verification script that runs deterministic gates in dependency order.
- [ ] Separate fast pre-commit checks from full release checks.
- [ ] Capture exact toolchain versions and fail clearly when versions drift.

**Tests:** clean install, backend suite, frontend build, Android lint/assemble, migration smoke, compileall.  
**End-of-day proof:** reproducible local/CI runbook and one-command verification output.

## Day 3, Friday July 31: Canonical autonomy state model audit

- [ ] Trace every application lifecycle transition from discovery to confirmation.
- [ ] Reject illegal transitions and direct writes that bypass the state service.
- [ ] Ensure `submission_uncertain` cannot become `submitted` without accepted evidence.
- [ ] Verify crash-safe resume from the last verified checkpoint.

**Tests:** transition matrix, stale worker replay, partial transaction, crash between click and evidence capture.  
**End-of-day proof:** state diagram, transition tests, zero unguarded terminal-state writes.

## Day 4, Saturday August 1: Answer Policy Vault completion audit

- [ ] Enumerate required applicant-data and answer-policy fields by country and platform.
- [ ] Verify provenance, scope, timestamp, confidence, encryption, and non-inference rules.
- [ ] Add completeness and conflict detection for required policies.
- [ ] Generate a user-facing “autonomy blockers” report showing exactly which answers prevent unattended submission.

**Tests:** missing sensitive answer, conflicting scope, expired consent, encrypted round trip, AI suggestion requiring approval.  
**End-of-day proof:** policy readiness report with no silent guessing path.

## Day 5, Sunday August 2: Duplicate and idempotency assault

- [ ] Test duplicate detection across source listings, canonical employer targets, redirects, retries, worker restarts, and confirmation-email ingestion.
- [ ] Bind final-submit attempts to exact applicant, employer, role, posting, documents, answers, adapter version, and approval context.
- [ ] Ensure consumed approvals never auto-retry.
- [ ] Add concurrency tests for two workers targeting the same application.

**Tests:** replay, double click, timeout retry, queue duplication, changed URL same posting, same URL changed posting.  
**End-of-day proof:** zero duplicate terminal submissions across the replay matrix.

## Day 6, Monday August 3: Kill switches, handoffs, and circuit breakers

- [ ] Verify global, autopilot, per-platform, real-submit, and resumable-handoff switches.
- [ ] Exercise CAPTCHA, MFA, login, anti-bot, assessment, legal-answer, ambiguous-control, and uncertain-confirmation handoffs.
- [ ] Verify session expiry and secure resume behaviour.
- [ ] Add clustered-failure circuit breakers and operator-visible reason codes.

**Tests:** switch toggles, stale handoff, wrong-posting resume, session expiry, three-failure breaker trip.  
**End-of-day proof:** recorded recovery drill and fail-closed matrix.

## Day 7, Tuesday August 4: Phase 1 gate and backlog surgery

- [ ] Run the full release gate from clean state.
- [ ] Close obsolete issues, split oversized blockers, and identify the exact Lever evidence queue.
- [ ] Publish Phase 1 results and unresolved risks.
- [ ] Freeze the certification scripts and schemas used during Phase 2.

**Gate:** main green, baseline reproducible, state/policy/duplicate/handoff controls verified.  
**Endgame:** a stable launchpad with no moving measurement rules.

---

# Phase 2: Complete Lever Phase A, 0/30 to 30/30

## Day 8, Wednesday August 5: Build the Lever target corpus

- [ ] Discover at least 40 active Lever-hosted postings across distinct employers and both global/EU hosts.
- [ ] Classify forms by control coverage and expected handoff risk.
- [ ] Exclude duplicate sites, expired postings, and unsuitable synthetic exercises.
- [ ] Lock the run manifest and provenance format.

**End-of-day proof:** reviewed corpus with at least 30 viable distinct sites.

## Day 9, Thursday August 6: Lever dry runs 1 through 5

- [ ] Execute five synthetic Phase A dry runs.
- [ ] Cover text, textarea, select, résumé upload, and optional cover letter.
- [ ] Import artifacts only after digest and provenance validation.
- [ ] Fix any deterministic adapter defect and rerun affected cases.

**Daily target:** readiness 5/30 or higher; `final_submit_clicked=false` for every row.

## Day 10, Friday August 7: Lever dry runs 6 through 10

- [ ] Execute five distinct-site dry runs.
- [ ] Prioritize checkbox, radio, work authorization, sponsorship, and consent controls.
- [ ] Verify unknown required controls create review tasks rather than guessed answers.

**Daily target:** readiness 10/30 or higher; zero false submitted records.

## Day 11, Saturday August 8: Lever dry runs 11 through 15

- [ ] Execute five distinct-site dry runs.
- [ ] Prioritize searchable combobox, multi-select, location autocomplete, and conditional controls.
- [ ] Capture validation messages and map them back to source answers.

**Daily target:** readiness 15/30 or higher; all uploads hash-verified.

## Day 12, Sunday August 9: Lever dry runs 16 through 20

- [ ] Execute five distinct-site dry runs across global and EU hosts.
- [ ] Prioritize embedded/customized forms and navigation variants.
- [ ] Verify canonical site, posting ID, region, and official metadata remain stable.

**Daily target:** readiness 20/30 or higher; no cross-target resume path.

## Day 13, Monday August 10: Lever dry runs 21 through 25

- [ ] Execute five distinct-site dry runs.
- [ ] Prioritize CAPTCHA/manual-challenge detection and retained handoff creation.
- [ ] Validate screenshot, URL, pending action, expiry risk, and resumability metadata.

**Daily target:** readiness 25/30 or higher; all challenge paths remain `needs_review`.

## Day 14, Tuesday August 11: Lever dry runs 26 through 30 and Phase A certification

- [ ] Execute the final five or more qualifying distinct-site dry runs.
- [ ] Recalculate readiness from locked evidence inputs.
- [ ] Run the full exact-head workflow matrix.
- [ ] Review all 30 records for duplicates, provenance gaps, guessed answers, and false states.
- [ ] Update issue #161 with final truthful Phase A evidence.

**Gate:** 30 qualifying dry runs, 30 distinct sites where practical, global and EU coverage, zero duplicates, zero false submissions.  
**Endgame:** Phase A complete while Lever remains `dry_run`.

---

# Phase 3: Lever Controlled Supervised Pilot and Promotion

## Day 15, Wednesday August 12: Phase B launch dossier

- [ ] Confirm the user’s profile, résumé, job filters, legal-answer policies, and application caps are current.
- [ ] Present ten high-match real Lever roles for explicit selection.
- [ ] Generate exact payload hashes and one-time approval dossiers only for selected applications.
- [ ] Run dry previews before any final-submit authorization.

**User gate:** select/approve the first two real applications and resolve any truthful policy blocker.  
**End-of-day proof:** two ready dossiers, no submission without explicit approval.

## Day 16, Thursday August 13: Supervised submissions 1 and 2

- [ ] Execute up to two approved applications, one exact approval per attempt.
- [ ] Stop for challenge or ambiguity and preserve the session.
- [ ] Capture strong confirmation evidence and independent review.
- [ ] Verify no retry is possible after approval consumption.

**Daily target:** 2/10 confirmed or a truthful blocker report.

## Day 17, Friday August 14: Supervised submissions 3 and 4

- [ ] Select next best distinct employers and repeat the exact approval flow.
- [ ] Exercise at least one non-trivial custom-question form.
- [ ] Reconcile confirmation page and confirmation email when available.

**Daily target:** 4/10 confirmed; zero duplicates and zero uncertain outcomes promoted.

## Day 18, Saturday August 15: Supervised submissions 5 and 6

- [ ] Execute two approved applications with different control profiles.
- [ ] Exercise retained handoff only if a real challenge appears.
- [ ] Verify resume after handoff cannot cross employer, posting, region, or adapter.

**Daily target:** 6/10 confirmed or safely paused.

## Day 19, Sunday August 16: Supervised submissions 7 and 8

- [ ] Execute two approved applications.
- [ ] Inspect worker timing, retries, browser memory, and evidence durability.
- [ ] Confirm application caps and quiet-hour policy enforcement.

**Daily target:** 8/10 confirmed; no clustered failures.

## Day 20, Monday August 17: Supervised submissions 9 and 10

- [ ] Execute final two approved pilot applications.
- [ ] Independently review every successful evidence record.
- [ ] Classify any failure without weakening the gate.
- [ ] Re-run duplicate and crash-recovery tests using sanitized pilot metadata.

**Gate:** 10 distinct confirmed supervised submissions, one click maximum per approval, zero duplicates, zero silent retries, strong evidence for every success.

## Day 21, Tuesday August 18: Lever promotion decision

- [ ] Generate the Phase B certification report from immutable evidence.
- [ ] Run all backend, browser, frontend, Android, migration, security, and release gates.
- [ ] Open a separate promotion PR. Do not mix implementation/evidence and maturity promotion.
- [ ] Promote only to the level supported by evidence, initially `human_reviewed_submit` unless autonomous gates are also proven.
- [ ] Publish incident and rollback procedures.

**User gate:** final adapter-promotion approval if all gates are green.  
**Endgame:** Lever reaches Greenhouse-grade supervised production readiness without overstating autonomy.

---

# Phase 4: Multi-Adapter Certification and Autonomous Candidate

## Day 22, Wednesday August 19: Greenhouse gap analysis

- [ ] Recalculate Greenhouse readiness using the same locked certification model.
- [ ] Compare its controls, evidence, duplicate protection, and recovery behaviour against Lever.
- [ ] Build the smallest exact backlog to close Greenhouse certification gaps.

**End-of-day proof:** issue-linked Greenhouse gate matrix.

## Day 23, Thursday August 20: Greenhouse regression corpus and missing controls

- [ ] Expand representative Greenhouse fixtures and dry-run coverage.
- [ ] Fix remaining conditional, custom-question, upload, or validation gaps.
- [ ] Verify embedded and hosted forms.

**Tests:** targeted adapter, full inherited safety, frontend labels, Android workflow.

## Day 24, Friday August 21: Greenhouse supervised evidence completion

- [ ] Complete any missing supervised evidence under exact approvals.
- [ ] Independently review confirmations and email/portal corroboration.
- [ ] Re-run replay and uncertain-submission tests.

**User gate:** only for real application selection, legal policies, or third-party challenge.

## Day 25, Saturday August 22: Ashby readiness audit

- [ ] Recalculate Ashby readiness and inspect the existing fixture/live-inspection evidence.
- [ ] Classify iframe, form-definition, upload, challenge, and confirmation variations.
- [ ] Create an exact Ashby promotion backlog.

**End-of-day proof:** Ashby certification dossier and target corpus.

## Day 26, Sunday August 23: Ashby adapter hardening

- [ ] Fix any current-form, iframe, resumable-handoff, or confirmation defect.
- [ ] Verify inherited Greenhouse/Lever safety gates remain unchanged.
- [ ] Expand sanitized regression fixtures.

**Tests:** Ashby browser matrix, inherited adapter gates, state/evidence tests.

## Day 27, Monday August 24: Autonomous-certification contract

- [ ] Define requirements beyond supervised promotion: sustained success rate, zero false positives, bounded retries, breaker behaviour, and recovery drills.
- [ ] Add a signed/machine-readable certification manifest schema.
- [ ] Require adapter version, fixture digest, evidence digest, policy readiness, and exact release commit.
- [ ] Ensure only `certified_autonomous` adapters are eligible for unattended submission.

**End-of-day proof:** executable certification gate, not a prose-only checklist.

## Day 28, Tuesday August 25: Phase 4 gate

- [ ] Run the cross-adapter regression matrix.
- [ ] Select the first autonomous candidate adapter based on evidence, not preference.
- [ ] Publish remaining supervised-only boundaries.
- [ ] Freeze adapter versions for the unattended-pilot phase.

**Gate:** at least one adapter is an evidence-backed autonomous candidate; all others remain correctly bounded.

---

# Phase 5: Scheduler, Observability, Recovery, and Operator UX

## Day 29, Wednesday August 26: Continuous discovery scheduler

- [ ] Implement or verify scheduled job-source discovery and company-career-page refresh.
- [ ] Deduplicate across boards, redirects, canonical posting IDs, and employer sites.
- [ ] Add source backoff, freshness expiry, and closing-date priority.

**Tests:** repeated crawl, source outage, stale posting, redirect loop, same role across sources.

## Day 30, Thursday August 27: Policy-bounded application queue

- [ ] Enforce location, remote status, language, salary, role, seniority, authorization, employer exclusions, and minimum score.
- [ ] Add daily/weekly caps, quiet hours, allowlists, and per-platform limits.
- [ ] Explain every accept/reject/hold decision in the audit trail.

**Tests:** boundary values, conflicting policies, timezone edges, cap exhaustion, emergency kill switch.

## Day 31, Friday August 28: Autonomous material generation verification

- [ ] Verify résumé selection, cover-letter generation, answer lookup, and document hashing.
- [ ] Prevent hallucinated credentials, employment facts, dates, skills, or legal claims.
- [ ] Add deterministic content QA and manual review only when confidence/policy requires it.

**Tests:** missing fact, conflicting résumé, stale document, unsupported claim, low-confidence custom answer.

## Day 32, Saturday August 29: Observability and notifications

- [ ] Build adapter/source success dashboards and actionable alerts.
- [ ] Alert on uncertain submission, repeated validation failure, source breakage, lockout risk, breaker trip, and evidence mismatch.
- [ ] Keep routine successes in digest form to avoid notification noise.

**End-of-day proof:** synthetic incident alerts with exact application links and recovery actions.

## Day 33, Sunday August 30: Crash recovery and dead-letter operations

- [ ] Exercise process crash, worker restart, Redis interruption, database lock, browser death, and device reboot.
- [ ] Resume only from verified checkpoints.
- [ ] Route irrecoverable tasks to a dead-letter/manual-review queue with complete context.

**Tests:** chaos matrix with no duplicate submission and no status corruption.

## Day 34, Monday August 31: Android autonomy control centre

- [ ] Present readiness, active adapters, caps, queue, blockers, handoffs, evidence, and kill switches clearly.
- [ ] Add one-tap pause, drain queue, resume, and reject-application controls.
- [ ] Ensure no direct live-submit control bypasses the certified workflow.

**Tests:** frontend runtime regressions, accessibility, offline/reconnect, Android lint and assemble.

## Day 35, Tuesday September 1: Phase 5 operations rehearsal

- [ ] Run a full no-submit simulation from discovery through evidence-shaped completion.
- [ ] Verify scheduling, caps, quiet hours, retries, alerts, and dead-letter handling.
- [ ] Review audit logs for explainability and secret leakage.
- [ ] Freeze the unattended-pilot configuration.
- [ ] Evaluate the candidate against the Day 27 contract and completed recovery evidence; record a provisional autonomous-certification recommendation bound to immutable adapter/version, code, fixture, and evidence digests. Do not promote maturity or enable live submission yet.

**Gate:** the system can run continuously in simulation without manual babysitting or state corruption; the candidate is eligible to enter shadow runs, while Day 39 remains blocked until Day 38 evidence is committed and a separate exact-head promotion is approved.

---

# Phase 6: Controlled Unattended Pilot and JobTomatik v2.00

## Day 36, Wednesday September 2: Four-hour unattended shadow run

- [ ] Run discovery, scoring, preparation, dry-run filling, and handoff detection unattended for four hours.
- [ ] Keep final submit disabled.
- [ ] Measure queue throughput, error rate, memory, browser cleanup, and notification quality.

**Gate:** no leaked session, duplicate task, false status, or runaway retry.

## Day 37, Thursday September 3: Eight-hour unattended shadow run

- [ ] Run the full working-day shadow cycle.
- [ ] Inject one source outage, one browser crash, one stale posting, and one ambiguous question.
- [ ] Confirm breakers and recovery routes behave exactly as designed.

**End-of-day proof:** incident timeline and recovery evidence.

## Day 38, Friday September 4: Twenty-four-hour unattended shadow run

- [ ] Run across quiet-hour transitions and daily-cap reset.
- [ ] Verify no work occurs outside policy windows except safe maintenance.
- [ ] Reconcile every discovered, skipped, prepared, and held application.

**Gate:** zero unexplained records and zero policy escapes.

## Day 39, Saturday September 5: Bounded live pilot, first wave

- [ ] After Day 38 evidence is committed, run the exact-head release matrix and open a separate promotion change binding the exact adapter version and release commit to a retained `certified_autonomous` approval.
- [ ] Enable final submit only after that promotion is merged, and only for approved policy-complete applications under a conservative daily cap.
- [ ] Run unattended while preserving manual handoff boundaries.
- [ ] Independently verify every submitted outcome.
- [ ] Abort unless the post-Day-38 exact-head promotion and owner authorization both remain valid for the live configuration.

**User gate:** approve the post-shadow exact-head promotion, authorize the bounded live window, and complete only unavoidable external challenges.  
**Stop immediately:** any duplicate, wrong target, guessed required answer, ambiguous confirmation, or breaker trip.

## Day 40, Sunday September 6: Bounded live pilot, second wave

- [ ] Continue only if Day 39 has zero critical defects.
- [ ] Exercise queue prioritization, cap enforcement, and follow-up scheduling.
- [ ] Compare platform evidence with confirmation email/portal records where available.

**Gate:** sustained zero false-positive submission status and zero duplicates.

## Day 41, Monday September 7: Release candidate audit and recovery drill

- [ ] Disable live mode and perform a complete data, security, privacy, dependency, migration, Android, and release audit.
- [ ] Rotate test secrets and confirm no production secret entered source control or artifacts.
- [ ] Run rollback, kill-switch, database restore, and previous-release compatibility drills.
- [ ] Finalize release notes, known boundaries, operator guide, and incident runbook.

**End-of-day proof:** signed release checklist and reproducible candidate build.

## Day 42, Tuesday September 8: Ship JobTomatik v2.00

- [ ] Run the exact release commit through every required workflow.
- [ ] Build and verify the signed or explicitly development-signed Android artifact.
- [ ] Publish JobTomatik v2.00 with truthful adapter maturity and autonomy scope.
- [ ] Tag the release, attach checksums/build info, and update README/CHANGELOG.
- [ ] Open the post-release reliability watch issue and next-adapter expansion issue.

**Final gate:** v2.00 may run hands-off only through certified adapters and configured policy limits.  
**Endgame:** continuous job discovery, preparation, bounded submission, confirmation, recovery, and follow-up operate without routine user supervision.

---

# Post-v2.00 Expansion Chapters

These chapters continue the final objective after the initial bounded-autonomy release.

## Chapter 7: SmartRecruiters promotion

- Move from `detect_only` through dry-run, supervised pilot, and autonomous certification.
- Add official target identity, form control, session, evidence, and failure taxonomy support.
- Reuse the common adapter contract and locked certification framework.

## Chapter 8: Workday authentication and multi-step forms

- Build encrypted credential references and isolated sessions.
- Support account creation/login, resumable multi-page forms, repeated history sections, and MFA handoff.
- Add lockout prevention, session expiry, and portal-history confirmation.

## Chapter 9: iCIMS and Taleo

- Inventory platform families and UI generations.
- Build family-specific adapters rather than a brittle universal clicker.
- Certify each family/version with fixtures, supervised evidence, and fail-closed detection.

## Chapter 10: Government and specialized portals

- Separate portal families by jurisdiction and authority.
- Encode explicit legal/work-authorization policy scopes.
- Detect and hand off assessments, identity checks, declarations, and unsupported document requirements.

## Chapter 11: Long-run reliability

- Maintain rolling 7-day and 30-day adapter reliability windows.
- Automatically demote adapters when evidence quality or success rate falls below threshold.
- Require recertification after material platform changes.
- Run quarterly recovery, security, and duplicate-prevention drills.

---

# Daily closeout checklist

Use this at the end of every scheduled mission:

- [ ] Today’s code/evidence is committed to the correct branch.
- [ ] Relevant targeted tests pass.
- [ ] Full affected release gates pass.
- [ ] No feature flag or maturity level changed accidentally.
- [ ] No uncertain outcome is marked submitted.
- [ ] No duplicate path exists.
- [ ] Evidence and readiness snapshots are regenerated from locked inputs.
- [ ] Active issue and PR descriptions state exact progress.
- [ ] Tomorrow’s task is unblocked or the blocker is documented with the smallest required user action.

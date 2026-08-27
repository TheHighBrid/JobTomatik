# Day 39: Post-Shadow Promotion and Bounded Live Pilot

Day 39 is the first stage that can lead to autonomous real submission. It therefore has two separate approvals that must not be collapsed into one flag:

1. **adapter maturity promotion** to `certified_autonomous` on an exact post-Day-38 release candidate;
2. **bounded live-window authorization** for a conservative real-submit pilot after that promotion is merged.

A successful promotion does not itself authorize the live window.

## Required predecessor

Day 38 must first produce genuine physical Android `shadow_run_24h` evidence that:

- has at least 86,400 persisted elapsed seconds;
- passes `scripts/export_day38_shadow_endurance.py`;
- returns `day39_entry_eligible=true`;
- has strict report SHA-256 retained in the Day 39 dossier;
- has independently reviewed certification evidence with `review_status=verified`;
- proves diagnostic production-policy telemetry without allowing those diagnostics to authorize or block shadow execution;
- proves configured quiet-hour transition coverage;
- proves production capacity uses `rolling_previous_24_hours` semantics;
- proves at least one real persisted application aged out of the rolling 24-hour membership window;
- has zero policy escapes, unexplained records, duplicates, false submitted states, runaway retries, or cycle failures.

The old roadmap phrase `daily-cap reset` is not a valid promotion claim. Production does not use a UTC-midnight daily reset.

## Exact-head release matrix

After Day 38 evidence is retained and reviewed, run the release matrix on the **current post-shadow release candidate**, not the older Day 38 runtime revision. The Day 39 readiness evaluator deliberately allows the Day 38 evidence SHA to precede the release-candidate SHA.

The dossier requires success from:

- Backend tests
- Post-merge stabilization
- Reproducible verification
- CodeQL security analysis
- Current-head end-to-end acceptance
- Android runtime dispatch acceptance
- Full-stack shadow campaigns
- Day 38 shadow endurance tooling gate

The matrix revision and `current_head` must be the same exact 40-character commit.

## Pre-promotion safety state

Before promotion:

- Lever remains `1.1.0 / dry_run`;
- `autonomous_submission_allowed=false`;
- `ALLOW_REAL_APPLICATION_SUBMIT=false`;
- `ALLOW_REAL_FOLLOWUP_SEND=false`;
- no live window is pre-authorized.

Enabling real submission early to make the promotion test "more realistic" is prohibited. That would defeat the gate rather efficiently, which is apparently a thing software needs to be told explicitly.

## Owner promotion gate

Technical readiness is not sufficient. The owner approval must bind:

- exact release-candidate commit;
- adapter `lever`;
- adapter version `1.1.0`;
- target maturity `certified_autonomous`;
- non-empty approval reference.

Only then may a **separate promotion change** be opened or finalized.

## Read-only evaluator

Use:

```bash
cd backend
python scripts/build_day39_promotion_readiness.py \
  --day38-report evidence/day38-twenty-four-hour-shadow-endurance.json \
  --day38-review <DAY38_REVIEW_JSON> \
  --release-matrix <EXACT_HEAD_RELEASE_MATRIX_JSON> \
  --adapter-state <LEVER_STATE_JSON> \
  --runtime-safety <RUNTIME_SAFETY_JSON> \
  --owner-approval <OWNER_APPROVAL_JSON>
```

Exit codes:

- `0`: technical evidence and exact owner promotion approval pass;
- `3`: technical evidence passes but owner promotion approval is still required;
- `2`: one or more technical promotion blockers remain.

The evaluator never edits adapter maturity, signs a promotion manifest, changes submission flags, or authorizes a live window.

## Bounded live window remains separate

After a promotion is merged, Day 39 still requires a separate live-window authorization with conservative caps and current policy readiness. That future authorization must expire or otherwise be bounded, remain revocable by kill switches, and stop immediately on:

- duplicate submission;
- wrong target;
- guessed required answer;
- ambiguous confirmation;
- circuit-breaker trip;
- loss of exact promoted adapter/runtime identity.

The promotion gate proves eligibility. The live-window gate spends real submission authority. They are intentionally different things.

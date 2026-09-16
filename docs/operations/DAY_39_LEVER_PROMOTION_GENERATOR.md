# Day 39 Lever promotion generator

This runbook describes the separate promotion-record generation step for Lever 1.1.0.
It is intentionally non-consequential: generating a valid signed release record does not
enable real application submission, recruiter follow-up, autopilot, or a Day 39 live
window.

## Hard prerequisites

Do not run the generator as a release action until all of these are genuine retained facts:

1. Lever Phase A remains complete under the frozen rules.
2. Lever Phase B contains at least 10 safe supervised confirmed submissions, all independently reviewed, with zero duplicates, zero false submitted records, no uncertain outcome credited as submitted, and evidence payloads matching consumed approvals.
3. The retained Day 35 recovery/policy gate remains valid.
4. The strict Day 36 4-hour report passes.
5. The strict Day 37 8-hour report passes with all four required incident drills.
6. The strict Day 38 24-hour report passes and returns `day39_entry_eligible=true`.
7. The Day 39 promotion-readiness report passes on the exact release-candidate commit.
8. The owner promotion approval binds the exact release commit, `lever`, `1.1.0`, and `certified_autonomous`.
9. A separately configured `AUTONOMY_CERTIFICATION_SIGNING_KEY` of at least 32 bytes is available. Never commit this key.

As of the preparation of this tooling, canonical retained Lever Phase B is still `0/10`.
The generator must therefore produce blockers, not a promotion record, against current
frozen evidence.

## Generation command

Run from `backend/` on the exact promotion candidate after all prerequisite artifacts have
been reviewed:

```bash
export AUTONOMY_CERTIFICATION_SIGNING_KEY='<operator-provided-secret>'
python scripts/build_day39_lever_promotion.py \
  --promotion-readiness evidence/day39-promotion-readiness.json \
  --lever-readiness evidence/lever-pilot-readiness.json \
  --phase4-freeze evidence/day28-phase4-version-freeze.json \
  --day35-gate evidence/day35-operations-rehearsal-gate.json \
  --day36-report evidence/day36-four-hour-shadow-endurance.json \
  --day37-report evidence/day37-eight-hour-shadow-endurance.json \
  --day38-report evidence/day38-twenty-four-hour-shadow-endurance.json \
  --owner-approval evidence/day39-owner-promotion-approval.json \
  --key-id '<operator-key-id>' \
  --output evidence/lever-autonomy-release.json
```

The signing key is intentionally environment-only. It is not accepted as a command-line
argument, because shell history is a remarkably stupid place to store a release trust
root.

Exit codes:

- `0`: an installable signed release wrapper was generated and self-validated;
- `3`: one or more evidence/approval/signing prerequisites are blocked; the output is a non-installable blocker report;
- other nonzero status: malformed input or execution failure.

## Runtime behavior

`app.services.ats_manifest` may load `evidence/lever-autonomy-release.json` (or the path
specified by `LEVER_AUTONOMY_RELEASE_PATH`). The loader only exposes the embedded
`autonomy_release` section when the wrapper says `promotion_record_generated=true` and
it targets Lever 1.1.0.

That is still not enough to promote maturity. `ats_maturity` independently validates the
embedded manifest, source bindings, evidence and policy digests, exact adapter/version,
exact release commit, owner approval, manifest digest, and HMAC signature against the
runtime `AUTONOMY_CERTIFICATION_SIGNING_KEY`. Missing or wrong trust material therefore
leaves Lever at `dry_run`.

## Separation of authority

A successful promotion record changes canonical maturity evidence only. It does not:

- set `ALLOW_REAL_APPLICATION_SUBMIT=true`;
- set `ALLOW_REAL_FOLLOWUP_SEND=true`;
- authorize a Day 39 live window;
- reserve an application attempt;
- submit an application;
- create or infer an owner live-pilot approval.

Those remain separate later gates. PR #405 provides the bounded owner live-pilot API and
worker chokepoint, and it still requires exact active authority immediately before
consequential browser work.

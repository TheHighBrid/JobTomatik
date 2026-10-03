# Lever native-Chrome physical submission evidence — 2026-09-21

## Evidence class

Owner-observed physical-device acceptance evidence for the operator-assisted Lever path on Android native Chrome.

This record documents one genuine successful employer submission. It does **not** promote Lever to autonomous maturity, enable unattended final-submit authority, or replace the repository's release/certification gates.

## Observed successful path

- Platform: Lever
- Employer: Zopa
- Role: Zopa for Business - Risk Lead
- Employer confirmation URL:
  `https://jobs.lever.co/zopa/3cc55902-4524-475b-ada7-43af0daaf180/thanks`
- Visible confirmation text: `Application submitted!`
- Browser: native Android Chrome
- Preparation mode: JobTomatik operator-assisted retained application
- Form preparation: JobTomatik filled the application before the human final action
- Final action: human/operator controlled
- Confirmation: visible Lever `/thanks` page after the final action

## Source artifact

The owner supplied a physical-device screenshot in the acceptance session.

- Screenshot SHA-256: `03e56eba5594ae6a2adf0b3839bfc60b9ae883b807abf3bd909f4fedacb1a7a8`
- Encoded dimensions: `1536x912`
- Encoded size: `84203 bytes`
- Visible browser state: Lever confirmation route ending in `/thanks`
- Visible employer response: `Application submitted!`

The screenshot itself is intentionally not committed to the repository because repository evidence must not depend on committing user browser captures or personal application material.

## Runtime lineage

The successful path followed the native-Chrome repair sequence merged through:

- PR #542: native Chrome identity enforcement
- PR #544: Android acceptance browser config resolution
- PR #545: stranded `applying` recovery
- PR #547: native Chrome bootstrap
- PR #548: verified HTTP CDP Playwright attachment
- PR #552: retained native Chrome target-id continuity
- PR #553: post-stack native Chrome recovery

The exact device runtime revision is not asserted from the screenshot alone. Runtime identity remains governed by the managed runtime attestation output.

## What this proves

This physical acceptance proves that the supported operator-assisted path can reach the following real-world sequence on Android native Chrome:

`resolve exact Lever target -> fill application -> retain/review -> human final action -> Lever confirmation page`

It also proves that the final employer page can remain usable through the repaired native-Chrome path long enough for a successful human-controlled final submission.

## What this does not prove

This record does not by itself prove:

- autonomous Lever final submission;
- CAPTCHA compatibility for every Lever employer;
- a zero-false-positive confirmation rate across a certification sample;
- adapter promotion to `certified_autonomous`;
- permission to retry this application;
- permission to broaden submission authority.

Existing idempotency, exact-target approval, evidence, duplicate-prevention, kill-switch, and adapter-maturity controls remain authoritative.

## Golden regression contract

Future browser/runtime changes must preserve all of the following:

1. Native Android Chrome remains the application browser when selected.
2. JobTomatik may fill the exact approved Lever application without replacing the browser/profile.
3. The controlled filled page must survive the operator-review boundary.
4. Human final action remains distinct from automated final-submit authority.
5. A strong Lever confirmation route such as `/thanks`, paired with explicit confirmation text, must be recognized as submission evidence.
6. Once strong confirmation is observed, JobTomatik must finalize evidence and application state without requiring the operator to perform a second bookkeeping action.
7. A missing/changed retained target, browser identity drift, ambiguous confirmation, or uncertain outcome must remain fail-closed.

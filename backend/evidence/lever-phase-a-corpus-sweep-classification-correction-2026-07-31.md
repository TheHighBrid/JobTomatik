# Lever Phase A sweep classification correction, July 31, 2026

## Correction

The locked-corpus sweep originally grouped D8-019, D8-025, and D8-038 under `unsupported_control` because the form runner found no controls or submit action.

The retained source reports show a more precise root cause for all three targets:

- the hosted application page displayed a Not Found 404 title;
- the exact official Lever Postings API request returned HTTP 404;
- the exercise then ran against the unavailable page and emitted `No next-step or final-submit control was found.`

These attempts are therefore corrected to **`posting_unavailable`**, not adapter control failures.

## Corrected sweep categories

- 33 manual challenge or human-verification boundaries
- 3 ambiguous required-question failures
- 3 unavailable postings
- 0 unsupported-control failures
- 0 `ready_to_submit` outcomes
- 0 final-submit clicks

## Target receipts

| Review ID | Employer | Region | Official API | Retained report SHA-256 |
|---|---|---:|---:|---|
| D8-019 | Bounteous | global | 404 | `957d894f6c15418057102a48c514844aea05ff255a40fb1a8eaff6b7cba21663` |
| D8-025 | CaptivateIQ | global | 404 | `ab4269e9c846310e696904b3fa465b787c36d50ea7088b6028265d302c5a98e8` |
| D8-038 | Finom | EU | 404 | `5e9172ece28e265425dc79fcba4181a9444bec408c4ae3921e1f073416b24515` |

Source workflow run: `30604351125`  
Source artifact: `8783248871`  
Source artifact SHA-256: `cae1d5ecaa03510f3ea2ac32246ce4358633eaadae39b690dc023814166210e9`

## Certification effect

This is a root-cause correction only.

- Canonical qualifying count remains **0/30**.
- No quota credit is added.
- No corpus member or frozen qualification rule is changed.
- Lever remains `dry_run`.
- Real submission, supervised pilot, autopilot, and resumable live handoffs remain disabled.
- `final_submit_clicked=false` for all three attempts.

The live certification runner is being hardened to stop after authoritative 404/410 metadata and emit a `posting_unavailable` receipt instead of opening a second browser and reporting a phantom control defect.

# Lever Phase B Dossier

The Lever Phase B dossier is a deterministic, read-only review artifact for one exact user-selected application.

## What it contains

- employer and role;
- exact hosted Lever `/apply` URL;
- Lever site, posting ID, and region;
- adapter version;
- target-identity and official posting-metadata hashes;
- résumé, profile, cover-letter, answer-policy, and combined payload hashes;
- duplicate-prevention state;
- open manual-review reasons;
- approval status without private notes or raw answers;
- submission-evidence and independent-review status;
- Phase A and Phase B readiness counts;
- both live feature-flag states;
- mandatory retained-browser handoff boundaries.

## What it never does

The dossier does not:

- rank or select jobs;
- copy raw applicant answers, raw profile values, or cover-letter text;
- enable a feature flag;
- issue, revoke, or consume an approval;
- open a browser;
- queue a worker task;
- click final submit;
- write to the pilot ledger;
- promote Lever beyond `dry_run`.

## Operator flow

1. Open the exact Lever application record.
2. Review site, posting ID, region, canonical URL, adapter version, and target hashes.
3. Download the dossier JSON when an immutable review artifact is needed.
4. Re-fetch the dossier immediately before approval.
5. Treat any changed dossier digest as payload, target, or evidence drift.
6. Use the separate supervised approval panel only after all blockers are understood.

## Phase B evidence

A successful real pilot record still requires:

- one `lvsup-*` approval consumed for one attempt;
- one final-submit click maximum;
- strong confirmation evidence;
- matching approval and evidence payload hashes;
- independent evidence review;
- zero duplicate submission;
- no silent retry after approval consumption.

A URL change alone is not confirmation evidence. Ambiguous confirmation remains `submission_uncertain` and must create manual review.

## Certification

The `Lever Phase B dossier certification` workflow tests Greenhouse and Lever dossier behavior together while both platform flags, the global live-submit switch, autopilot, and resumable handoffs remain disabled.

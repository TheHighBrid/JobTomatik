# Ashby real-runtime certification

Status: IN PROGRESS

Ashby is not certified by fixture, synthetic, or historical dry-run evidence alone.

## Required real-runtime gate

Certification requires one operator-authorized application to demonstrate the complete current JobTomatik path on the retained native Chrome runtime:

1. resolve a real Ashby job/application target;
2. open or resume the exact retained application tab;
3. fill supported fields and uploads;
4. stop on unknown or policy-bound questions and surface them to Answer Vault;
5. resume the same retained application after answers are saved;
6. submit only under the normal authorized submission policy;
7. detect sufficient Ashby post-submit confirmation evidence;
8. persist confirmation evidence;
9. reconcile the JobTomatik application to `applied` only after sufficient evidence;
10. prevent another submission attempt for the confirmed application.

## Fail-closed requirements

- Missing or ambiguous confirmation must remain pending/manual review, never `applied`.
- Unknown answers must not be invented.
- CAPTCHA/MFA remains a manual boundary.
- A resumed handoff must not silently select an unrelated browser tab.
- A confirmed application must not be offered or submitted again.

## Historical evidence

Historical Ashby dry-run/certification work is useful regression context but is not accepted as proof of the current Android/native-Chrome runtime. Certification evidence must be produced against the current mainline architecture.

## Completion evidence

Record the application id, Ashby target, confirmation evidence type/final URL, persisted JobTomatik status, and duplicate-suppression result after the real run. Only then may this document and the adapter certification metadata be changed from IN PROGRESS to CERTIFIED.

# Lever Phase A locked-corpus sweep, July 31, 2026

## Verdict

The requested “20th qualifying run” was **not produced** because the repository does not contain 19 canonically retained qualifying runs. The canonical count remains **0/30**.

Owner reporting was not credited.

## Full locked-corpus result

All **39 viable distinct targets** in the frozen Day 8 corpus are accounted for:

- 38 targets were freshly exercised in GitHub Actions runs `30604029853` and `30604351125`.
- D8-043 was already retained as a verified EU manual-challenge boundary in run `30337038142`.
- **0** targets reached `ready_to_submit`.
- **33** targets stopped at a CAPTCHA or human-verification boundary.
- **3** targets stopped on an ambiguous required question, with CAPTCHA also present.
- **3** targets exposed no supported next-step or final-submit control.
- **0** final-submit clicks occurred.

Every boundary remains nonqualifying under measurement contract `2026-07-31.day8.4`.

## Checkpoint reconciliation

| Checkpoint | Required | Canonical | Result |
|---|---:|---:|---|
| Day 9 | 5 | 0 | Blocked |
| Day 10 | 10 | 0 | Blocked |
| Day 11 | 15 | 0 | Blocked |
| Day 12 | 20 | 0 | Blocked |

Lever maturity remains `dry_run`. Promotion readiness remains false. Real submission, the Lever supervised pilot, autopilot, and maturity promotion remain disabled.

## Retained provenance

- Run `30604029853`, artifact `8783020519`, digest `515d95a6fd012c1ac931c61652f6945e668f15bc454d2b9cbb3dfc92881684e3`
- Run `30604351125`, artifact `8783248871`, digest `cae1d5ecaa03510f3ea2ac32246ce4358633eaadae39b690dc023814166210e9`
- Existing D8-043 boundary: run `30337038142`, artifact `8679562746`, digest `c72bf99c62394393ef98100f3c5deee2b6bdcaa839d163bd0d9dc03a60d711e2`

The accompanying JSON retains the categorized target index and a SHA-256 digest of the complete normalized target-level manifest. The individual reports and their hashes are retained in the source workflow artifacts.

## Locked artifact regeneration

The Phase A baseline did not change, so regenerated readiness and campaign checkpoint outputs must remain byte-identical to the committed locked artifacts. CI regenerates:

- `lever-pilot-readiness.json`
- `lever-pilot-readiness.md`
- `campaign-days-12-22.json`

and fails unless all three match the committed outputs.

## Smallest truthful next action

Complete the human-verification boundary on one exact locked target without clicking final submit, resume until the form reaches `ready_to_submit`, and retain the exact inspection and exercise artifact. The alternative is a separately reviewed corpus or measurement-contract change. Neither may be inferred from an owner comment.

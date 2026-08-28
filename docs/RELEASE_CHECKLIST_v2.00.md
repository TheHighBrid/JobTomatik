# JobTomatik v2.00 Release Checklist

> **Pre-release checklist.** No checkbox in this file substitutes for retained machine-readable evidence. Do not mark an item complete because the corresponding code or CI tooling exists.

## 1. Exact release candidate

- [ ] Final release commit is a valid 40-character SHA.
- [ ] Final release commit equals current `main`.
- [ ] No code or release-document change occurred after the final exact-head workflow matrix.
- [ ] Day 41 audit candidate revision equals the final release commit.
- [ ] Final maturity-manifest revision equals the final release commit.

**Evidence references:**

- Final release commit:
- Day 41 report SHA-256:
- Final exact-head matrix SHA-256/reference:
- Maturity manifest SHA-256/reference:

## 2. Day 38 shadow prerequisite

- [ ] Genuine physical 24-hour Day 38 endurance report passed.
- [ ] Persisted elapsed duration satisfies the strict 24-hour contract.
- [ ] Retained report hash is valid.
- [ ] Required quiet-hour transition evidence passed.
- [ ] Required rolling previous-24-hour membership rollover evidence passed.
- [ ] Zero duplicate tasks/application references.
- [ ] Zero false submitted status.
- [ ] Zero policy escapes.
- [ ] Real submission and real follow-up remained disabled throughout the shadow campaign.
- [ ] Day 39 entry eligibility is true.

**Evidence references:**

- Day 38 session/campaign:
- Day 38 report SHA-256:
- Physical Android runtime revision:

## 3. Day 39 exact-head promotion and bounded first wave

- [ ] Post-shadow promotion report passed on the exact promoted revision.
- [ ] Separate owner promotion approval is retained.
- [ ] Lever maturity is `certified_autonomous` only if the strict promotion report authorizes it.
- [ ] Separate bounded live-window owner authorization is retained.
- [ ] Live authorization is bound to Lever 1.1.0 and the exact runtime revision.
- [ ] Attempt cap and authorization window are within the release contract.
- [ ] First live wave completed without a critical defect.
- [ ] Zero duplicate submissions.
- [ ] Zero false-positive submission status.
- [ ] Zero wrong-target or guessed-required-answer event.
- [ ] Any uncertain outcome was reconciled without silent retry.

**Evidence references:**

- Promotion report SHA-256:
- Promotion approval reference:
- First-wave authorization ID/reference:
- First-wave certification/report SHA-256:

## 4. Day 40 second wave

- [ ] Day 40 admission confirms the first wave is clean.
- [ ] Second live wave remained within its separate bounded authorization.
- [ ] Queue prioritization was exercised.
- [ ] Production cap enforcement was exercised.
- [ ] Follow-up scheduling was exercised without implicitly authorizing real follow-up send.
- [ ] Platform/portal/email confirmation reconciliation was exercised where available.
- [ ] Zero duplicate submissions across both live waves.
- [ ] Zero false-positive submitted state across both live waves.
- [ ] Live window is closed after the wave.
- [ ] Real submission and real follow-up are disabled after the wave.
- [ ] Day 41 entry eligibility is true.

**Evidence references:**

- Day 40 authorization/reference:
- Day 40 report SHA-256:

## 5. Day 41 offline release audit

- [ ] Live mode is disabled before and during the audit.
- [ ] Exact-head release workflow matrix passed.
- [ ] Data-integrity audit passed.
- [ ] Security audit and CodeQL passed.
- [ ] Privacy audit passed.
- [ ] Dependency verification passed.
- [ ] `pip check` passed.
- [ ] Production npm audit passed.
- [ ] Migration smoke test passed.
- [ ] Android candidate verification passed.
- [ ] Release-provenance verification passed.
- [ ] Source/artifact secret scan passed.
- [ ] Test-only release-verification secrets were rotated as required.
- [ ] No production secret exists in source or release artifacts.

### Recovery and compatibility drills

- [ ] Rollback drill passed with retained report hash.
- [ ] Kill-switch drill passed with retained report hash.
- [ ] Non-destructive database restore drill passed with retained report hash.
- [ ] Frozen-v1 compatibility drill passed from source `6f7f9fa6a7d3c63516cde381410ac188364dba36` with retained report hash.
- [ ] Previous v1 tables and columns are preserved through candidate migration.
- [ ] Synthetic v1 sentinel survives migration and is readable by the current ORM.

**Evidence references:**

- Rollback report SHA-256:
- Kill-switch report SHA-256:
- Database restore report SHA-256:
- Frozen-v1 compatibility report SHA-256:

## 6. Release documents

- [ ] `README.md` reflects the truthful v2.00 autonomy scope.
- [ ] `CHANGELOG.md` contains the final v2.0.0 release entry.
- [ ] `docs/RELEASE_NOTES_v2.00.md` is final and no longer labeled pre-release.
- [ ] `docs/KNOWN_BOUNDARIES_v2.00.md` matches the exact final maturity manifest.
- [ ] `docs/OPERATOR_GUIDE_v2.00.md` is final.
- [ ] `docs/operations/recovery-incident-response.md` remains accurate for v2 operation.
- [ ] Day 41 and Day 42 runbooks match the implemented workflows.

**Review reference:**

## 7. Exact prepublication Android candidate

- [ ] Candidate was built by `.github/workflows/build-v2-release-candidate.yml`.
- [ ] Candidate workflow event is `workflow_dispatch`.
- [ ] Candidate workflow conclusion is `success`.
- [ ] Candidate workflow head SHA equals the final release commit.
- [ ] Candidate workflow run ID is retained.
- [ ] Candidate APK source revision equals the final release commit.
- [ ] APK SHA-256 is valid and retained.
- [ ] Package name is `ca.jobtomatik.app`.
- [ ] Version name is `2.0.0`.
- [ ] Version code is `200`.
- [ ] Signing certificate output is retained.
- [ ] Signing mode is exactly `release_signed` or `development_signed`.
- [ ] Candidate metadata says `publication_authorized=false`.
- [ ] Candidate build did not create a Git tag or GitHub release.

**Candidate identity:**

- Candidate workflow run ID:
- APK SHA-256:
- Build identity SHA-256:
- Signing certificate SHA-256:
- Signing mode:

## 8. Day 42 exact-artifact readiness

- [ ] Day 41 report passed and sets `day42_entry_eligible=true`.
- [ ] Final exact-head workflow matrix passed on the same release commit.
- [ ] Day 42 tooling gate passed on that exact commit.
- [ ] Repository `main` still equals the approved release commit.
- [ ] `v2.0.0` tag does not already exist.
- [ ] `v2.0.0` GitHub release/assets do not already exist.
- [ ] Candidate source revision, workflow run ID, APK SHA-256, and signing identity are exact.
- [ ] Maturity manifest is truthful and exact to the release commit.
- [ ] Real submission default is fail-safe.
- [ ] Real follow-up default is fail-safe.
- [ ] Separate owner publication authorization binds the exact source commit, APK SHA-256, and candidate workflow run ID.
- [ ] Owner acknowledgment is exact.
- [ ] Day 42 readiness report sets `publication_eligible=true` while `publication_executed=false`.

**Evidence references:**

- Day 42 report SHA-256:
- Owner publication approval reference:
- Exact publication acknowledgment:

## 9. Publication

- [ ] Owner invokes `.github/workflows/publish-v1-command.yml` with the exact authorized inputs.
- [ ] Publisher verifies the candidate workflow identity through the GitHub Actions API.
- [ ] Publisher downloads the artifact from the exact approved candidate run ID.
- [ ] Publisher verifies the downloaded APK SHA-256 equals the owner-approved hash.
- [ ] Publisher does not rebuild the APK.
- [ ] Publisher rechecks current `main` immediately before publication.
- [ ] Publisher rechecks `v2.0.0` tag absence immediately before publication.
- [ ] Release target commit is the exact approved SHA, not moving `main`.
- [ ] Asset overwrite remains disabled.

## 10. Independent post-publication verification

- [ ] Git tag `v2.0.0` exists and resolves to the approved release commit.
- [ ] GitHub release target resolves to the approved release commit.
- [ ] Published APK SHA-256 equals the approved candidate hash.
- [ ] Published `SOURCE-COMMIT.txt` equals the approved release commit.
- [ ] Published `CANDIDATE-METADATA.json` contains the approved candidate run ID.
- [ ] Published signing identity matches the reviewed candidate signing identity.
- [ ] Published `DAY42-READINESS-SHA256.txt` equals the passing readiness report.
- [ ] README, CHANGELOG, release notes, known boundaries, and maturity manifest agree.
- [ ] No publication step changed adapter maturity.
- [ ] No unexpected real submission or real follow-up sending was enabled by publication.

## Final release decision

- Release version: `v2.0.0`
- Exact source commit:
- APK SHA-256:
- Candidate workflow run ID:
- Day 41 report SHA-256:
- Day 42 report SHA-256:
- Final checklist SHA-256:
- Review reference:
- Publication run ID:
- Post-publication verification reference:

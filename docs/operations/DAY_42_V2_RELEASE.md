# Day 42: Ship JobTomatik v2.00

Day 42 is the final exact-commit and exact-artifact publication gate. The release path is intentionally split into three independent stages:

1. build one exact-commit prepublication APK candidate;
2. generate a read-only Day 42 publication-readiness report bound to that exact candidate workflow run and APK SHA-256;
3. invoke a separate owner-only publisher that downloads and publishes those exact prebuilt bytes without rebuilding them.

A green CI run on the preparatory branch is not a release. The readiness evaluator cannot create a tag or GitHub release, and the candidate builder cannot publish.

## Entry prerequisite

Day 41 must first produce a strict release-candidate audit with:

- `passed=true`;
- `day42_entry_eligible=true`;
- exact candidate revision;
- retained Day 41 report SHA-256;
- live mode disabled;
- release-candidate workflow matrix green;
- recovery drills passed;
- candidate APK identity and signing mode verified;
- release checklist reviewed;
- publication and tag authorization still false.

Any code change after the Day 41 audit invalidates the final exact-head matrix until the affected release gates are rerun on the new commit.

## Final exact-head workflow matrix

Before publication, run the exact release commit through every required release workflow. The Day 42 readiness report requires the matrix `revision`, matrix `current_head`, repository `main_revision`, Day 41 candidate revision, maturity-manifest revision, and APK source revision to all identify the same exact 40-character commit.

Required final workflow results include:

- Backend tests;
- Post-merge stabilization;
- Reproducible verification;
- CodeQL security analysis;
- Current-head end-to-end acceptance;
- Android runtime dispatch acceptance;
- Runtime revision attestation;
- Android static frontend artifact;
- Android APK;
- Certification and scale;
- Submission evidence review certification;
- Full-stack shadow campaigns;
- Day 39 live-window tooling gate;
- Day 40 second-wave tooling gate;
- Day 41 release-audit tooling gate;
- Day 42 publish-readiness tooling gate.

Do not combine results from different candidate commits into one final matrix.

## Truthful autonomy scope

For the planned v2.0.0 release, the maturity manifest must truthfully state the final audited scope:

| Adapter | Version | Maturity | Autonomous submission |
| --- | --- | --- | --- |
| Lever | 1.1.0 | `certified_autonomous` | true |
| Greenhouse | 1.1.1 | `dry_run` | false |
| Ashby | 1.1.0 | `dry_run` | false |
| SmartRecruiters | 1.1.0 | `detect_only` | false |
| Workday | 1.1.0 | `detect_only` | false |

Real submission and real follow-up must remain fail-safe by default in the release configuration. If the audited maturity changes before release, update the release contract and rerun the affected gates rather than publishing stale claims.

## Stage 1: build the exact prepublication candidate

The controlled workflow is:

`.github/workflows/build-v2-release-candidate.yml`

It accepts:

- exact current `main` source commit;
- retained Day 41 audit reference.

The workflow must verify that the supplied commit equals current `origin/main`, detach to that exact SHA, build the APK, verify package/version/signing identity, and upload one immutable candidate artifact. It must not publish a release or create a tag.

The retained candidate must include:

- `JobTomatik-v2.00.apk`;
- `JobTomatik-v2.00.sha256`;
- `SOURCE-COMMIT.txt`;
- `BUILD-INFO.txt`;
- `APK-BADGING.txt`;
- `APK-SIGNING.txt`;
- `CANDIDATE-METADATA.json`.

Candidate metadata must record:

- exact source revision;
- exact APK SHA-256;
- explicit `release_signed` or `development_signed` signing mode;
- Day 41 audit reference;
- exact candidate workflow run ID;
- `publication_authorized=false`.

A development-signed artifact must be labeled `development_signed` everywhere it is surfaced. Do not describe it as production-signed merely because it is a final candidate.

## Candidate identity supplied to the Day 42 evaluator

The machine-readable candidate identity must include:

- exact source revision;
- APK SHA-256;
- build-identity SHA-256;
- signing-certificate SHA-256;
- explicit signing mode;
- exact candidate workflow run ID;
- workflow path `.github/workflows/build-v2-release-candidate.yml`;
- workflow conclusion `success`;
- reproducible-build proof;
- source-commit file present;
- checksums file present;
- build-info file present;
- candidate metadata present;
- `publication_authorized=false`.

The candidate run ID is authority-relevant. A different workflow run cannot silently replace the approved candidate even if it claims the same source revision.

## Repository state before publication

Immediately before owner authorization and again inside the hardened publisher:

- repository `main` must equal the approved exact commit;
- tag `v2.0.0` must not already exist;
- a `v2.0.0` GitHub release must not already exist;
- release assets for that tag must not already exist.

The publisher must fail instead of overwriting an existing tag or release.

## Release documents

Before publication:

- README must show the truthful v2 autonomy scope;
- CHANGELOG must contain the v2.0.0 release entry;
- release notes must be final;
- known boundaries must be final;
- operator guide must be final;
- incident runbook must be final.

## Exact owner publication authorization

Publication requires a separate approval bound to the exact source commit, exact APK SHA-256, and exact candidate workflow run ID.

The acknowledgment is:

```text
PUBLISH JOBTOMATIK V2.0.0 <REVISION12> <APK_SHA256_12>
```

The owner authorization supplied to the Day 42 evaluator must also bind:

- release version `v2.0.0`;
- release tag `v2.0.0`;
- exact 40-character source revision;
- exact 64-character APK SHA-256;
- exact positive candidate workflow run ID;
- non-empty approval reference.

## Stage 2: read-only publication readiness

Build the final readiness report using retained machine-readable inputs:

```bash
cd backend
python scripts/build_day42_publish_readiness.py \
  --day41-audit <DAY41_AUDIT_JSON> \
  --final-release-matrix <FINAL_EXACT_HEAD_MATRIX_JSON> \
  --candidate-artifact <FINAL_CANDIDATE_IDENTITY_JSON> \
  --maturity-manifest <FINAL_MATURITY_MANIFEST_JSON> \
  --repository-release-state <REPOSITORY_RELEASE_STATE_JSON> \
  --release-documents <RELEASE_DOCUMENTS_JSON> \
  --owner-authorization <OWNER_PUBLICATION_AUTHORIZATION_JSON>
```

A valid final result is:

```json
{
  "publication_eligible": true,
  "publication_executed": false,
  "release_tag_created": false,
  "github_release_created": false
}
```

Retain the exact `report_sha256`. That output is permission to invoke the separate publisher. It is not proof that publication occurred.

## Stage 3: hardened exact-artifact publisher

The controlled publisher is:

`.github/workflows/publish-v1-command.yml`

It is owner-invoked through `workflow_dispatch` and requires:

- exact source commit;
- exact candidate workflow run ID;
- exact approved APK SHA-256;
- exact passing Day 42 readiness report SHA-256;
- non-empty authorization reference;
- exact publication acknowledgment.

The publisher must:

- require the approved source SHA to equal current `origin/main`;
- query the candidate workflow run through the GitHub Actions API;
- require workflow path `.github/workflows/build-v2-release-candidate.yml`;
- require event `workflow_dispatch` and conclusion `success`;
- require the candidate run head SHA to equal the approved source commit;
- download the candidate artifact from that exact workflow run ID;
- verify the downloaded APK SHA-256 equals the owner-approved APK SHA-256;
- verify `SOURCE-COMMIT.txt`, candidate metadata, package name, version, and signing certificate;
- require candidate metadata workflow run ID to equal the approved run ID;
- require canonical signing mode `release_signed` or `development_signed`;
- never rebuild the APK after owner approval;
- recheck `origin/main` and tag absence immediately before publication;
- use the exact SHA as GitHub release `target_commitish`;
- refuse release-asset overwrite;
- publish the exact verified prebuilt APK and its provenance files.

The retained release bundle also records the exact Day 42 readiness SHA-256. The publisher treats that value as part of the explicit owner authorization trail; publication does not replace the need to retain and independently review the passing readiness report.

After publication, independently verify the created tag, release target, uploaded APK checksum, source-commit file, build info, signing identity, candidate metadata, Day 42 readiness hash, README/CHANGELOG state, and truthful maturity manifest.

## CI boundary

The Day 42 tooling gate must always retain a non-publication state:

```json
{
  "real_day42_release_claimed": false,
  "publication_eligible_from_ci": false,
  "publication_executed": false,
  "release_tag_created": false,
  "github_release_created": false,
  "main_modified": false,
  "publisher_rebuilds_approved_apk": false
}
```

CI prepares and tests the lock. The final exact owner action turns the key only after the genuine Day 41 audit, exact candidate build, final matrix, and Day 42 readiness report all pass.

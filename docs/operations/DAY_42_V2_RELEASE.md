# Day 42: Ship JobTomatik v2.00

Day 42 is the final exact-commit publication gate. It is intentionally split into two parts:

1. a read-only publication-readiness report;
2. a separate hardened owner-invoked publisher.

The readiness evaluator never creates a tag, GitHub release, or APK. A green CI run on this preparatory branch is not a release.

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
- Day 41 release-audit tooling gate.

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

## Final APK identity

The publication candidate must retain:

- exact source revision;
- APK SHA-256;
- build-identity SHA-256;
- signing-certificate SHA-256;
- explicit `release_signed` or `development_signed` signing mode;
- reproducible-build proof;
- `SOURCE-COMMIT.txt`;
- checksums file;
- build-information file.

A development-signed artifact must be labeled as development-signed everywhere it is surfaced. Do not call it production-signed because the calendar reached Day 42.

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

Publication requires a separate approval bound to both the exact source commit and exact APK SHA-256.

The acknowledgment is:

```text
PUBLISH JOBTOMATIK V2.0.0 <REVISION12> <APK_SHA256_12>
```

The owner authorization must also bind:

- release version `v2.0.0`;
- release tag `v2.0.0`;
- exact 40-character source revision;
- exact 64-character APK SHA-256;
- non-empty approval reference.

## Read-only publication readiness

Build the final readiness report using retained machine-readable inputs:

```bash
cd backend
python scripts/build_day42_publish_readiness.py \
  --day41-audit <DAY41_AUDIT_JSON> \
  --final-release-matrix <FINAL_EXACT_HEAD_MATRIX_JSON> \
  --candidate-artifact <FINAL_APK_IDENTITY_JSON> \
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

That output is permission to invoke the separate publisher. It is not proof that publication occurred.

## Hardened publisher

The final publisher must use the hardened Android release-provenance workflow prepared separately. It must:

- be explicitly owner-invoked;
- accept an exact approved source SHA and authorization reference;
- require the approved SHA to equal `origin/main` before building;
- rebuild/verify the final APK on that exact SHA;
- retain source commit, checksums, build info, badging, and signing certificate output;
- recheck `origin/main` immediately before publication;
- refuse an existing `v2.0.0` tag;
- use the exact SHA as GitHub release `target_commitish`;
- refuse release-asset overwrite.

After publication, independently verify the created tag, release target, uploaded APK checksum, source-commit file, build info, signing identity, README/CHANGELOG state, and truthful maturity manifest.

## CI boundary

The Day 42 tooling gate must always retain a non-publication state:

```json
{
  "real_day42_release_claimed": false,
  "publication_eligible_from_ci": false,
  "publication_executed": false,
  "release_tag_created": false,
  "github_release_created": false,
  "main_modified": false
}
```

CI prepares the lock. The final exact owner action turns the key.

# Day 42: JobTomatik v2.1.0 exact-artifact release gate

Day 42 is the final publication decision. It is intentionally split into preparation, read-only readiness evaluation, and a separate owner-authorized publisher.

## Required evidence

Publication readiness requires all of the following on one exact current `main` commit:

- a passing Day 41 release-candidate audit with `day42_entry_eligible=true`;
- the final required workflow matrix passing on that exact commit;
- the exact prebuilt APK from `.github/workflows/build-v2-release-candidate.yml`;
- retained APK SHA-256, signing-certificate SHA-256, build identity, workflow run ID, and source revision;
- truthful final adapter maturity and autonomy scope;
- `ALLOW_REAL_APPLICATION_SUBMIT` and real follow-up defaults remaining fail-safe;
- no existing `v2.1.0` tag, GitHub Release, or release asset set;
- release documentation finalized;
- a separate owner authorization bound to the exact commit, APK SHA-256, and candidate workflow run ID.

The exact acknowledgment format is:

```text
PUBLISH JOBTOMATIK V2.1.0 <REVISION12> <APK_SHA256_12>
```

## Three-stage release architecture

1. `build-v2-release-candidate.yml` checks out the exact current-main SHA, builds one candidate, records its source/hash/signing identity, and uploads it. It has read-only repository permissions and cannot publish.
2. `build_day42_publish_readiness.py` evaluates Day 41 evidence, the final workflow matrix, candidate provenance, maturity scope, repository state, documentation, and owner authorization. It cannot publish or create a tag.
3. `publish-v1-command.yml` is an owner-only manual workflow. It downloads the exact approved candidate from the approved workflow run, re-verifies its bytes and source, rechecks that `main` has not moved and `v2.1.0` does not exist, then publishes those exact prebuilt bytes. It does not rebuild the APK.

## Safety boundary

A green Day 42 tooling workflow is not a release. CI records `publication_executed=false`, `release_tag_created=false`, and `github_release_created=false`.

Do not create publication authorization from test fixtures, CI output, inferred intent, or a previous release approval. The owner approval must be explicit and exact-artifact bound.

Publication does not itself grant application-submission authority or change adapter maturity. Those controls remain independently governed by the certified-adapter and runtime policy contracts.

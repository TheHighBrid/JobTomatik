# Phase 12: Runtime Revision Attestation

## Purpose

Phase 11 made it possible to collect real 4-hour, 8-hour, and 24-hour full-stack no-submit shadow evidence. Phase 12 makes sure that evidence can prove **which exact JobTomatik commit actually ran it**.

This closes a concrete deployment gap. Phase 10's `current_revision()` correctly returns `unknown` rather than inventing a commit when no identity is available. In Docker Compose, however, the backend source is mounted as `./backend:/app`; the repository `.git` directory is normally not present inside `/app`. Before Phase 12, API/worker/beat also did not receive `JOBTOMATIK_RUNTIME_REVISION` through Compose. A production-like shadow campaign could therefore be unable to establish an exact candidate revision even though its application logic was healthy.

The Android/Ubuntu PRoot reference setup had the complementary problem: the repository does contain `.git`, but the documented Uvicorn/Celery commands did not stamp that commit into a shared expected/runtime identity before launch. Phase 12 gives both deployment styles the same contract.

The Phase 12 rule is:

> A sensitive JobTomatik runtime must know the exact commit it is running, know the exact commit it was expected to run, and prove those values are identical before it begins consequential or certification-relevant operation.

Runtime identity is evidence only. It never grants permission to submit an application, contact a recruiter, promote an ATS adapter, verify certification evidence, or authorize a release.

## Identity values

Two deployment values form the attestation:

```text
JOBTOMATIK_RUNTIME_REVISION=<exact commit SHA>
JOBTOMATIK_EXPECTED_REVISION=<same exact commit SHA>
```

Each process also carries a bounded role:

```text
JOBTOMATIK_RUNTIME_ROLE=api
JOBTOMATIK_RUNTIME_ROLE=worker
JOBTOMATIK_RUNTIME_ROLE=beat
```

CI uses `ci`. Unsupported role values are normalized to `unknown` rather than being reflected as arbitrary input.

The runtime revision resolver checks, in order:

1. `JOBTOMATIK_RUNTIME_REVISION`;
2. `GITHUB_SHA`;
3. `git rev-parse HEAD` for a local checkout;
4. `unknown`.

A revision is accepted only when it is hexadecimal and 7 to 64 characters long.

`deployment_attested=true` requires all of the following:

- a known runtime revision;
- an explicitly configured expected revision;
- a syntactically valid expected revision;
- exact equality between runtime and expected revision.

Merely being inside a git checkout is therefore enough to make the revision observable, but it is **not** enough to claim deployment attestation.

## Sensitive-runtime startup gate

`backend/scripts/check_runtime_identity.py` is executed before protected API, Celery worker, and Celery beat launch paths.

With `--require-sensitive`, attestation becomes mandatory when any of these are true:

- `APP_ENV=production`;
- `AUTOPILOT_ENABLED=true`;
- `ALLOW_REAL_APPLICATION_SUBMIT=true`;
- `ALLOW_REAL_FOLLOWUP_SEND=true`;
- `GREENHOUSE_SUPERVISED_PILOT_ENABLED=true`;
- `LEVER_SUPERVISED_PILOT_ENABLED=true`.

If a sensitive runtime does not have matching exact revisions, the checker exits with status `2` before Uvicorn or Celery starts.

Non-sensitive local development remains usable without attestation. That preserves ordinary development workflows without letting an unattested runtime masquerade as certification-ready.

## Revision-stamped Compose launch

For a repository checkout using Docker, use:

```bash
bash scripts/jobtomatik-compose.sh up -d
```

The launcher:

1. derives `git rev-parse HEAD` unless `JOBTOMATIK_RUNTIME_REVISION` is already supplied;
2. validates the revision;
3. exports it as `JOBTOMATIK_RUNTIME_REVISION`;
4. defaults `JOBTOMATIK_EXPECTED_REVISION` to that same value;
5. fails if the two values differ;
6. invokes Docker Compose.

To inspect the rendered deployment without starting it:

```bash
bash scripts/jobtomatik-compose.sh config
```

API, worker, and beat receive the same exact revision and expected revision, while their roles remain distinct.

## Revision-stamped Android / Ubuntu PRoot launch

The Android-first reference runtime can use the repository launcher directly from `/root/JobTomatik`:

API terminal:

```bash
cd /root/JobTomatik
bash scripts/jobtomatik-runtime.sh api
```

Worker terminal:

```bash
cd /root/JobTomatik
bash scripts/jobtomatik-runtime.sh worker
```

Optional beat terminal:

```bash
cd /root/JobTomatik
bash scripts/jobtomatik-runtime.sh beat
```

The launcher:

- derives the revision with `git -C /root/JobTomatik rev-parse HEAD` through its repository-root calculation;
- sets the same value as the expected revision unless an expected revision was supplied explicitly;
- assigns the appropriate `api`, `worker`, or `beat` role;
- uses `backend/.venv/bin/python` when available;
- runs the sensitive-runtime checker before the process starts;
- launches Uvicorn on `127.0.0.1:8010` for the API;
- launches the Android reference solo Celery worker with the established queues.

This is the recommended launcher when collecting real shadow evidence on the Android/PRoot runtime. The older direct `uvicorn` and `celery` commands remain suitable only for non-sensitive development where no deployment-attestation claim is being made.

## Read-only runtime identity API

Phase 12 adds:

```text
GET /api/system/runtime-identity
```

The response contains:

- identity contract version;
- current revision;
- revision source;
- process role;
- whether the revision is known;
- expected revision;
- expected-value validity;
- exact-match result;
- `deployment_attested`;
- SHA-256 of the canonical identity payload;
- `submission_authorized=false`;
- `outreach_authorized=false`.

`/api/system/operations-readiness` also includes the same `runtime_identity` snapshot. Neither endpoint changes runtime state.

## Shadow campaign gate

Phase 11 already requires `AUTOPILOT_ENABLED=true` for a real full-stack campaign. Phase 12 uses that fact as the certification boundary.

When autopilot is enabled:

- Shadow Campaign preflight requires `deployment_attested=true`;
- an unattested preflight adds `runtime_identity_unattested`;
- the expected START acknowledgment is withheld;
- `POST /api/shadow-runs` returns HTTP 409 before creating a session;
- the Celery shadow worker independently checks attestation before executing a cycle;
- stalled-session recovery checks the same condition before redispatch.

This is defense in depth. Skipping the recommended launchers and manually starting a process does not bypass the shadow-campaign identity requirement.

When autopilot is disabled, deterministic unit tests and ordinary non-sensitive development can still exercise local service logic without claiming a production deployment attestation.

## Phase 10 identity consistency

Phase 10 certification already prefers `JOBTOMATIK_RUNTIME_REVISION` before GitHub or local-git fallbacks. Phase 12 regression tests prove that, when an explicit deployment revision is supplied, the Phase 10 certification revision and Phase 12 runtime identity resolve to the same SHA.

A mismatched expected SHA does **not** change Phase 10's observed runtime SHA. Instead, Phase 12 marks the deployment unattested and prevents it from entering the real shadow path.

## Android artifact and release identity

The normal Android APK workflow binds each build to `${{ github.sha }}` and retains:

```text
SOURCE-COMMIT.txt
```

next to the debug APK and SHA-256 checksum. That artifact is build evidence only. The normal Android workflow has read-only repository permissions and cannot create a tag or GitHub Release.

Public `v2.1.0` publication uses a separate explicit owner-command workflow. That workflow:

1. checks out current `main` only after owner authorization;
2. freezes `RELEASE_SOURCE_SHA` from that exact checkout before building;
3. builds and identity-checks the APK from that frozen source;
4. writes the same SHA to `SOURCE-COMMIT.txt` and `BUILD-INFO.txt`;
5. fetches `origin/main` again immediately before publication and fails if it moved;
6. refuses to overwrite an existing `v2.1.0` tag or release;
7. creates the immutable tag with `target_commitish` equal to the exact frozen source SHA.

This prevents a PR merge-ref, later workflow context, or moved main branch from being substituted for the source that produced the published APK.

The Android artifact contract remains separate from runtime submission authority.

## Pre-run checklist for the first real 4-hour campaign

Before starting the 4-hour clock:

1. Check out the exact candidate commit intended for certification in the runtime repository.
2. Start the runtime through the appropriate revision-stamped launcher:

   Docker:

   ```bash
   bash scripts/jobtomatik-compose.sh up -d
   ```

   Android/Ubuntu PRoot:

   ```bash
   bash scripts/jobtomatik-runtime.sh api
   bash scripts/jobtomatik-runtime.sh worker
   ```

3. Confirm:

   ```text
   GET /api/system/runtime-identity
   ```

   reports:
   - `known=true`;
   - `deployment_attested=true`;
   - `revision == expected_revision`;
   - role `api` for the API process.

4. Confirm `/api/system/operations-readiness` carries the same revision.
5. Confirm Shadow Campaign preflight reports `runtime_identity_attested=true`.
6. Confirm `ALLOW_REAL_APPLICATION_SUBMIT=false` and `ALLOW_REAL_FOLLOWUP_SEND=false`.
7. Only then use the exact Phase 11 START acknowledgment and begin the measured campaign.

If any revision changes while a Phase 11 campaign is running, the existing candidate-revision invariant fails the campaign closed.

## CI coverage

`.github/workflows/runtime-revision-attestation.yml` proves:

- exact runtime/expected revision matching;
- malformed and mismatched revisions fail attestation;
- sensitive autopilot runtime cannot launch unattested;
- ordinary non-sensitive development remains usable;
- API/worker/beat receive one exact revision through rendered Compose;
- all three Compose processes run the startup checker;
- the Android/PRoot launcher derives repository HEAD, assigns a bounded role, and invokes the same startup checker;
- runtime identity endpoints grant no submission/outreach authority;
- an unattested shadow API cannot create a campaign;
- a direct unattested shadow-worker invocation cannot execute a cycle;
- Android build artifacts retain `SOURCE-COMMIT.txt`;
- consequential runtime defaults remain false.

The inherited Phase 11 workflow also runs the identity-bypass regressions with an exact CI attestation.

## What Phase 12 does not claim

Phase 12 does not itself run a real 4-hour, 8-hour, or 24-hour campaign. It prevents those future campaigns from being wasted on an unprovable runtime identity.

It does not claim:

- real shadow-duration evidence exists;
- certification evidence is independently verified;
- the autonomous-pilot gate is satisfied;
- an ATS adapter is autonomous;
- the Android artifact has been accepted on a physical device;
- v2.1.0 is published;
- owner authorization has occurred.

Those gates remain independent and fail closed until their real evidence exists.

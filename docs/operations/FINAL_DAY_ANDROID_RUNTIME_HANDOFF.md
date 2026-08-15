# Final-Day Android Runtime Handoff

This runbook validates the **exact merged JobTomatik revision** on an account-owned Android/Termux runtime. It is a deployment-attestation and no-submit readiness procedure only. It does **not** authorize an ATS promotion, recruiter outreach, application submission, or a duration shadow campaign.

## Preconditions

The candidate must be the current `main` revision after pull request checks are green and the pull request is reviewed and merged. Do not run this procedure from a feature branch, a dirty checkout, or a mixed-revision runtime. The device must be able to reach GitHub and must keep Termux-native Chromium available only on loopback at `127.0.0.1:9222`.

The managed runtime requires a Python virtual environment at `backend/.venv`. The static frontend is retrieved from the repository's SHA-bound artifact branch, so no device-side Node/Vite build is required.

| Boundary | Required state |
|---|---|
| Candidate source | Clean `main` checkout at one immutable Git SHA |
| API, worker, Beat, frontend | Attested to that same SHA |
| Browser CDP | Termux-native Chromium at `127.0.0.1:9222`; never exposed to the LAN or internet |
| Real application submission | `false` |
| Recruiter/follow-up sending | `false` |
| Autopilot | Leave disabled for this validation run |

## 1. Pin the exact candidate

Run the following in the Ubuntu/proot shell that owns the JobTomatik checkout. The output from `git status --short` must be empty before continuing.

```bash
cd ~/JobTomatik
git fetch origin
git checkout main
git pull --ff-only origin main
git status --short

CANDIDATE_SHA="$(git rev-parse HEAD)"
printf 'JobTomatik candidate: %s\n' "$CANDIDATE_SHA"
export JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA"

bash scripts/verify.sh device
```

The device audit is read-only. It should report an Android/Termux or Ubuntu/proot profile and a recommended validation lane; it never enables submission, outreach, autopilot, or adapter promotion.

## 2. Preserve the no-submit configuration

Review `backend/.env` before starting the managed stack. Set or retain these values. Use a valid, device-private `SECRET_KEY`; do not commit it or share it in a receipt.

```env
APP_ENV=production
ALLOW_REAL_APPLICATION_SUBMIT=false
ALLOW_REAL_FOLLOWUP_SEND=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
LEVER_SUPERVISED_PILOT_ENABLED=false
ENABLE_RESUMABLE_HANDOFFS=false
AUTOPILOT_ENABLED=false
```

The managed Android startup routine uses Redis DB 1, configures the external browser endpoint as `http://127.0.0.1:9222`, and verifies the runtime identity before admitting API, worker, Beat, or the static frontend.

## 3. Install the SHA-bound static frontend and start the managed stack

```bash
cd ~/JobTomatik/backend
./.venv/bin/python scripts/install_android_static_frontend_artifact.py \
  --revision "$CANDIDATE_SHA"

JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  bash scripts/manage_android_stack.sh start

JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  bash scripts/manage_android_stack.sh status
```

The frontend installer must print `ANDROID_STATIC_FRONTEND_ARTIFACT_READY` with the exact candidate SHA. If the exact artifact has not yet been published, wait for the matching artifact workflow rather than substituting a locally built or stale frontend.

The status command must report all of the following before the final acceptance command:

```text
API: READY_ATTESTED
FRONTEND: READY_STATIC_ATTESTED
CELERY: READY applications,celery,followup,scraping
CELERY_APPLICATION_CANARY: STARTUP_RECEIPT_ATTESTED
CELERY_BEAT: READY_ATTESTED
ANDROID_BROWSER_CDP: READY
ANDROID_RUNTIME_BROKER: ISOLATED
ANDROID_RUNTIME_ATTESTATION: READY
```

Any `DOWN`, `UNMANAGED`, `STALE`, `UNATTESTED`, `FAILED`, or `NOT_ISOLATED` marker is a blocker. Do not start a shadow campaign or application workflow; retain the output and inspect the relevant log in `backend/.runtime/logs/`.

## 4. Record the physical acceptance receipt

```bash
cd ~/JobTomatik/backend
JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  ./.venv/bin/python scripts/android_runtime_acceptance_base.py
```

A passing run prints:

```text
ANDROID_RUNTIME_ACCEPTANCE=PASS revision=<candidate SHA> fingerprint=<sha256>
```

The verifier independently confirms the static frontend's SHA-bound manifest and HTTP identity, API identity, managed process identities, worker startup canary receipt, Beat identity, isolated broker, local Chromium CDP, and disabled real-submission/outreach controls. Preserve the generated runtime acceptance receipt together with the command output and the candidate SHA.

## 5. Stop point and escalation

A passing runtime acceptance receipt proves **runtime plumbing only**. It does not count as a 4-hour shadow campaign, certification evidence, or permission for real application submission.

At this point, proceed only to a no-submit material and fresh-preflight workflow for an exact application the account owner has selected. Do not enable `ALLOW_REAL_APPLICATION_SUBMIT`, send outreach, bypass CAPTCHA/MFA/identity controls, or create/consume a submission approval as part of this runbook.

## References

- `docs/ANDROID_SHADOW_RUNTIME_READINESS.md`
- `docs/roadmaps/2026-08-10-android-arm64-efficient-execution-plan.md`
- `backend/scripts/manage_android_stack.sh`
- `backend/scripts/android_runtime_acceptance_base.py`
- `backend/scripts/install_android_static_frontend_artifact.py`

# Final-Day Android Runtime Handoff

This runbook validates the **exact merged JobTomatik revision** on an account-owned Android/Termux runtime. It is a deployment-attestation and no-submit readiness procedure only. It does **not** authorize an ATS promotion, recruiter outreach, application submission, or a duration shadow campaign.

## Preconditions

The candidate must be the current `main` revision after pull request checks are green and the pull request is reviewed and merged. Do not run this procedure from a feature branch, a dirty checkout, or a mixed-revision runtime. The device must be able to reach GitHub, native Android Chrome must be available for debugging, and native Termux must be able to see one authorized ADB device or an explicitly selected `ANDROID_SERIAL`.

The managed runtime requires a Python virtual environment at `backend/.venv`. The static frontend is retrieved from the repository's SHA-bound artifact branch, so no device-side Node/Vite build is required.

| Boundary | Required state |
|---|---|
| Candidate source | Clean `main` checkout at one immutable Git SHA |
| API, worker, Beat, frontend | Attested to that same SHA |
| Browser CDP | Native Android Chrome over a loopback ADB forward; new installs default to `127.0.0.1:9223`; never exposed to the LAN or internet |
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

The managed Android startup routine uses Redis DB 1 and the shared browser contract. The native Termux wrapper establishes or verifies the native Chrome ADB forward before the PRoot stack is admitted. It rejects a missing or wrong browser package instead of starting Termux Chromium.

## 3. Install the SHA-bound frontend and start through the native wrapper

Install or refresh the native command from the pinned checkout, then return to native Termux for the integrated start. This is required because ADB forwarding belongs outside Ubuntu PRoot.

```bash
proot-distro login ubuntu --shared-tmp -- bash -lc '
  set -e
  cd /root/JobTomatik
  bash backend/scripts/install_android_native_browser_launcher.sh
'

export JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA"
jobtomatik browser-preflight
jobtomatik start
jobtomatik status
```

`browser-preflight` is non-mutating with respect to the managed stack. It proves the configured native Chrome identity and Playwright attachment before startup. If more than one authorized ADB device is visible, set `ANDROID_SERIAL` to the intended device before the preflight. Do not bypass this with a Termux Chromium launcher.

### Direct managed-stack maintenance path

The native wrapper is the preferred production entrypoint. If the direct managed-stack script must be used for launcher maintenance or diagnosis, first complete the same native Chrome `jobtomatik browser-preflight` above, then return to the Ubuntu/proot checkout and sanitize persisted process identities **before** starting the stack directly:

```bash
cd ~/JobTomatik/backend

JOBTOMATIK_RUNTIME_REVISION="$CANDIDATE_SHA" \
JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  bash scripts/sanitize_android_runtime_pid_files.sh

JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  bash scripts/manage_android_stack.sh start

JOBTOMATIK_EXPECTED_REVISION="$CANDIDATE_SHA" \
  bash scripts/manage_android_stack.sh status
```

The PID sanitizer is mandatory before any direct `manage_android_stack.sh start`. Android/Linux can recycle numeric PIDs after an earlier JobTomatik process exits. The sanitizer validates each live persisted PID against the expected JobTomatik process identity and removes a stale PID file without signalling the unrelated live process. Do not bypass this step when using the direct stack command. This maintenance path does not replace the native Chrome browser preflight and does not authorize a fallback browser provider.

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

The verifier independently confirms the static frontend's SHA-bound manifest and HTTP identity, API identity, managed process identities, worker startup canary receipt, Beat identity, isolated broker, configured native Chrome CDP identity, and disabled real-submission/outreach controls. Preserve the generated runtime acceptance receipt together with the command output and the candidate SHA.

## 5. Stop point and escalation

A passing runtime acceptance receipt proves **runtime plumbing only**. It does not count as a 4-hour shadow campaign, certification evidence, or permission for real application submission.

At this point, proceed only to a no-submit material and fresh-preflight workflow for an exact application the account owner has selected. Do not enable `ALLOW_REAL_APPLICATION_SUBMIT`, send outreach, bypass CAPTCHA/MFA/identity controls, or create/consume a submission approval as part of this runbook.

## References

- `docs/ANDROID_SHADOW_RUNTIME_READINESS.md`
- `docs/roadmaps/2026-08-10-android-arm64-efficient-execution-plan.md`
- `backend/scripts/manage_android_stack.sh`
- `backend/scripts/sanitize_android_runtime_pid_files.sh`
- `backend/scripts/android_runtime_acceptance_base.py`
- `backend/scripts/install_android_static_frontend_artifact.py`

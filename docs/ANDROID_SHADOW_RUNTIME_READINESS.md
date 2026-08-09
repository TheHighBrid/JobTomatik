# Android Shadow Runtime Readiness

This note defines the Android runtime prerequisites for a real Phase 11/12 full-stack shadow campaign. It is a runtime-readiness contract only. It does not create certification evidence, enable application submission, authorize recruiter outreach, promote an ATS adapter, or authorize a release.

## One configuration source

The native Android manager keeps `backend/.env` as the local durable configuration file. Core Pydantic settings already read that file. Operations settings now use the same file as a fallback while preserving exported process variables as the authoritative override.

This matters for controls such as:

- `AUTOMATION_GLOBAL_KILL_SWITCH`
- `AUTOPILOT_ENABLED`
- daily and weekly caps
- quiet hours
- circuit-breaker thresholds
- disabled platforms

An explicitly exported variable, including an explicitly empty value, wins over `.env`. The manager does not shell-source `.env`, so arbitrary shell content and secrets are not injected by Bash evaluation.

`APP_ENV` is also the documented runtime-profile variable. Core settings accept both `APP_ENV` and the compatibility spelling `APP_ENVIRONMENT`, so `APP_ENV=production` reaches the same production security validator used by the runtime identity checker.

## Emergency stop propagation

Docker API, worker, and Beat processes all receive the canonical `AUTOMATION_GLOBAL_KILL_SWITCH` variable. The obsolete `GLOBAL_KILL_SWITCH` spelling is not a runtime control.

The normal default remains `false`. Setting the canonical switch to `true` is the emergency stop and must reach scheduled automation before browser work or consequential execution.

## Managed Android processes

The one-command Android runtime supervises four application processes plus the native browser:

1. FastAPI, role `api`
2. Celery worker, role `worker`
3. Celery Beat, role `beat`
4. Vite frontend
5. Termux-native Chromium over local CDP

API, worker, and Beat are bound to the exact checked-out Git revision and the same expected deployment revision. Runtime identity is evidence only and never grants submission or outreach authority.

## Shadow recovery Beat

Phase 11 healthy shadow cycles self-schedule through the worker. Crash or broker recovery additionally depends on Celery Beat dispatching:

`app.tasks.shadow_runs.recover_stalled_shadow_sessions`

The required schedule is minutes:

`11, 26, 41, 56`

The Android manager now starts a dedicated Beat process with:

- Redis DB1, the managed Android broker
- exact runtime and expected revision
- runtime role `beat`
- a dedicated schedule database under `backend/.runtime/`
- a retained runtime-attestation receipt
- PID-based supervision and bounded shutdown

`jobtomatik status` must fail closed when Beat is absent, stale, unattested, or the recovery schedule contract is missing.

## Expected readiness markers

A shadow-capable Android stack should report all of the following before any real duration campaign is considered:

```text
API: READY_ATTESTED
FRONTEND: READY
CELERY: READY applications,celery,followup,scraping
CELERY_APPLICATION_CANARY: READY_ATTESTED
CELERY_BEAT: READY_ATTESTED
ANDROID_BROWSER_CDP: READY
ANDROID_RUNTIME_BROKER: ISOLATED
ANDROID_RUNTIME_ATTESTATION: READY
```

These markers prove runtime plumbing only.

## Separate shadow preflight

A real 4h, 8h, or 24h campaign still requires the Phase 11 shadow preflight to independently confirm at least:

- exact deployment-attested runtime identity
- `ALLOW_REAL_APPLICATION_SUBMIT=false`
- no recruiter-outreach authorization
- `AUTOPILOT_ENABLED=true` as a scheduler prerequisite
- global kill switch clear
- the selected user has auto-search enabled
- the selected user has auto-apply enabled
- the selected user remains in dry-run mode
- platform and policy controls are not blocking the selected campaign

Enabling `AUTOPILOT_ENABLED` is an explicit operating decision. The runtime-hardening changes do not turn it on automatically.

## Evidence boundary

A green runtime and a green CI matrix do not count as retained 4h, 8h, or 24h shadow evidence.

Qualifying evidence still requires one real account-owned Phase 11 `ShadowRunSession` to:

1. run for the requested wall-clock duration on the exact attested revision;
2. settle and reconcile;
3. retain the hash-bound Phase 11 report;
4. bridge that exact session into the certification ledger;
5. pass independent review;
6. pass Phase 12 provenance revalidation when release readiness is evaluated later.

No synthetic test, owner report, elapsed calendar date, or CI receipt may substitute for that evidence.

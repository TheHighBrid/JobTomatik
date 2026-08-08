# Android-native application browser

JobTomatik runs fully on one Android device without launching the Playwright Chromium binary inside Ubuntu PRoot.

Chromium runs natively in Termux/X11. FastAPI and the authoritative Celery worker run in Ubuntu PRoot and attach to that browser over Chrome DevTools Protocol (CDP) through `127.0.0.1:9222`.

## Runtime contract

The managed Android runtime has one authoritative execution path:

- API: `http://127.0.0.1:8010`
- frontend: `http://127.0.0.1:3000`
- native Chromium CDP: `http://127.0.0.1:9222`
- managed Redis/Celery database: `redis://localhost:6379/1`
- managed Celery hostname: `jobtomatik-android-<revision-prefix>@%h`
- managed queues: `applications,celery,followup,scraping`
- API runtime role: `api`
- worker runtime role: `worker`
- runtime revision: exact checked-out Git commit
- expected revision: exact same checked-out Git commit

Redis DB 1 intentionally isolates the managed runtime from historical manually launched workers that may still be alive in old terminal tabs on Redis DB 0. Those processes do not need to be killed and cannot consume newly queued managed tasks.

The frontend automatically migrates historical loopback API settings such as port `8011` back to the authoritative Android API on port `8010`.

The one-command Android manager now carries the same Phase 12 runtime-identity contract as the standalone revision-stamped launchers. It derives the checked-out revision, binds it as both `JOBTOMATIK_RUNTIME_REVISION` and `JOBTOMATIK_EXPECTED_REVISION`, assigns process-specific roles, runs the unconditional attestation checker before managed processes start, and rechecks the live API plus the worker queue canary before reporting the stack ready.

Runtime identity is evidence only. It never enables application submission, recruiter outreach, adapter promotion, or release authorization.

## Application execution order

A dry preview follows this order:

1. open the discovery listing
2. detect an explicitly closed listing and stop cleanly when applicable
3. locate the current Apply doorway from the live DOM
4. follow a proven external employer/ATS href directly when available, or click the live Apply control
5. tolerate LinkedIn SPA rerenders by rescanning rather than handing control to the operator
6. verify that the actual application form is present
7. fill safe applicant fields and upload configured application materials
8. advance through ATS steps
9. retain a browser handoff only for an active security or identity boundary such as CAPTCHA, login, MFA, or anti-bot verification
10. in dry-run mode, stop before final submission

A visible `Apply` button on a LinkedIn job-detail page is not a human boundary. JobTomatik must operate it automatically. Plain `Apply` matching is restricted to known discovery job boards so an ATS final-submit button cannot be mistaken for a doorway.

## Components

- `backend/scripts/start_android_browser_cdp.sh` runs in native Termux. It keeps the authenticated Chromium profile alive, holds a Termux wake lock when available, rotates noisy browser logs, and automatically restarts Chromium if the browser process exits.
- `backend/scripts/install_android_native_browser_launcher.sh` installs the native `jobtomatik` and `jobtomatik-browser` commands from inside Ubuntu PRoot without assuming where PRoot-Distro stores its root filesystem.
- `backend/scripts/repair_android_database_url.py` replaces an unreachable localhost PostgreSQL URL with the Android SQLite database after backing up `backend/.env`. Remote PostgreSQL URLs and reachable local servers remain unchanged.
- `backend/scripts/prepare_android_runtime.py` backs up an existing SQLite database when schema repair is needed, creates missing runtime tables, verifies critical discovery tables, and reports browser reachability.
- `backend/scripts/manage_android_stack.sh` establishes the authoritative Android settings, repairs configuration and schema, binds exact runtime identity, starts Redis when necessary, and supervises FastAPI, Celery, and Vite through PID files and logs.

## One-time activation from native Termux

Run this from the native Termux prompt:

```bash
proot-distro login ubuntu --shared-tmp -- bash -lc '
  set -e
  cd /root/JobTomatik
  git fetch origin main
  git switch main
  git pull --ff-only origin main
  bash backend/scripts/install_android_native_browser_launcher.sh
'

jobtomatik start
```

Do not construct a path through `installed-rootfs` or `containers` manually. The installer executes inside the selected PRoot container and writes the native commands directly into the Termux executable prefix.

This installs two native Termux commands:

```text
jobtomatik
jobtomatik-browser
```

## Daily operation from native Termux

Start or adopt the complete managed runtime while preserving a healthy authenticated browser:

```bash
jobtomatik start
```

Restart managed components while preserving Chromium:

```bash
jobtomatik restart
```

Update to authoritative `origin/main`, refresh the native command files, and restart the managed runtime:

```bash
jobtomatik update
```

`jobtomatik update` always switches to `main` and fast-forwards from `origin/main`; it does not silently keep running an old feature branch.

Other commands:

```bash
jobtomatik status
jobtomatik stop
```

Successful status markers are:

```text
API: READY_ATTESTED
FRONTEND: READY
CELERY: READY applications,celery,followup,scraping
CELERY_APPLICATION_CANARY: READY_ATTESTED
ANDROID_BROWSER_CDP: READY
ANDROID_RUNTIME_BROKER: ISOLATED
ANDROID_RUNTIME_ATTESTATION: READY
```

`jobtomatik status` fails closed when the API is reachable but its live Phase 12 identity is stale, unattested, has the wrong process role, or does not match the current checkout. The worker is considered ready only after a real producer → `applications` queue → worker → Redis DB1 result round trip also proves the worker role and exact deployment attestation.

The persistent authenticated browser profile remains at:

```text
$HOME/.jobtomatik-chromium
```

## Ubuntu PRoot configuration

The Android stack manager enforces these runtime values on startup:

```env
REDIS_URL=redis://localhost:6379/1
APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222
APPLICATION_BROWSER_HEADLESS=false
APPLICATION_TARGET_HUMAN_WAIT_SECONDS=0
JOBTOMATIK_RUNTIME_REVISION=<checked-out-commit>
JOBTOMATIK_EXPECTED_REVISION=<same-checked-out-commit>
```

The API and worker receive their own `JOBTOMATIK_RUNTIME_ROLE` values when launched. The identity values are process environment, not durable permission flags.

`APPLICATION_TARGET_HUMAN_WAIT_SECONDS=0` is deliberate. The worker must never wait for the operator merely to click an Apply doorway. Human time is reserved for real retained security or policy boundaries.

For the database:

- a missing `DATABASE_URL` becomes `sqlite:///./jobtomatik.db`
- an unreachable PostgreSQL URL targeting `localhost`, `127.0.0.1`, or `::1` is backed up and replaced with SQLite
- a reachable local PostgreSQL server is preserved
- a remote PostgreSQL URL is preserved without a reachability probe

When `APPLICATION_BROWSER_CDP_ENDPOINT` is set, JobTomatik:

- attaches to the already-running native browser
- reuses its logged-in profile and open tabs
- does not spawn the PRoot Playwright browser
- does not terminate the native browser after an application task
- preserves CDP-backed handoffs only when a genuine resumable boundary exists

## Full-stack shadow certification

The managed Android runtime is suitable for Phase 11/12 shadow preflight only when all independent shadow prerequisites also pass. In particular:

- `ALLOW_REAL_APPLICATION_SUBMIT=false`
- `AUTOPILOT_ENABLED=true` as the scheduler prerequisite
- user auto-search and auto-apply are enabled
- user dry-run mode is enabled
- global/platform safety controls remain clear
- `/api/system/runtime-identity` reports the exact current revision and `deployment_attested=true`
- Shadow Campaign preflight reports runtime identity attested

A green Android runtime status does **not** create 4h, 8h, or 24h certification evidence. The campaign must still run for the real requested duration, settle and reconcile, retain its hash-bound Phase 11 report, bridge that exact session into the certification ledger, and receive independent review under the Phase 12 provenance rules.

## Component-level commands

Native browser only:

```bash
jobtomatik-browser status
jobtomatik-browser restart
jobtomatik-browser stop
```

PRoot managed application stack only:

```bash
cd /root/JobTomatik
bash backend/scripts/manage_android_stack.sh status
bash backend/scripts/manage_android_stack.sh restart
bash backend/scripts/manage_android_stack.sh stop
```

For isolated component development, `scripts/jobtomatik-runtime.sh api|worker|beat` remains available. The native `jobtomatik` command is the preferred integrated Android path because it also owns Redis isolation, schema preparation, browser attachment, frontend routing, queue-canary verification, and exact runtime attestation.

Runtime logs and automatic backups are stored under:

```text
backend/.runtime/logs/
backend/.runtime/env-backups/
backend/runtime_backups/
$HOME/.jobtomatik-runtime/
```

## Failure behavior

- Celery creates newly introduced SQLAlchemy tables before it accepts tasks, even when the API was not restarted first.
- Job discovery releases the search controls after `FAILURE`, `REVOKED`, or a bounded timeout. A Celery `RETRY` state is shown as an automatic retry rather than a frozen search.
- Repeated discovery results use stable provider posting identities so tracking-query changes do not re-add the same job.
- An explicitly closed job listing is a terminal, non-retryable outcome and does not create a manual handoff.
- A LinkedIn DOM rerender triggers an automatic Apply-control rescan, not a manual handoff.
- A stale worker connected to historical Redis DB 0 cannot consume managed tasks routed through Redis DB 1.
- A stale or unattested managed API is restarted rather than silently adopted.
- A worker that cannot prove exact Phase 12 attestation through the real applications queue is not declared ready.
- A caller-supplied expected revision that differs from the checked-out runtime revision stops the manager before API/worker startup.
- The browser supervisor restarts native Chromium after an unexpected exit. JobTomatik waits briefly for the CDP endpoint to return.
- SQLite is backed up before missing critical tables are created by the Android runtime preflight. Only the newest three automatic schema backups are retained.
- Browser logs rotate at a bounded size to avoid consuming the device's limited storage.
- The native launcher never depends on a hard-coded PRoot-Distro storage layout.

## Safety

The native Chromium process belongs to the operator, not JobTomatik. JobTomatik only disconnects its Playwright controller when a task finishes.

The runtime manager never uses broad process matching to terminate arbitrary terminal sessions. Historical manual processes may remain visible, but the managed broker and API routing prevent them from participating in new application tasks.

Runtime attestation proves exact code identity only. It cannot turn on real application submission, recruiter outreach, adapter maturity, supervised approval, or release authorization.

Do not expose port `9222` to the public network. The remote-debugging address remains bound to `127.0.0.1`.

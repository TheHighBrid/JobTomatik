# Android-native application browser

JobTomatik can run fully on one Android device without launching the Playwright Chromium binary inside Ubuntu PRoot.

The browser runs natively in Termux/X11. FastAPI and Celery run in Ubuntu PRoot and attach to that browser over Chrome DevTools Protocol (CDP) through `127.0.0.1:9222`.

## Components

- `backend/scripts/start_android_browser_cdp.sh` runs in native Termux. It keeps the authenticated Chromium profile alive, holds a Termux wake lock when available, rotates noisy browser logs, and automatically restarts Chromium if the browser process exits.
- `backend/scripts/install_android_native_browser_launcher.sh` installs the native `jobtomatik` and `jobtomatik-browser` commands from inside Ubuntu PRoot without assuming where PRoot-Distro stores its root filesystem.
- `backend/scripts/repair_android_database_url.py` replaces an unreachable localhost PostgreSQL URL with the Android SQLite database after backing up `backend/.env`. Remote PostgreSQL URLs and reachable local servers remain unchanged.
- `backend/scripts/prepare_android_runtime.py` backs up an existing SQLite database when schema repair is needed, creates missing runtime tables, verifies critical discovery tables, and reports browser reachability.
- `backend/scripts/manage_android_stack.sh` repairs configuration and schema, starts Redis when necessary, and supervises FastAPI, Celery, and Vite through PID files and logs.

## One-time activation from native Termux

Run this from the native Termux prompt:

```bash
proot-distro login ubuntu --shared-tmp -- bash -lc '
  cd /root/JobTomatik &&
  git pull --ff-only origin fix/android-native-cdp-browser &&
  bash backend/scripts/install_android_native_browser_launcher.sh
'

jobtomatik restart
```

Do not construct a path through `installed-rootfs` or `containers` manually. The installer executes inside the selected PRoot container and writes the native commands directly into the Termux executable prefix.

This installs two commands into native Termux:

```text
jobtomatik
jobtomatik-browser
```

## Daily operation from native Termux

Start the complete Android runtime while preserving a healthy browser process:

```bash
jobtomatik start
```

Restart and repair every component:

```bash
jobtomatik restart
```

The command:

1. starts native Chromium under its automatic supervisor
2. reuses the authenticated LinkedIn profile
3. enters Ubuntu PRoot with shared X11 sockets
4. repairs an unavailable localhost PostgreSQL configuration to SQLite
5. repairs missing SQLite tables
6. starts Redis, FastAPI, Celery, and Vite
7. verifies API, worker, frontend, and CDP health

Other commands:

```bash
jobtomatik status
jobtomatik stop
jobtomatik update
```

`jobtomatik update` pulls the currently checked-out Git branch, refreshes the native command files through PRoot, and restarts the full runtime.

The successful markers are:

```text
ANDROID_BROWSER_CDP_CONNECTED
ANDROID_DATABASE_URL_READY
JOBTOMATIK_RUNTIME_SCHEMA_READY
JOBTOMATIK_ANDROID_STACK_READY
API: READY
FRONTEND: READY
CELERY: READY
ANDROID_BROWSER_CDP: READY
```

When an unavailable localhost PostgreSQL URL is repaired, the database marker is instead:

```text
ANDROID_DATABASE_URL_REPAIRED
```

The persistent authenticated browser profile remains at:

```text
$HOME/.jobtomatik-chromium
```

## Ubuntu PRoot configuration

The stack manager supplies safe Android defaults when browser keys are absent from `backend/.env`:

```env
APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222
APPLICATION_BROWSER_HEADLESS=false
APPLICATION_TARGET_HUMAN_WAIT_SECONDS=600
```

For the database:

- a missing `DATABASE_URL` becomes `sqlite:///./jobtomatik.db`
- an unreachable PostgreSQL URL targeting `localhost`, `127.0.0.1`, or `::1` is backed up and replaced with SQLite
- a reachable local PostgreSQL server is preserved
- a remote PostgreSQL URL is preserved without a reachability probe

When `APPLICATION_BROWSER_CDP_ENDPOINT` is set, JobTomatik:

- attaches to the already-running native browser
- reuses its logged-in profile and open tabs
- does not spawn the PRoot Playwright browser
- does not terminate the native browser after a task
- preserves CDP-backed manual handoffs

## Component-level commands

Native browser only:

```bash
jobtomatik-browser status
jobtomatik-browser restart
jobtomatik-browser stop
```

PRoot application stack only:

```bash
cd /root/JobTomatik
bash backend/scripts/manage_android_stack.sh status
bash backend/scripts/manage_android_stack.sh restart
bash backend/scripts/manage_android_stack.sh stop
```

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
- The browser supervisor restarts native Chromium after an unexpected exit. JobTomatik waits briefly for the CDP endpoint to return.
- SQLite is backed up before missing critical tables are created by the Android runtime preflight. Only the newest three automatic schema backups are retained.
- Browser logs rotate at a bounded size to avoid consuming the device's limited storage.
- The native launcher never depends on a hard-coded PRoot-Distro storage layout.

## Safety

The native Chromium process belongs to the operator, not JobTomatik. JobTomatik only disconnects its Playwright controller when a task finishes.

Do not expose port `9222` to the public network. The remote-debugging address remains bound to `127.0.0.1`.

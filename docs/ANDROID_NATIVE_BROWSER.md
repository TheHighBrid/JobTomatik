# Android-native application browser

JobTomatik can run fully on one Android device without launching the Playwright Chromium binary inside Ubuntu PRoot.

The browser runs natively in Termux/X11. FastAPI and Celery run in Ubuntu PRoot and attach to that browser over Chrome DevTools Protocol (CDP) through `127.0.0.1:9222`.

## Components

- `backend/scripts/start_android_browser_cdp.sh` runs in native Termux. It keeps the authenticated Chromium profile alive, holds a Termux wake lock when available, and automatically restarts Chromium if the browser process exits.
- `backend/scripts/install_android_native_browser_launcher.sh` installs that supervisor into native Termux from the PRoot repository.
- `backend/scripts/prepare_android_runtime.py` runs in Ubuntu PRoot. It backs up an existing SQLite database when schema repair is needed, creates missing runtime tables, verifies critical discovery tables, and reports browser reachability.
- `backend/scripts/manage_android_stack.sh` runs in Ubuntu PRoot. It repairs the schema, starts Redis when necessary, and supervises FastAPI, Celery, and Vite through PID files and logs.

## Native Termux browser supervisor

Install the repository launcher into native Termux once, from Ubuntu PRoot:

```bash
cd /root/JobTomatik
bash backend/scripts/install_android_native_browser_launcher.sh
```

After installation, run the launcher from native Termux:

```bash
$HOME/.local/bin/jobtomatik-browser start
```

Useful commands:

```bash
$HOME/.local/bin/jobtomatik-browser status
$HOME/.local/bin/jobtomatik-browser restart
$HOME/.local/bin/jobtomatik-browser stop
```

The successful start marker is:

```text
ANDROID_BROWSER_CDP_CONNECTED
```

The persistent authenticated profile remains at:

```text
$HOME/.jobtomatik-chromium
```

## Ubuntu PRoot configuration

Inside `backend/.env`:

```env
DATABASE_URL=sqlite:///./jobtomatik.db
APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222
APPLICATION_BROWSER_HEADLESS=false
APPLICATION_TARGET_HUMAN_WAIT_SECONDS=600
```

When `APPLICATION_BROWSER_CDP_ENDPOINT` is set, JobTomatik:

- attaches to the already-running native browser
- reuses its logged-in profile and open tabs
- does not spawn the PRoot Playwright browser
- does not terminate the native browser after a task
- preserves CDP-backed manual handoffs

## PRoot stack supervisor

From Ubuntu PRoot:

```bash
cd /root/JobTomatik
bash backend/scripts/manage_android_stack.sh restart
```

Successful startup ends with:

```text
JOBTOMATIK_RUNTIME_SCHEMA_READY
JOBTOMATIK_ANDROID_STACK_READY
```

Status and shutdown commands:

```bash
bash backend/scripts/manage_android_stack.sh status
bash backend/scripts/manage_android_stack.sh stop
```

Runtime logs are stored under:

```text
backend/.runtime/logs/
```

## Failure behavior

- Celery creates newly introduced SQLAlchemy tables before it accepts tasks, even when the API was not restarted first.
- Job discovery releases the search controls after `FAILURE`, `REVOKED`, or a bounded timeout. A Celery `RETRY` state is shown as an automatic retry rather than a frozen search.
- The browser supervisor restarts native Chromium after an unexpected exit. JobTomatik waits briefly for the CDP endpoint to return.
- SQLite is backed up before missing critical tables are created by the Android runtime preflight.

## Safety

The native Chromium process belongs to the operator, not JobTomatik. JobTomatik only disconnects its Playwright controller when a task finishes.

Do not expose port `9222` to the public network. The remote-debugging address remains bound to `127.0.0.1`.

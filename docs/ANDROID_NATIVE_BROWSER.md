# Android-native application browser

JobTomatik can run fully on an Android device without launching the Playwright Chromium binary inside Ubuntu PRoot.

The browser runs natively in Termux/X11. The backend and Celery worker attach to it over Chrome DevTools Protocol (CDP) through `127.0.0.1:9222`.

## 1. Start Chromium from native Termux

Run this outside Ubuntu PRoot:

```bash
mkdir -p "$HOME/.jobtomatik-chromium"
export DISPLAY=:0

chromium-browser \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-gpu \
  --disable-features=Vulkan,WebGPU \
  --ozone-platform=x11 \
  --no-first-run \
  --no-default-browser-check \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.jobtomatik-chromium" \
  "https://www.linkedin.com/login"
```

Keep Chromium open. Log into LinkedIn in this persistent profile.

Verify the endpoint from native Termux:

```bash
curl -sS http://127.0.0.1:9222/json/version
```

The response must contain `webSocketDebuggerUrl`.

## 2. Configure the Ubuntu PRoot backend

Inside `backend/.env` set:

```env
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

Verify Ubuntu PRoot can reach the browser:

```bash
curl -sS http://127.0.0.1:9222/json/version
```

## 3. Start Celery with the applications queue

```bash
cd /root/JobTomatik/backend
source .venv/bin/activate

celery -A app.celery_app worker \
  --loglevel=info \
  --pool=solo \
  -Q applications,celery,followup,scraping
```

## 4. Safety and ownership

The native Chromium process belongs to the operator, not JobTomatik. Closing or restarting Celery does not close the browser. JobTomatik only disconnects its Playwright controller when a task finishes.

Do not expose port `9222` to the public network. Keep the remote-debugging address bound to `127.0.0.1`.

# OneHost production deployment

This is the supported production execution shape after Recovery Gate 2 and Gate 3.

Android is a thin client. It does not own FastAPI, PostgreSQL, Redis, Celery, ADB,
native Chrome, or the application browser. The application browser is Playwright-owned
Chromium on the OneHost machine.

## Topology

```text
Android APK
    |
    | HTTPS / trusted network API
    v
OneHost Linux machine
    |
    +-- FastAPI
    +-- PostgreSQL
    +-- Redis
    +-- one Celery worker (solo, concurrency=1)
            |
            +-- Playwright-owned persistent Chromium
            +-- retained handoff state
```

The API container is the namespace anchor. The Celery worker shares the API container's
network and PID namespaces. Both use the same `JOBTOMATIK_BROWSER_NODE_ID` and the
same `/state` volume. This is required because the authenticated handoff API attaches
directly to the retained Chromium CDP endpoint while resume and cleanup run in Celery.

Celery Beat is intentionally absent.

## Required host

Use a Docker-capable Linux host with enough persistent disk for PostgreSQL, uploads,
browser profiles, screenshots, traces and handoff evidence.

Do not use the Android tablet as this host.

## Secrets and revision

From an exact checked-out revision:

```bash
export JOBTOMATIK_RUNTIME_REVISION="$(git rev-parse HEAD)"
export POSTGRES_PASSWORD='...'
export SECRET_KEY='...'
export ANSWER_VAULT_KEY='...'
```

Use stable production secrets. Do not rotate them casually while encrypted Answer Vault
or handoff data still exists.

## Start

Safe localhost-only default:

```bash
docker compose -f docker-compose.onehost-production.yml up -d --build
```

The default API bind is `127.0.0.1:8000`. For an Android device on a trusted LAN,
explicitly choose a host bind address:

```bash
export ONEHOST_API_BIND_ADDRESS=0.0.0.0
export ONEHOST_API_PORT=8000
docker compose -f docker-compose.onehost-production.yml up -d --build
```

For access beyond a trusted private network, place the API behind authenticated TLS
termination or another approved secure ingress. Do not expose an unauthenticated raw
HTTP endpoint to the public Internet.

## Android client

The APK already supports an operator-selected API base URL. In the API connection
control, save the reachable OneHost URL. The saved value remains authoritative across
requests.

The Termux `jobtomatik` command is no longer an execution-host launcher:

- `jobtomatik start`, `restart`, and `status` report thin-client mode and return
  without touching ADB, native Chrome, PRoot API/worker processes, or a browser.
- `browser-preflight` and `acceptance` are retired and return a non-success status so
  they cannot be mistaken for OneHost certification.
- `stop` remains available only to clean up historical local Android processes.
- `update` may update the checkout/tooling, then re-enters the harmless thin-client
  `restart` action.

Historical Android/native-Chrome scripts remain in the repository for evidence and
bounded recovery history. They are not the supported production execution path.

## Safe defaults

The production Compose defaults keep these controls closed:

```text
ALLOW_REAL_APPLICATION_SUBMIT=false
GREENHOUSE_SUPERVISED_PILOT_ENABLED=false
LEVER_SUPERVISED_PILOT_ENABLED=false
ALLOW_REAL_FOLLOWUP_SEND=false
AUTOPILOT_ENABLED=false
```

`ENABLE_RESUMABLE_HANDOFFS` defaults to true because same-browser human handoff is a
core OneHost capability. That does not grant final-submit authority.

## GH-OH1

Issue #655 remains application-specific. Its candidate approval does not authorize a
different job and does not automatically open global submission flags.

Before a real final action, preserve the exact employer/role/URL, application identity,
document hashes, answer payload hash, one-time approval, confirmation evidence,
evidence-before-state-promotion and duplicate/replay protections.

## Verification

At minimum:

```bash
docker compose -f docker-compose.onehost-production.yml config
python -m pytest -q backend/tests/test_onehost_production_cutover.py
bash scripts/verify-onehost-handoff.sh
```

Gate 3 evidence remains the canonical proof of same-browser authenticated handoff.
Production deployment must preserve that contract rather than replacing it with an
external browser or reconstructed form.

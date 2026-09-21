"""Shared browser selection and native Chrome identity checks.

This module does not launch, stop, recover, or modify a browser. Native identity
is checked on both the HTTP discovery endpoint and the actual CDP connection.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.config import get_settings


class BrowserContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApplicationBrowserContract:
    provider: str
    endpoint: str

    @property
    def native(self) -> bool:
        return self.provider == "native_chrome"


def _validated_native_port(endpoint: str) -> int:
    """Return the port only for an explicit loopback HTTP CDP endpoint."""

    candidate = str(endpoint or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    try:
        port = parsed.port
    except ValueError as exc:
        raise BrowserContractError("ANDROID_NATIVE_CHROME_ENDPOINT_INVALID") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise BrowserContractError(
            "ANDROID_NATIVE_CHROME_ENDPOINT_INVALID: use an explicit localhost ADB-forwarded port"
        )
    return port


def application_browser_contract(settings: Any = None) -> ApplicationBrowserContract:
    settings = settings if settings is not None else get_settings()
    endpoint = str(getattr(settings, "application_browser_cdp_endpoint", "") or "").strip().rstrip("/")
    provider = str(getattr(settings, "application_browser_provider", "auto") or "auto")
    managed = os.environ.get("JOBTOMATIK_RUNTIME_MODE") == "android_managed"
    if provider == "auto":
        provider = "native_chrome" if managed else ("external_cdp" if endpoint else "local")
    if managed and provider != "native_chrome":
        raise BrowserContractError("ANDROID_NATIVE_CHROME_REQUIRED: managed application work cannot use a replacement browser")
    if provider not in {"native_chrome", "external_cdp", "local"}:
        raise BrowserContractError("APPLICATION_BROWSER_PROVIDER_INVALID")
    if provider == "local":
        if endpoint:
            raise BrowserContractError("APPLICATION_BROWSER_CONFIG_CONFLICT: local provider has a CDP endpoint")
    else:
        if not endpoint:
            raise BrowserContractError("APPLICATION_BROWSER_ENDPOINT_REQUIRED: configure the selected browser; local fallback is disabled")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            raise BrowserContractError("APPLICATION_BROWSER_ENDPOINT_INVALID")
        try:
            parsed.port
        except ValueError as exc:
            raise BrowserContractError("APPLICATION_BROWSER_ENDPOINT_INVALID") from exc
        if provider == "native_chrome":
            _validated_native_port(endpoint)
    return ApplicationBrowserContract(provider=provider, endpoint=endpoint)


def validate_native_identity(payload: Any, endpoint: str) -> dict[str, str]:
    if not isinstance(payload, dict) or payload.get("Android-Package") != "com.android.chrome":
        raise BrowserContractError("ANDROID_NATIVE_CHROME_IDENTITY_MISMATCH: expected com.android.chrome; application paused")
    if not all(isinstance(payload.get(key), str) and payload[key] for key in ("Browser", "User-Agent", "webSocketDebuggerUrl")):
        raise BrowserContractError("ANDROID_NATIVE_CHROME_IDENTITY_INCOMPLETE")
    native_port = _validated_native_port(endpoint)
    websocket = urlparse(payload["webSocketDebuggerUrl"])
    try:
        valid_socket = (
            websocket.scheme == "ws"
            and websocket.hostname in {"127.0.0.1", "localhost"}
            and websocket.port == native_port
            and not websocket.username and not websocket.password
            and not websocket.query and not websocket.fragment
            and (
                websocket.path == "/devtools/browser"
                or websocket.path.startswith("/devtools/browser/")
            )
        )
    except ValueError:
        valid_socket = False
    if not valid_socket:
        raise BrowserContractError("ANDROID_NATIVE_CHROME_WEBSOCKET_MISMATCH")
    return {key: payload[key] for key in ("Android-Package", "Browser", "User-Agent", "webSocketDebuggerUrl")}


async def read_native_identity(endpoint: str) -> dict[str, str]:
    native_port = _validated_native_port(endpoint)
    # Build the request target from a fixed loopback host plus the validated integer
    # port. Direct callers therefore cannot turn identity discovery into an SSRF path.
    identity_endpoint = f"http://127.0.0.1:{native_port}"
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False, follow_redirects=False) as client:
            response = await client.get(f"{identity_endpoint}/json/version")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise BrowserContractError(
            "ANDROID_NATIVE_CHROME_UNAVAILABLE: preserve the application and reconnect the selected Chrome transport"
        ) from exc
    return validate_native_identity(payload, identity_endpoint)


def _native_browser_instance_id(websocket_url: str) -> str:
    """Return Chrome's restart-sensitive browser UUID when discovery exposes one."""

    path = urlparse(str(websocket_url or "")).path
    prefix = "/devtools/browser/"
    if not path.startswith(prefix):
        return ""
    candidate = path[len(prefix) :]
    if not candidate or "/" in candidate:
        return ""
    try:
        return str(UUID(candidate))
    except ValueError:
        return ""


async def connect_native_browser(playwright: Any, contract: ApplicationBrowserContract, connect: Any) -> Any:
    before = await read_native_identity(contract.endpoint)
    # Pin discovery to its returned websocket instead of asking Playwright to
    # rediscover whichever browser happens to occupy the HTTP port later.
    browser = await connect(playwright, before["webSocketDebuggerUrl"])
    session = await browser.new_browser_cdp_session()
    try:
        connected = await session.send("Browser.getVersion")
    finally:
        await session.detach()
    after = await read_native_identity(contract.endpoint)
    if before != after or connected.get("product") != before["Browser"] or connected.get("userAgent") != before["User-Agent"]:
        raise BrowserContractError("ANDROID_NATIVE_CHROME_CHANGED_DURING_ATTACH: application paused")
    if len(browser.contexts) != 1:
        raise BrowserContractError("ANDROID_NATIVE_CHROME_CONTEXT_AMBIGUOUS")
    browser_instance_id = _native_browser_instance_id(before["webSocketDebuggerUrl"])
    browser._jobtomatik_application_browser_identity = {
        "provider": "native_chrome",
        "transport": "adb_forwarded_cdp",
        "android_package": before["Android-Package"],
        "browser": before["Browser"],
        "user_agent": before["User-Agent"],
        "cdp_endpoint": contract.endpoint,
        "browser_instance_id": browser_instance_id,
        "runtime_revision": os.environ.get("JOBTOMATIK_RUNTIME_REVISION", ""),
        "connection_identity_verified": True,
    }
    return browser

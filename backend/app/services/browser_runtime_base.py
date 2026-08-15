from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.ats_base import page_fingerprint
from app.services.browser_handoff import current_browser_node_id


CDP_STARTUP_TIMEOUT_SECONDS = 120
PLAYWRIGHT_ATTACH_TIMEOUT_SECONDS = 120
EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS = 20


class BrowserRuntimeError(RuntimeError):
    pass


def chromium_stability_args() -> list[str]:
    """Return conservative flags for Chromium in containers and Android/proot.

    ``--disable-gpu`` alone does not prevent Chromium from starting a GPU
    process. In particular, WebGL may fall back to Mesa's software renderer
    and repeatedly abort the GPU process. Disabling all 3D APIs and the
    software rasterizer prevents that crash loop; LinkedIn's authentication
    flow does not require either feature.
    """
    return [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-gpu-rasterization",
        "--disable-software-rasterizer",
        "--disable-3d-apis",
        "--disable-accelerated-2d-canvas",
        "--disable-accelerated-video-decode",
        "--disable-accelerated-video-encode",
        "--disable-webgl",
        "--disable-webgl2",
        "--disable-features=Vulkan,UseSkiaRenderer,CanvasOopRasterization,WebGPU",
    ]


def resumable_handoffs_enabled() -> bool:
    # Read through BaseSettings so ENABLE_RESUMABLE_HANDOFFS in backend/.env is
    # honored without requiring the caller to export it into the shell first.
    return bool(get_settings().enable_resumable_handoffs)


def handoff_storage_root() -> Path:
    return Path(os.getenv("HANDOFF_STORAGE_DIR", "handoff_sessions"))


def _reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _chromium_environment() -> Dict[str, str]:
    """Remove malformed desktop-session variables commonly inherited in proot."""
    environment = os.environ.copy()
    dbus_address = environment.get("DBUS_SESSION_BUS_ADDRESS", "")
    if dbus_address and not dbus_address.startswith(("unix:", "tcp:")):
        environment.pop("DBUS_SESSION_BUS_ADDRESS", None)
    return environment


def _normalize_external_cdp_endpoint(endpoint: str) -> str:
    value = (endpoint or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserRuntimeError(
            "APPLICATION_BROWSER_CDP_ENDPOINT must be an HTTP(S) Chrome DevTools "
            "endpoint such as http://127.0.0.1:9222."
        )
    return value


@dataclass
class ExternalBrowserProcess:
    """Process-compatible health probe for a browser owned outside JobTomatik."""

    endpoint: str
    pid: Optional[int] = None

    def poll(self) -> Optional[int]:
        try:
            response = httpx.get(f"{self.endpoint}/json/version", timeout=0.75)
            if response.status_code == 200 and response.json().get("webSocketDebuggerUrl"):
                return None
        except Exception:
            pass
        return 1

    def terminate(self) -> None:
        return None

    def wait(self, timeout: Optional[float] = None) -> int:
        return 0

    def kill(self) -> None:
        return None


async def _wait_for_cdp_endpoint(
    process: subprocess.Popen,
    endpoint: str,
    log_handle: Any,
    log_path: Path,
) -> None:
    """Wait for Chromium's CDP endpoint using its own startup budget."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + CDP_STARTUP_TIMEOUT_SECONDS
    last_error = ""

    while loop.time() < deadline:
        if process.poll() is not None:
            log_handle.close()
            raise BrowserRuntimeError(
                "Chromium exited before CDP became available. "
                f"See {log_path} (exit code {process.returncode})."
            )
        try:
            response = httpx.get(f"{endpoint}/json/version", timeout=0.75)
            if response.status_code == 200 and response.json().get("webSocketDebuggerUrl"):
                return
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(0.25)

    process.terminate()
    log_handle.close()
    raise BrowserRuntimeError(
        "Chromium CDP endpoint did not become ready within "
        f"{CDP_STARTUP_TIMEOUT_SECONDS} seconds: {last_error[:200]}. See {log_path}."
    )


async def _wait_for_external_cdp_endpoint(endpoint: str) -> None:
    """Wait briefly for an Android/native Chromium endpoint JobTomatik does not own."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS
    last_error = ""

    while loop.time() < deadline:
        try:
            response = httpx.get(f"{endpoint}/json/version", timeout=0.75)
            if response.status_code == 200 and response.json().get("webSocketDebuggerUrl"):
                return
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(0.5)

    raise BrowserRuntimeError(
        "The configured Android/native Chromium CDP endpoint is not reachable at "
        f"{endpoint}. Start chromium-browser with --remote-debugging-port=9222 "
        f"and keep it open. Last error: {last_error[:200]}"
    )


async def _connect_playwright_over_cdp(
    playwright: Any,
    process: subprocess.Popen,
    endpoint: str,
    log_handle: Any,
    log_path: Path,
) -> Any:
    """Attach Playwright using a fresh budget after CDP is already ready."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + PLAYWRIGHT_ATTACH_TIMEOUT_SECONDS
    attach_error = ""

    while loop.time() < deadline:
        if process.poll() is not None:
            log_handle.close()
            raise BrowserRuntimeError(
                "Chromium exited while Playwright was attaching over CDP. "
                f"See {log_path} (exit code {process.returncode})."
            )
        try:
            remaining_ms = max(1_000, int((deadline - loop.time()) * 1000))
            return await playwright.chromium.connect_over_cdp(
                endpoint,
                timeout=min(15_000, remaining_ms),
            )
        except Exception as exc:
            attach_error = str(exc)
            await asyncio.sleep(1)

    process.terminate()
    log_handle.close()
    raise BrowserRuntimeError(
        "Playwright could not attach to the Chromium CDP websocket within "
        f"{PLAYWRIGHT_ATTACH_TIMEOUT_SECONDS} seconds after CDP became ready: "
        f"{attach_error[:300]}. See {log_path}."
    )


async def _connect_external_playwright_over_cdp(playwright: Any, endpoint: str) -> Any:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS
    attach_error = ""

    while loop.time() < deadline:
        try:
            remaining_ms = max(1_000, int((deadline - loop.time()) * 1000))
            return await playwright.chromium.connect_over_cdp(
                endpoint,
                timeout=min(10_000, remaining_ms),
            )
        except Exception as exc:
            attach_error = str(exc)
            await asyncio.sleep(1)

    raise BrowserRuntimeError(
        "Playwright could not attach to the configured Android/native Chromium "
        f"endpoint {endpoint}: {attach_error[:300]}"
    )


async def _select_context_page(
    browser: Any,
    *,
    viewport: Optional[Dict[str, int]],
    resize_viewport: bool,
) -> tuple[Any, Any]:
    """Select a controlled page without guessing from shared tab order."""
    contexts = list(browser.contexts)
    if not contexts:
        raise BrowserRuntimeError("Retained Chromium exposed no default browser context.")
    context = contexts[0]
    pages = list(context.pages)
    if not pages:
        page = await context.new_page()
    elif len(pages) == 1:
        page = pages[0]
    else:
        raise BrowserRuntimeError(
            "Retained Chromium exposed multiple pages without an explicit target; "
            "runtime attachment is fail-closed."
        )
    if resize_viewport:
        await page.set_viewport_size(viewport or {"width": 1280, "height": 900})
    return context, page


@dataclass
class RetainableBrowserRuntime:
    process: Any
    cdp_endpoint: str
    browser_session_id: str
    browser_profile_path: str
    browser_node_id: str
    browser_provider: str
    owns_process: bool
    browser: Any
    context: Any
    page: Any
    session_dir: Path

    async def capture_snapshot(self, *, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.session_dir / "handoff.png"
        storage_state_path = self.session_dir / "storage-state.json"
        html_path = self.session_dir / "page.html"

        await self.page.screenshot(path=str(screenshot_path), type="png", full_page=False)
        storage_state = await self.context.storage_state(path=str(storage_state_path))
        html = await self.page.content()
        html_path.write_text(html, encoding="utf-8")
        fingerprint = await page_fingerprint(self.page)
        storage_hash = hashlib.sha256(
            json.dumps(storage_state, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        return {
            "browser_provider": self.browser_provider,
            "browser_session_id": self.browser_session_id,
            "browser_endpoint": self.cdp_endpoint,
            "browser_node_id": self.browser_node_id,
            "browser_process_id": getattr(self.process, "pid", None),
            "browser_profile_path": self.browser_profile_path,
            "active_page_hint": self.page.url,
            "current_url": self.page.url,
            "current_fingerprint": fingerprint,
            "storage_state_path": str(storage_state_path),
            "storage_state_hash": storage_hash,
            "screenshot_path": str(screenshot_path),
            "html_snapshot_path": str(html_path),
            "metadata": metadata or {},
        }

    def terminate(self, *, remove_profile: bool = False) -> None:
        if self.owns_process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if remove_profile and self.owns_process and self.browser_profile_path:
            profile = Path(self.browser_profile_path)
            try:
                profile.relative_to(self.session_dir)
            except ValueError:
                # Persistent operator profiles must never be deleted by handoff cleanup.
                pass
            else:
                shutil.rmtree(profile, ignore_errors=True)
        if remove_profile:
            shutil.rmtree(self.session_dir, ignore_errors=True)


async def launch_retainable_browser(
    playwright,
    *,
    viewport: Optional[Dict[str, int]] = None,
    profile_dir: Optional[Path | str] = None,
    headless: bool = True,
    executable_path: str = "",
) -> RetainableBrowserRuntime:
    session_id = str(uuid4())
    session_dir = handoff_storage_root() / session_id
    resolved_profile_dir = Path(profile_dir) if profile_dir else session_dir / "profile"
    session_dir.mkdir(parents=True, exist_ok=True)
    resolved_profile_dir.mkdir(parents=True, exist_ok=True)
    port = _reserve_port()
    executable = executable_path or playwright.chromium.executable_path
    log_path = session_dir / "chromium.log"
    log_handle = log_path.open("ab")

    args = [
        executable,
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        *chromium_stability_args(),
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={resolved_profile_dir}",
        "about:blank",
    ]
    if headless:
        args.insert(1, "--headless=new")

    process = subprocess.Popen(
        args,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
        env=_chromium_environment(),
    )
    endpoint = f"http://127.0.0.1:{port}"

    # Android + Ubuntu PRoot can take substantially longer than desktop Linux
    # to expose the CDP websocket. Give readiness and Playwright attachment
    # independent retry budgets so a slow first stage cannot starve the second.
    await _wait_for_cdp_endpoint(process, endpoint, log_handle, log_path)
    browser = await _connect_playwright_over_cdp(
        playwright,
        process,
        endpoint,
        log_handle,
        log_path,
    )

    try:
        context, page = await _select_context_page(
            browser,
            viewport=viewport,
            resize_viewport=True,
        )
    except Exception:
        process.terminate()
        log_handle.close()
        raise

    log_handle.close()
    return RetainableBrowserRuntime(
        process=process,
        cdp_endpoint=endpoint,
        browser_session_id=session_id,
        browser_profile_path=str(resolved_profile_dir),
        browser_node_id=current_browser_node_id(),
        browser_provider="local_cdp",
        owns_process=True,
        browser=browser,
        context=context,
        page=page,
        session_dir=session_dir,
    )


async def attach_retainable_browser(
    playwright: Any,
    *,
    cdp_endpoint: str,
    viewport: Optional[Dict[str, int]] = None,
) -> RetainableBrowserRuntime:
    """Attach to Android/native Chromium without launching or terminating it."""
    endpoint = _normalize_external_cdp_endpoint(cdp_endpoint)
    await _wait_for_external_cdp_endpoint(endpoint)
    browser = await _connect_external_playwright_over_cdp(playwright, endpoint)
    context, page = await _select_context_page(
        browser,
        viewport=viewport,
        resize_viewport=False,
    )

    session_id = str(uuid4())
    session_dir = handoff_storage_root() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return RetainableBrowserRuntime(
        process=ExternalBrowserProcess(endpoint),
        cdp_endpoint=endpoint,
        browser_session_id=session_id,
        browser_profile_path="",
        browser_node_id=current_browser_node_id(),
        browser_provider="local_cdp",
        owns_process=False,
        browser=browser,
        context=context,
        page=page,
        session_dir=session_dir,
    )


async def launch_application_browser(
    playwright,
    *,
    viewport: Optional[Dict[str, int]] = None,
) -> RetainableBrowserRuntime:
    """Use external Android Chromium when configured, otherwise launch locally."""
    settings = get_settings()
    cdp_endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if cdp_endpoint:
        return await attach_retainable_browser(
            playwright,
            cdp_endpoint=cdp_endpoint,
            viewport=viewport,
        )
    return await launch_retainable_browser(
        playwright,
        viewport=viewport,
        profile_dir=Path(settings.application_browser_profile_dir).expanduser(),
        headless=bool(settings.application_browser_headless),
        executable_path=(settings.application_browser_executable or "").strip(),
    )

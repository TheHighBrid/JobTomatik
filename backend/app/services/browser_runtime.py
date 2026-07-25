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
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.ats_base import page_fingerprint
from app.services.browser_handoff import current_browser_node_id


class BrowserRuntimeError(RuntimeError):
    pass


def chromium_stability_args() -> list[str]:
    """Return conservative flags for Chromium in containers and Android/proot.

    ``--disable-gpu`` alone does not prevent Chromium from starting a GPU
    process.  In particular, WebGL may fall back to Mesa's software renderer
    and repeatedly abort the GPU process.  Disabling all 3D APIs and the
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


@dataclass
class RetainableBrowserRuntime:
    process: subprocess.Popen
    cdp_endpoint: str
    browser_session_id: str
    browser_profile_path: str
    browser_node_id: str
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
            "browser_provider": "local_cdp",
            "browser_session_id": self.browser_session_id,
            "browser_endpoint": self.cdp_endpoint,
            "browser_node_id": self.browser_node_id,
            "browser_process_id": self.process.pid,
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
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if remove_profile:
            profile = Path(self.browser_profile_path)
            try:
                profile.relative_to(self.session_dir)
            except ValueError:
                # Persistent operator profiles must never be deleted by handoff cleanup.
                pass
            else:
                shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(self.session_dir, ignore_errors=True) if remove_profile else None


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
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={resolved_profile_dir}",
        *chromium_stability_args(),
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

    last_error = ""
    for _ in range(80):
        if process.poll() is not None:
            log_handle.close()
            raise BrowserRuntimeError(
                "Chromium exited before CDP became available. The dedicated profile may "
                f"already be open in another browser process (exit code {process.returncode})."
            )
        try:
            response = httpx.get(f"{endpoint}/json/version", timeout=0.5)
            if response.status_code == 200 and response.json().get("webSocketDebuggerUrl"):
                break
        except Exception as exc:
            last_error = str(exc)
        await asyncio.sleep(0.1)
    else:
        process.terminate()
        log_handle.close()
        raise BrowserRuntimeError(f"Chromium CDP endpoint did not become ready: {last_error[:200]}")

    try:
        browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=5000)
        contexts = list(browser.contexts)
        if not contexts:
            raise BrowserRuntimeError("Retained Chromium exposed no default browser context.")
        context = contexts[0]
        pages = list(context.pages)
        page = pages[-1] if pages else await context.new_page()
        await page.set_viewport_size(viewport or {"width": 1280, "height": 900})
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
    """Launch JobTomatik's dedicated, persistent application-browser identity."""
    settings = get_settings()
    return await launch_retainable_browser(
        playwright,
        viewport=viewport,
        profile_dir=Path(settings.application_browser_profile_dir).expanduser(),
        headless=bool(settings.application_browser_headless),
        executable_path=(settings.application_browser_executable or "").strip(),
    )

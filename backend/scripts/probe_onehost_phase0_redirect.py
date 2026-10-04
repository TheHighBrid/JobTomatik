"""Adversarial negative control for the Phase 0 fixture redirect boundary."""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.services.onehost_phase0_fixture_runtime import (
    _install_fixture_network_guard,
    _unexpected_observed_requests,
)


class _Counter:
    def __init__(self) -> None:
        self.hits = 0
        self.lock = threading.Lock()

    def increment(self) -> None:
        with self.lock:
            self.hits += 1


def _destination_handler(counter: _Counter):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            counter.increment()
            payload = b"unexpected redirect destination reached"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    return Handler


def _redirect_handler(counter: _Counter, target_url: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            counter.increment()
            self.send_response(302)
            self.send_header("Location", target_url)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format, *_args):
            return

    return Handler


def _start_server(handler) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


async def _probe(output_path: Path) -> dict[str, Any]:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    destination_counter = _Counter()
    redirect_counter = _Counter()
    destination = _start_server(_destination_handler(destination_counter))
    destination_url = f"http://127.0.0.1:{destination.server_port}/escaped"
    redirector = _start_server(_redirect_handler(redirect_counter, destination_url))
    redirect_url = f"http://127.0.0.1:{redirector.server_port}/fixture"

    record: dict[str, Any] = {
        "gate": "onehost-phase0-redirect-negative-control",
        "synthetic": True,
        "expected_url": redirect_url,
        "redirect_destination_url": destination_url,
        "observed_requests": [],
        "blocked_requests": [],
        "navigation_error": None,
        "status": "failed",
    }
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(service_workers="block")
                await _install_fixture_network_guard(context, redirect_url, record)
                page = await context.new_page()
                try:
                    await page.goto(redirect_url, wait_until="domcontentloaded", timeout=10000)
                except PlaywrightError as exc:
                    record["navigation_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            finally:
                await browser.close()
    finally:
        redirector.shutdown()
        redirector.server_close()
        destination.shutdown()
        destination.server_close()

    record["redirect_source_hits"] = redirect_counter.hits
    record["redirect_destination_hits"] = destination_counter.hits
    record["unexpected_observed_requests"] = _unexpected_observed_requests(record, redirect_url)
    redirect_blocks = [
        item
        for item in record["blocked_requests"]
        if item.get("reason") == "fixture_redirect_refused"
    ]
    record["checks"] = {
        "redirect_source_was_requested": redirect_counter.hits == 1,
        "redirect_was_explicitly_blocked": len(redirect_blocks) == 1,
        "redirect_destination_was_never_requested": destination_counter.hits == 0,
        "browser_observed_no_escape": not record["unexpected_observed_requests"],
        "navigation_failed_closed": bool(record["navigation_error"]),
    }
    record["status"] = "passed" if all(record["checks"].values()) else "failed"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if record["status"] != "passed":
        raise RuntimeError(f"Phase 0 redirect negative control failed: {record['checks']}")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = asyncio.run(_probe(args.output))
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

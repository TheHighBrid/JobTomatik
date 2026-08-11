#!/usr/bin/env python3
"""Serve an attested JobTomatik SPA without a Node/Vite runtime."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

IDENTITY_PATH = "/__jobtomatik_frontend_identity"


class StaticFrontendHandler(SimpleHTTPRequestHandler):
    server_version = "JobTomatikStaticFrontend/1"

    def __init__(self, *args, directory: str, manifest: dict, **kwargs):
        self.jobtomatik_manifest = manifest
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"STATIC_FRONTEND {self.address_string()} {fmt % args}", flush=True)

    def _identity(self) -> None:
        payload = json.dumps(
            {
                "ok": True,
                "runtime": "static_artifact",
                "revision": self.jobtomatik_manifest["revision"],
                "dist_tree_sha256": self.jobtomatik_manifest["dist_tree_sha256"],
                "package_lock_sha256": self.jobtomatik_manifest["package_lock_sha256"],
                "final_submit_allowed": False,
                "outreach_authorized": False,
            },
            sort_keys=True,
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == IDENTITY_PATH:
            self._identity()
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == IDENTITY_PATH:
            self._identity()
            return
        super().do_HEAD()

    def end_headers(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path.endswith(".html"):
            self.send_header("Cache-Control", "no-store")
        elif parsed.path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        """Provide BrowserRouter SPA fallback while preserving actual assets/files."""

        translated = Path(super().translate_path(path))
        if translated.exists():
            return str(translated)

        parsed = urlparse(path)
        requested = unquote(parsed.path)
        # Requests that look like a concrete file must remain a real 404. Route-like
        # paths without a suffix fall back to index.html for React BrowserRouter.
        if Path(requested).suffix:
            return str(translated)
        return str(Path(self.directory) / "index.html")

    def guess_type(self, path: str) -> str:
        guessed, _ = mimetypes.guess_type(path)
        return guessed or "application/octet-stream"


def load_manifest(path: Path, root: Path, expected_revision: str) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Frontend manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("artifact_type") != "jobtomatik-static-frontend":
        raise RuntimeError("Frontend manifest identity is invalid")
    if str(manifest.get("revision") or "").lower() != expected_revision.lower():
        raise RuntimeError("Frontend manifest revision does not match runtime revision")
    if not root.is_dir() or not (root / "index.html").is_file():
        raise RuntimeError(f"Frontend dist root is invalid: {root}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()

    root = args.root.resolve()
    manifest_path = args.manifest.resolve()
    manifest = load_manifest(manifest_path, root, args.revision)

    def handler(*handler_args, **handler_kwargs):
        return StaticFrontendHandler(
            *handler_args,
            directory=str(root),
            manifest=manifest,
            **handler_kwargs,
        )

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(
        "JOBTOMATIK_STATIC_FRONTEND_READY "
        f"pid={os.getpid()} revision={manifest['revision']} "
        f"dist_sha256={manifest['dist_tree_sha256']} host={args.host} port={args.port}",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

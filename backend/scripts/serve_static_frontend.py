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
    server_version = "JobTomatikStaticFrontend/2"

    def __init__(
        self,
        *args,
        directory: str,
        manifest: dict,
        index_payload: bytes,
        **kwargs,
    ):
        self.jobtomatik_manifest = manifest
        self.jobtomatik_index_payload = index_payload
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"STATIC_FRONTEND {self.address_string()} {fmt % args}", flush=True)

    def _write_payload(
        self,
        payload: bytes,
        *,
        content_type: str,
        cache_control: str,
        head_only: bool = False,
    ) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _identity(self, *, head_only: bool = False) -> None:
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
        self._write_payload(
            payload,
            content_type="application/json",
            cache_control="no-store",
            head_only=head_only,
        )

    def _spa_shell(self, *, head_only: bool = False) -> None:
        self._write_payload(
            self.jobtomatik_index_payload,
            content_type="text/html; charset=utf-8",
            cache_control="no-store",
            head_only=head_only,
        )

    @staticmethod
    def _is_spa_route(path: str) -> bool:
        parsed = urlparse(path)
        requested = unquote(parsed.path)
        if requested == "/":
            return True
        if requested.startswith("/assets/"):
            return False
        return not bool(Path(requested).suffix)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == IDENTITY_PATH:
            self._identity()
            return
        if self._is_spa_route(self.path):
            self._spa_shell()
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == IDENTITY_PATH:
            self._identity(head_only=True)
            return
        if self._is_spa_route(self.path):
            self._spa_shell(head_only=True)
            return
        super().do_HEAD()

    def end_headers(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/assets/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        """Preserve exact-file serving for immutable build assets."""

        return super().translate_path(path)

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


def load_index_payload(root: Path) -> bytes:
    index_path = root / "index.html"
    payload = index_path.read_bytes()
    if not payload:
        raise RuntimeError(f"Frontend index shell is empty: {index_path}")
    return payload


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
    index_payload = load_index_payload(root)

    def handler(*handler_args, **handler_kwargs):
        return StaticFrontendHandler(
            *handler_args,
            directory=str(root),
            manifest=manifest,
            index_payload=index_payload,
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

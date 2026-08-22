from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from scripts.serve_static_frontend import StaticFrontendHandler, load_index_payload


def _manifest(revision: str) -> dict:
    return {
        "version": 1,
        "artifact_type": "jobtomatik-static-frontend",
        "revision": revision,
        "dist_tree_sha256": "dist-digest",
        "package_lock_sha256": "lock-digest",
    }


def test_spa_shell_is_pinned_at_startup_when_index_path_disappears(tmp_path: Path):
    revision = "a" * 40
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    index = dist / "index.html"
    index.write_text('<!doctype html><div id="root">jobtomatik</div>', encoding="utf-8")
    (assets / "app.js").write_text("console.log('asset')", encoding="utf-8")

    index_payload = load_index_payload(dist)
    handler = partial(
        StaticFrontendHandler,
        directory=str(dist),
        manifest=_manifest(revision),
        index_payload=index_payload,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        # Reproduce the physical Android failure class: the server has already
        # attested and started, but the on-disk shell becomes unavailable later.
        index.unlink()
        base = f"http://127.0.0.1:{server.server_port}"

        with urlopen(base + "/", timeout=2) as response:
            assert response.status == 200
            assert response.read() == index_payload
            assert response.headers["Cache-Control"] == "no-store"

        with urlopen(base + "/shadow-campaigns", timeout=2) as response:
            assert response.status == 200
            assert response.read() == index_payload
            assert response.headers["Cache-Control"] == "no-store"

        with urlopen(base + "/assets/app.js", timeout=2) as response:
            assert response.status == 200
            assert response.read() == b"console.log('asset')"

        with urlopen(base + "/__jobtomatik_frontend_identity", timeout=2) as response:
            payload = json.loads(response.read())
            assert payload["runtime"] == "static_artifact"
            assert payload["revision"] == revision
            assert payload["final_submit_allowed"] is False
            assert payload["outreach_authorized"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

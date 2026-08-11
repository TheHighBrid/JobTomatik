#!/usr/bin/env python3
"""Build the immutable identity manifest for a JobTomatik static frontend artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    """Hash paths, sizes and file contents in stable lexical order."""

    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(payload)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def build_manifest(*, dist: Path, revision: str, package_lock: Path) -> dict:
    revision = revision.strip().lower()
    if not revision or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("revision must be a hexadecimal Git commit SHA")
    if not dist.is_dir() or not (dist / "index.html").is_file():
        raise ValueError(f"frontend dist is missing index.html: {dist}")
    if not package_lock.is_file():
        raise ValueError(f"package lock is missing: {package_lock}")

    return {
        "version": 1,
        "artifact_type": "jobtomatik-static-frontend",
        "revision": revision,
        "package_lock_sha256": sha256_file(package_lock),
        "dist_tree_sha256": sha256_tree(dist),
        "build_api_url": os.environ.get("VITE_API_URL", "http://127.0.0.1:8010"),
        "build_platform": os.environ.get("JOBTOMATIK_FRONTEND_BUILD_PLATFORM", "linux-arm64-ci"),
        "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--package-lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(
        dist=args.dist.resolve(),
        revision=args.revision,
        package_lock=args.package_lock.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "JOBTOMATIK_FRONTEND_ARTIFACT_MANIFEST_READY "
        f"revision={manifest['revision']} dist_sha256={manifest['dist_tree_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

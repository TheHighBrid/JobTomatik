#!/usr/bin/env python3
"""Install the exact CI-built frontend artifact for the checked-out Android revision.

Runtime delivery deliberately uses the repository's public Git transport rather than
GitHub Actions' archive-download API. CI publishes only the generated ``dist/`` plus
its SHA-bound manifest to a dedicated branch. The Android device fetches that branch,
requires its revision marker to equal the checked-out ``main`` commit, archives the
Git objects locally, and verifies the lockfile + dist-tree hashes before installation.
No GitHub API token and no device-side Node/Vite build are required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_RUNTIME_DIR = BACKEND_ROOT / ".runtime"
DEFAULT_ARTIFACT_BRANCH = "android-static-frontend-runtime"
MANIFEST_NAME = "jobtomatik-frontend-manifest.json"
REVISION_MARKER = "JOBTOMATIK_REVISION"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
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


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def current_revision() -> str:
    revision = _git("rev-parse", "HEAD").stdout.strip().lower()
    if not revision or any(char not in "0123456789abcdef" for char in revision):
        raise RuntimeError("Unable to derive exact frontend artifact revision")
    return revision


def _remote_ref(branch: str) -> str:
    return f"refs/remotes/origin/{branch}"


def _fetch_branch(branch: str) -> None:
    result = _git(
        "fetch",
        "--no-tags",
        "--force",
        "origin",
        f"refs/heads/{branch}:{_remote_ref(branch)}",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git fetch failed").strip()
        raise RuntimeError(detail[:1200])


def _show_text(ref: str, path: str) -> str:
    result = _git("show", f"{ref}:{path}", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Published frontend artifact is missing {path}")
    return result.stdout


def _published_ref_for_revision(branch: str, revision: str, timeout_seconds: int) -> str:
    deadline = time.monotonic() + max(0, timeout_seconds)
    last_error = "artifact_branch_not_published_yet"
    while True:
        try:
            _fetch_branch(branch)
            ref = _remote_ref(branch)
            marker = _show_text(ref, REVISION_MARKER).strip().lower()
            manifest = json.loads(_show_text(ref, MANIFEST_NAME))
            manifest_revision = str(manifest.get("revision") or "").strip().lower()
            if marker == revision and manifest_revision == revision:
                return ref
            last_error = (
                "published_revision_mismatch:"
                f"marker={marker or 'missing'} manifest={manifest_revision or 'missing'}"
            )
        except (RuntimeError, ValueError, TypeError) as exc:
            last_error = str(exc)

        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Exact static frontend is unavailable for revision {revision}: {last_error}"
            )
        time.sleep(5)


def _archive_ref(ref: str, destination: Path) -> str:
    published_commit = _git("rev-parse", ref).stdout.strip().lower()
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", "--output", str(destination), ref],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git archive failed").strip()
        raise RuntimeError(detail[:1200])
    return published_commit


def _safe_extract(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with tarfile.open(archive, mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            candidate = (destination / member.name).resolve()
            try:
                candidate.relative_to(destination_resolved)
            except ValueError as exc:
                raise RuntimeError(f"Artifact archive contains unsafe path: {member.name}") from exc
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError(f"Artifact archive contains unsupported entry: {member.name}")
        bundle.extractall(destination, members=members)


def _locate_payload(extracted: Path) -> tuple[Path, Path]:
    manifest_path = extracted / MANIFEST_NAME
    dist = extracted / "dist"
    if not manifest_path.is_file():
        raise RuntimeError(f"Frontend artifact is missing {MANIFEST_NAME}")
    if not dist.is_dir() or not (dist / "index.html").is_file():
        raise RuntimeError("Frontend artifact is missing dist/index.html")
    return manifest_path, dist


def _verify_payload(
    *,
    manifest_path: Path,
    dist: Path,
    revision: str,
    package_lock: Path,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise RuntimeError("Unsupported frontend artifact manifest version")
    if manifest.get("artifact_type") != "jobtomatik-static-frontend":
        raise RuntimeError("Unexpected frontend artifact type")
    if str(manifest.get("revision") or "").lower() != revision:
        raise RuntimeError("Frontend artifact manifest revision does not match checkout")
    if manifest.get("package_lock_sha256") != sha256_file(package_lock):
        raise RuntimeError("Frontend artifact package-lock digest does not match checkout")
    dist_digest = sha256_tree(dist)
    if manifest.get("dist_tree_sha256") != dist_digest:
        raise RuntimeError("Frontend artifact dist tree digest verification failed")
    if str(manifest.get("build_api_url") or "") != "http://127.0.0.1:8010":
        raise RuntimeError("Frontend artifact was not built for the managed Android API endpoint")
    return manifest


def _verify_existing(destination: Path, revision: str, package_lock: Path) -> dict | None:
    manifest_path = destination / MANIFEST_NAME
    dist = destination / "dist"
    if not manifest_path.is_file() or not dist.is_dir():
        return None
    try:
        return _verify_payload(
            manifest_path=manifest_path,
            dist=dist,
            revision=revision,
            package_lock=package_lock,
        )
    except Exception:
        return None


def _prune_artifacts(artifact_root: Path, keep_revision: str, keep: int = 3) -> None:
    rows = []
    for child in artifact_root.iterdir() if artifact_root.exists() else []:
        if not child.is_dir() or child.name.startswith(".") or child.name == keep_revision:
            continue
        try:
            rows.append((child.stat().st_mtime, child))
        except OSError:
            continue
    rows.sort(reverse=True)
    for _, stale in rows[max(0, keep - 1):]:
        shutil.rmtree(stale, ignore_errors=True)


def install(*, artifact_branch: str, runtime_dir: Path, revision: str, wait_seconds: int) -> dict:
    package_lock = REPO_ROOT / "frontend" / "package-lock.json"
    artifact_root = runtime_dir / "frontend-artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    destination = artifact_root / revision
    receipt_path = runtime_dir / "frontend-artifact-receipt.json"

    existing = _verify_existing(destination, revision, package_lock)
    if existing is not None:
        receipt = {
            "version": 1,
            "status": "ready",
            "source": "existing_verified",
            "revision": revision,
            "artifact_branch": artifact_branch,
            "published_commit": None,
            "package_lock_sha256": existing["package_lock_sha256"],
            "dist_tree_sha256": existing["dist_tree_sha256"],
            "artifact_root": str(destination),
            "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    ref = _published_ref_for_revision(artifact_branch, revision, wait_seconds)
    with tempfile.TemporaryDirectory(prefix="jobtomatik-frontend-artifact-", dir=artifact_root) as tmp:
        temp_root = Path(tmp)
        archive = temp_root / "artifact.tar"
        extracted = temp_root / "extracted"
        extracted.mkdir()
        published_commit = _archive_ref(ref, archive)
        archive_digest = sha256_file(archive)
        _safe_extract(archive, extracted)
        manifest_path, dist = _locate_payload(extracted)
        manifest = _verify_payload(
            manifest_path=manifest_path,
            dist=dist,
            revision=revision,
            package_lock=package_lock,
        )

        staged = artifact_root / f".{revision}.installing"
        shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True)
        shutil.copy2(manifest_path, staged / MANIFEST_NAME)
        shutil.copytree(dist, staged / "dist")
        shutil.rmtree(destination, ignore_errors=True)
        staged.replace(destination)

    receipt = {
        "version": 1,
        "status": "ready",
        "source": "git_artifact_branch",
        "revision": revision,
        "artifact_branch": artifact_branch,
        "published_commit": published_commit,
        "archive_sha256": archive_digest,
        "package_lock_sha256": manifest["package_lock_sha256"],
        "dist_tree_sha256": manifest["dist_tree_sha256"],
        "artifact_root": str(destination),
        "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _prune_artifacts(artifact_root, revision)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact-branch",
        default=os.environ.get("JOBTOMATIK_FRONTEND_ARTIFACT_BRANCH", DEFAULT_ARTIFACT_BRANCH),
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=Path(os.environ.get("JOBTOMATIK_RUNTIME_DIR", DEFAULT_RUNTIME_DIR)),
    )
    parser.add_argument("--revision", default=None)
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=int(os.environ.get("JOBTOMATIK_FRONTEND_ARTIFACT_WAIT_SECONDS", "360")),
    )
    args = parser.parse_args()

    revision = (args.revision or current_revision()).strip().lower()
    receipt = install(
        artifact_branch=args.artifact_branch,
        runtime_dir=args.runtime_dir.resolve(),
        revision=revision,
        wait_seconds=args.wait_seconds,
    )
    print(
        "ANDROID_STATIC_FRONTEND_ARTIFACT_READY "
        f"revision={receipt['revision']} dist_sha256={receipt['dist_tree_sha256']} source={receipt['source']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

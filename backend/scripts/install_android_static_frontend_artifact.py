#!/usr/bin/env python3
"""Install the exact CI-built frontend artifact for the checked-out Android revision.

This deliberately removes Node/Vite/native addons from the certification runtime. The
only accepted artifact is one whose GitHub Actions workflow head SHA exactly matches
the checked-out repository revision and whose immutable archive + internal manifest
hashes verify before installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_RUNTIME_DIR = BACKEND_ROOT / ".runtime"
DEFAULT_REPOSITORY = "TheHighBrid/JobTomatik"
ARTIFACT_PREFIX = "jobtomatik-frontend-dist-"


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


def current_revision() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip().lower()
    if not revision or any(char not in "0123456789abcdef" for char in revision):
        raise RuntimeError("Unable to derive exact frontend artifact revision")
    return revision


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "JobTomatik-Android-Frontend-Artifact/1",
    }
    token = (
        os.environ.get("JOBTOMATIK_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or ""
    ).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _artifact_for_revision(repository: str, revision: str) -> dict | None:
    artifact_name = ARTIFACT_PREFIX + revision
    encoded_name = urllib.parse.quote(artifact_name, safe="")
    url = f"https://api.github.com/repos/{repository}/actions/artifacts?name={encoded_name}&per_page=100"
    payload = _request_json(url)
    candidates = []
    for artifact in payload.get("artifacts") or []:
        if artifact.get("name") != artifact_name or artifact.get("expired") is True:
            continue
        workflow = artifact.get("workflow_run") or {}
        if str(workflow.get("head_sha") or "").lower() != revision:
            continue
        candidates.append(artifact)
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return candidates[0]


def _wait_for_artifact(repository: str, revision: str, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + max(0, timeout_seconds)
    last_error: str | None = None
    while True:
        try:
            artifact = _artifact_for_revision(repository, revision)
            if artifact is not None:
                return artifact
            last_error = "artifact_not_published_yet"
        except urllib.error.HTTPError as exc:
            last_error = f"github_http_{exc.code}"
        except urllib.error.URLError as exc:
            last_error = f"github_network_error:{exc.reason}"

        if time.monotonic() >= deadline:
            raise RuntimeError(
                "Exact frontend artifact is unavailable for revision "
                f"{revision}: {last_error or 'not_found'}"
            )
        time.sleep(5)


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        destination_resolved = destination.resolve()
        for member in bundle.infolist():
            candidate = (destination / member.filename).resolve()
            try:
                candidate.relative_to(destination_resolved)
            except ValueError as exc:
                raise RuntimeError(f"Artifact zip contains unsafe path: {member.filename}") from exc
        bundle.extractall(destination)


def _locate_payload(extracted: Path) -> tuple[Path, Path]:
    manifests = list(extracted.rglob("jobtomatik-frontend-manifest.json"))
    if len(manifests) != 1:
        raise RuntimeError(
            "Frontend artifact must contain exactly one jobtomatik-frontend-manifest.json"
        )
    manifest_path = manifests[0]
    dist = manifest_path.parent / "dist"
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
    lock_digest = sha256_file(package_lock)
    if manifest.get("package_lock_sha256") != lock_digest:
        raise RuntimeError("Frontend artifact package-lock digest does not match checkout")
    dist_digest = sha256_tree(dist)
    if manifest.get("dist_tree_sha256") != dist_digest:
        raise RuntimeError("Frontend artifact dist tree digest verification failed")
    if str(manifest.get("build_api_url") or "") != "http://127.0.0.1:8010":
        raise RuntimeError("Frontend artifact was not built for the managed Android API endpoint")
    return manifest


def _verify_existing(destination: Path, revision: str, package_lock: Path) -> dict | None:
    manifest_path = destination / "jobtomatik-frontend-manifest.json"
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


def install(*, repository: str, runtime_dir: Path, revision: str, wait_seconds: int) -> dict:
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
            "artifact_name": ARTIFACT_PREFIX + revision,
            "artifact_id": None,
            "github_artifact_digest": None,
            "archive_sha256": None,
            "package_lock_sha256": existing["package_lock_sha256"],
            "dist_tree_sha256": existing["dist_tree_sha256"],
            "artifact_root": str(destination),
            "installed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return receipt

    artifact = _wait_for_artifact(repository, revision, wait_seconds)
    artifact_id = int(artifact["id"])
    download_url = str(artifact.get("archive_download_url") or "")
    if not download_url:
        raise RuntimeError("GitHub artifact did not provide an archive download URL")

    with tempfile.TemporaryDirectory(prefix="jobtomatik-frontend-artifact-", dir=artifact_root) as tmp:
        temp_root = Path(tmp)
        archive = temp_root / "artifact.zip"
        extracted = temp_root / "extracted"
        extracted.mkdir()
        _download(download_url, archive)
        archive_digest = sha256_file(archive)
        github_digest = str(artifact.get("digest") or "")
        if github_digest.startswith("sha256:") and github_digest.split(":", 1)[1] != archive_digest:
            raise RuntimeError("Downloaded GitHub artifact archive digest did not verify")

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
        shutil.copy2(manifest_path, staged / "jobtomatik-frontend-manifest.json")
        shutil.copytree(dist, staged / "dist")
        shutil.rmtree(destination, ignore_errors=True)
        staged.replace(destination)

    receipt = {
        "version": 1,
        "status": "ready",
        "source": "github_actions",
        "revision": revision,
        "artifact_name": str(artifact.get("name") or ""),
        "artifact_id": artifact_id,
        "github_artifact_digest": str(artifact.get("digest") or "") or None,
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
    parser.add_argument("--repository", default=os.environ.get("JOBTOMATIK_GITHUB_REPOSITORY", DEFAULT_REPOSITORY))
    parser.add_argument("--runtime-dir", type=Path, default=Path(os.environ.get("JOBTOMATIK_RUNTIME_DIR", DEFAULT_RUNTIME_DIR)))
    parser.add_argument("--revision", default=None)
    parser.add_argument("--wait-seconds", type=int, default=int(os.environ.get("JOBTOMATIK_FRONTEND_ARTIFACT_WAIT_SECONDS", "360")))
    args = parser.parse_args()

    revision = (args.revision or current_revision()).strip().lower()
    receipt = install(
        repository=args.repository,
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

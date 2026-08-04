#!/usr/bin/env python3
"""Complete the 30-site Lever Phase A checkpoint from retained artifacts only."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PACKAGE_ROOT = Path("/tmp/day14-packages")
RUN_ID = 30880573048
SOURCE_SHA = "1de9181e710ede2bc8700dbb667f4dfea50726ea"
EXPECTED_IDS = {
    "D8-004",
    "D8-009",
    "D8-010",
    "D8-016",
    "D8-018",
    "D8-020",
    "D8-030",
    "D8-034",
    "D8-036",
    "D8-040",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request_bytes(url: str) -> bytes:
    token = os.environ["GH_TOKEN"]
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JobTomatik-Day14-Cleanup",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location")
        if not location:
            raise RuntimeError("Artifact redirect omitted its signed location") from exc
    redirected = urllib.request.Request(
        location,
        headers={"User-Agent": "JobTomatik-Day14-Cleanup"},
    )
    with urllib.request.urlopen(redirected, timeout=120) as response:
        return response.read()


def _safe_extract(archive: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for info in package.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise RuntimeError(f"Unsafe artifact member: {info.filename}")
        package.extractall(destination)


def _download_packages() -> dict:
    repository = os.environ["GITHUB_REPOSITORY"]
    api = os.environ["GITHUB_API_URL"]
    payload = json.loads(
        _request_bytes(
            f"{api}/repos/{repository}/actions/runs/{RUN_ID}/artifacts?per_page=100"
        )
    )
    prefix = "lever-phase-a-day14-package-"
    suffix = f"-{SOURCE_SHA}"
    artifacts = []
    for artifact in payload.get("artifacts") or []:
        name = str(artifact.get("name") or "")
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        review_id = name[len(prefix) : -len(suffix)]
        if review_id in EXPECTED_IDS:
            artifacts.append((review_id, artifact))

    found_ids = {review_id for review_id, _ in artifacts}
    if found_ids != EXPECTED_IDS or len(artifacts) != 10:
        raise RuntimeError(
            f"Expected ten Day 14 packages, found {sorted(found_ids)}"
        )

    shutil.rmtree(PACKAGE_ROOT, ignore_errors=True)
    (PACKAGE_ROOT / "evidence").mkdir(parents=True)
    receipt = {
        "schema_version": "1.0",
        "source_run_id": RUN_ID,
        "source_sha": SOURCE_SHA,
        "artifacts": [],
    }

    for review_id, artifact in sorted(artifacts):
        artifact_id = int(artifact["id"])
        expected_digest = str(artifact.get("digest") or "")
        if expected_digest.startswith("sha256:"):
            expected_digest = expected_digest.split(":", 1)[1]
        if len(expected_digest) != 64:
            raise RuntimeError(
                f"Artifact {artifact_id} lacks a valid digest for {review_id}"
            )
        archive = _request_bytes(
            f"{api}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
        )
        actual_digest = hashlib.sha256(archive).hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError(
                f"Artifact digest mismatch for {review_id}: "
                f"{actual_digest} != {expected_digest}"
            )

        extract_root = Path("/tmp/day14-artifact-extract") / review_id
        shutil.rmtree(extract_root, ignore_errors=True)
        _safe_extract(archive, extract_root)
        candidates = [
            extract_root / "evidence",
            extract_root / "day14-package" / "evidence",
            extract_root / "backend" / "day14-package" / "evidence",
        ]
        evidence_dir = next((path for path in candidates if path.is_dir()), None)
        if evidence_dir is None:
            matches = list(
                extract_root.rglob(
                    f"lever-phase-a-candidate-{review_id}.csv"
                )
            )
            if len(matches) != 1:
                raise RuntimeError(
                    f"Unable to locate package evidence for {review_id}: {matches}"
                )
            evidence_dir = matches[0].parent
        shutil.copytree(
            evidence_dir,
            PACKAGE_ROOT / "evidence",
            dirs_exist_ok=True,
        )
        receipt["artifacts"].append(
            {
                "review_id": review_id,
                "artifact_id": artifact_id,
                "artifact_digest": expected_digest,
                "name": artifact["name"],
            }
        )

    candidate_ids = {
        path.stem.removeprefix("lever-phase-a-candidate-")
        for path in (PACKAGE_ROOT / "evidence").glob(
            "lever-phase-a-candidate-D8-*.csv"
        )
    }
    if candidate_ids != EXPECTED_IDS:
        raise RuntimeError(
            f"Finalized package set is incomplete: {sorted(candidate_ids)}"
        )
    Path("/tmp/day14-package-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def _patch_importer() -> None:
    path = BACKEND / "scripts/import_lever_day14_packages.py"
    text = path.read_text(encoding="utf-8")
    old = '''            "historical_archive": archive_path.relative_to(
                evidence_root
            ).as_posix(),
'''
    new = '''            "historical_archive": archive_path.relative_to(
                evidence_root.resolve()
            ).as_posix(),
'''
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected one absolute-root correction site, found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _run(*args: str) -> None:
    subprocess.run(args, cwd=BACKEND, check=True)


def _import_and_verify() -> dict:
    _run(
        sys.executable,
        "scripts/import_lever_day14_packages.py",
        "--package-root",
        str(PACKAGE_ROOT),
        "--evidence-root",
        "evidence",
        "--request",
        "evidence/lever-phase-a-day14-request.json",
    )
    _run(
        sys.executable,
        "scripts/evaluate_campaign_days_12_22.py",
        "--lever",
        "evidence/lever-pilot-readiness.json",
        "--output",
        "evidence/campaign-days-12-22.json",
    )
    _run(
        sys.executable,
        "scripts/verify_lever_phase_a_checkpoint.py",
        "--evidence-root",
        "evidence",
        "--output-root",
        "evidence-ci",
    )
    _run(
        sys.executable,
        "scripts/certify_lever_pilot_readiness.py",
        "--baseline",
        "evidence/lever-phase-a-baseline.csv",
        "--ledger",
        "evidence/.missing-phase-b-runtime.jsonl",
        "--json-output",
        "/tmp/lever-day14-certification.json",
        "--markdown-output",
        "/tmp/lever-day14-certification.md",
    )

    readiness = json.loads(
        (BACKEND / "evidence/lever-pilot-readiness.json").read_text()
    )
    checkpoint = json.loads(
        (BACKEND / "evidence/campaign-days-12-22.json").read_text()
    )
    verification = json.loads(
        (BACKEND / "evidence-ci/lever-phase-a-checkpoint-verification.json").read_text()
    )
    summary = readiness["summary"]
    day14 = next(
        item for item in checkpoint["checkpoints"] if item["day"] == 14
    )

    expected = {
        "qualifying_dry_run_count": 30,
        "distinct_site_count": 30,
        "record_count": 31,
        "manual_challenge_boundary_count": 1,
        "phase_a_external_archive_failure_count": 0,
        "phase_a_inspection_failure_count": 0,
        "duplicate_submission_count": 0,
        "false_submitted_count": 0,
        "canonical_maturity": "dry_run",
        "promotion_ready": False,
    }
    for key, value in expected.items():
        if summary.get(key) != value:
            raise RuntimeError(
                f"Final readiness mismatch for {key}: "
                f"{summary.get(key)!r} != {value!r}"
            )
    if summary["gates"]["thirty_qualifying_dry_runs"] is not True:
        raise RuntimeError("The 30-run gate did not pass")
    if summary["gates"]["thirty_distinct_lever_sites"] is not True:
        raise RuntimeError("The 30-site gate did not pass")
    if summary["gates"]["explicit_separate_promotion_approval"] is not False:
        raise RuntimeError("Promotion approval changed")
    if day14["passed"] is not True:
        raise RuntimeError("Day 14 checkpoint did not pass")
    if verification["phase_a_target_reached"] is not True:
        raise RuntimeError("Phase A target verification failed")
    day14_supersession = verification["day14_supersession"]
    if day14_supersession["replacement_count"] != 8:
        raise RuntimeError("Day 14 replacement count mismatch")
    if day14_supersession["addition_count"] != 2:
        raise RuntimeError("Day 14 addition count mismatch")
    if day14_supersession["quota_credit_counted_once"] is not True:
        raise RuntimeError("Day 14 quota credit was not deduplicated")
    if verification["safety"]["final_submit_clicked"] is not False:
        raise RuntimeError("Checkpoint verification recorded a submit click")
    if checkpoint["safety"]["final_submit_clicked"] is not False:
        raise RuntimeError("Campaign checkpoint recorded a submit click")
    if checkpoint["safety"]["maturity_promoted"] is not False:
        raise RuntimeError("Campaign checkpoint promoted maturity")
    return {
        "qualifying_dry_run_count": summary["qualifying_dry_run_count"],
        "distinct_site_count": summary["distinct_site_count"],
        "record_count": summary["record_count"],
        "day14_passed": day14["passed"],
        "final_submit_clicked": False,
        "maturity": summary["canonical_maturity"],
        "promotion_ready": summary["promotion_ready"],
    }


def _verify_freeze() -> None:
    freeze = json.loads(
        (ROOT / "docs/operations/lever-phase-2-measurement-freeze.json").read_text()
    )
    if freeze["contract_version"] != "2026-08-04.day14.1":
        raise RuntimeError(f"Unexpected freeze version: {freeze['contract_version']}")
    for path, expected in freeze["locked_input_blobs"].items():
        actual = subprocess.check_output(
            ["git", "hash-object", path],
            cwd=ROOT,
            text=True,
        ).strip()
        if actual != expected:
            raise RuntimeError(
                f"Frozen blob mismatch for {path}: {actual} != {expected}"
            )


def main() -> None:
    receipt = _download_packages()
    _patch_importer()
    _import_and_verify()
    _verify_freeze()
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    print("FINAL CHECKPOINT VERIFIED: 30 QUALIFIERS, 30 SITES")


if __name__ == "__main__":
    main()

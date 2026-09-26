#!/usr/bin/env python3
"""Fail-closed verifier for retained Ashby real-runtime certification evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def verify(payload: dict) -> list[str]:
    blockers: list[str] = []
    if payload.get("adapter") != "ashby":
        blockers.append("adapter_not_ashby")
    if not payload.get("application_id"):
        blockers.append("missing_application_id")
    target = str(payload.get("target_url") or "")
    if (urlparse(target).hostname or "").lower() != "jobs.ashbyhq.com":
        blockers.append("target_not_ashby")
    if payload.get("runtime") != "android_native_chrome_cdp":
        blockers.append("wrong_runtime")
    if payload.get("confirmation_sufficient") is not True:
        blockers.append("confirmation_not_sufficient")
    if not payload.get("confirmation_evidence_type"):
        blockers.append("missing_confirmation_evidence_type")
    if not payload.get("confirmation_final_url"):
        blockers.append("missing_confirmation_final_url")
    if payload.get("persisted_status") != "applied":
        blockers.append("status_not_applied")
    if payload.get("duplicate_submission_suppressed") is not True:
        blockers.append("duplicate_submission_not_suppressed")
    if payload.get("unknown_answer_policy_respected") is not True:
        blockers.append("unknown_answer_policy_not_proven")
    if payload.get("retained_tab_resume_proven") is not True:
        blockers.append("retained_tab_resume_not_proven")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    blockers = verify(payload)
    print(json.dumps({"certified": not blockers, "blockers": blockers}, indent=2))
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

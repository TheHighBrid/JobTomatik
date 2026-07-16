"""Classify a SmartRecruiters live report without weakening its evidence.

Accepted boundaries are deliberately distinct:

- ``hosted_form_ready``: the hosted application rendered and reached the adapter's
  safe dry-run boundary.
- ``pre_form_anti_bot_handoff``: official public metadata was verified, the live
  platform presented DataDome before form rendering, and no submit action occurred.

The second boundary is not a full-form certification and must never be represented
as one. It proves accurate detection and secure manual-handoff routing only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _reports(payload: Dict[str, Any], mode: str) -> List[Dict[str, Any]]:
    return [item for item in payload.get("reports") or [] if item.get("mode") == mode]


def _datadome_surface(item: Dict[str, Any]) -> bool:
    values = (
        item.get("surface_url"),
        item.get("loaded_url"),
        item.get("url"),
    )
    return any(
        "captcha-delivery.com" in str(value or "").lower()
        or "datadome" in str(value or "").lower()
        for value in values
    )


def _preform_review(exercise: Dict[str, Any]) -> bool:
    for item in exercise.get("review_items") or []:
        if item.get("reason_code") not in {
            "anti_bot_challenge",
            "captcha_detected",
        }:
            continue
        details = item.get("details") or {}
        if details.get("handoff_boundary") == "pre_form":
            return True
        if details.get("provider") == "datadome":
            return True
    return False


def classify(payload: Dict[str, Any], *, require_exercise: bool) -> Dict[str, Any]:
    inspect_items = _reports(payload, "inspect")
    exercise_items = _reports(payload, "exercise")
    inspect = inspect_items[0] if inspect_items else {}
    exercise = exercise_items[0] if exercise_items else {}

    metadata = inspect.get("public_metadata") or {}
    official_metadata_verified = bool(metadata.get("posting_metadata_certified"))
    zero_submit = payload.get("final_submit_clicked") is False and not any(
        item.get("final_submit_clicked") for item in payload.get("reports") or []
    )
    hosted_form_ready = bool(
        inspect.get("passed")
        and inspect.get("adapter") == "smartrecruiters"
        and inspect.get("submit_control_present")
        and official_metadata_verified
        and zero_submit
    )
    pre_form_boundary = bool(
        inspect.get("adapter") == "smartrecruiters"
        and official_metadata_verified
        and _datadome_surface(inspect)
        and int((inspect.get("dom") or {}).get("visible_control_count") or 0) == 0
        and zero_submit
    )

    if require_exercise:
        full_form_exercise = bool(
            exercise.get("passed")
            and exercise.get("adapter") == "smartrecruiters"
            and exercise.get("certification_outcome") in {
                "ready_to_submit",
                "manual_challenge_handoff",
            }
            and int(exercise.get("fields_filled") or 0) > 0
            and any(
                evidence.get("verification") == "passed"
                for evidence in exercise.get("upload_evidence") or []
            )
            and exercise.get("final_submit_clicked") is False
        )
        pre_form_boundary = bool(
            pre_form_boundary
            and exercise.get("adapter") == "smartrecruiters"
            and _preform_review(exercise)
            and int(exercise.get("fields_filled") or 0) == 0
            and not (exercise.get("upload_evidence") or [])
            and exercise.get("final_submit_clicked") is False
        )
        if full_form_exercise:
            boundary = "hosted_form_ready"
            passed = True
        elif pre_form_boundary:
            boundary = "pre_form_anti_bot_handoff"
            passed = True
        else:
            boundary = "uncertified"
            passed = False
    else:
        if hosted_form_ready:
            boundary = "hosted_form_ready"
            passed = True
        elif pre_form_boundary:
            boundary = "pre_form_anti_bot_handoff"
            passed = True
        else:
            boundary = "uncertified"
            passed = False

    return {
        "passed": passed,
        "certified_boundary": boundary,
        "full_hosted_form_certified": boundary == "hosted_form_ready",
        "pre_form_handoff_certified": boundary == "pre_form_anti_bot_handoff",
        "official_metadata_verified": official_metadata_verified,
        "final_submit_clicked": not zero_submit,
        "company_identifier": inspect.get("company_identifier"),
        "posting_id": inspect.get("posting_id"),
        "posting_uuid": inspect.get("posting_uuid"),
        "title": metadata.get("title"),
        "loaded_url": inspect.get("loaded_url"),
        "surface_url": inspect.get("surface_url"),
        "exercise_review_items": exercise.get("review_items") or [],
        "source_report": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--require-exercise", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.report).read_text())
    result = classify(payload, require_exercise=bool(args.require_exercise))
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

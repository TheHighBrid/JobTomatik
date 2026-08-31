#!/usr/bin/env python3
"""List, prepare, inspect, and explicitly review current Lever Phase B materials.

This is a debug/emergency operator fallback. The normal workflow lives in the
JobTomatik UI. It never issues submission approval, changes live flags, queues a
submission worker, or submits an application. Mutations use the same server-side
active-attempt quarantine and exact-bundle binding as the UI/API.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models.user import User
from app.services.lever_phase_b_current_operator import (
    prepare_current_lever_operator_materials,
    review_current_lever_operator_materials,
    show_current_lever_operator_materials,
)
from app.services.lever_phase_b_current_roster import (
    list_current_lever_phase_b_candidates,
)


def _owner(db, email: str) -> User:
    normalized = str(email or "").strip().casefold()
    users = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .all()
    )
    matches = [user for user in users if str(user.email or "").strip().casefold() == normalized]
    if len(matches) != 1:
        raise RuntimeError(
            f"OWNER_RESOLUTION_BLOCKED expected_exact_active_owner observed={len(matches)}"
        )
    return matches[0]


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _displayed_bundle_binding(shown: dict[str, Any]) -> dict[str, Any]:
    materials = dict(shown.get("materials") or {})
    cover = dict(materials.get("cover_letter") or {})
    resume = dict(materials.get("resume_summary") or {})
    cover_preparation = dict(cover.get("preparation") or {})
    resume_preparation = dict(resume.get("preparation") or {})
    cover_digest = str(cover_preparation.get("evidence_digest") or "")
    resume_digest = str(resume_preparation.get("evidence_digest") or "")
    posting_sha256 = str(shown.get("posting_sha256") or "")

    if (
        not cover.get("id")
        or not resume.get("id")
        or not cover.get("version")
        or not resume.get("version")
        or not posting_sha256
        or not cover_digest
        or cover_digest != resume_digest
    ):
        raise RuntimeError(
            "MATERIAL_BUNDLE_STALE current displayed bundle identity is incomplete"
        )

    return {
        "material_ids": {
            "cover_letter": int(cover["id"]),
            "resume_summary": int(resume["id"]),
        },
        "material_versions": {
            "cover_letter": int(cover["version"]),
            "resume_summary": int(resume["version"]),
        },
        "posting_sha256": posting_sha256,
        "evidence_digest": cover_digest,
    }


def _encode_bundle_token(binding: dict[str, Any]) -> str:
    payload = json.dumps(
        binding,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_bundle_token(token: str) -> dict[str, Any]:
    encoded = str(token or "").strip()
    if not encoded:
        raise RuntimeError(
            "MATERIAL_BUNDLE_STALE --bundle-token from the earlier show command is required"
        )
    try:
        padding = "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("MATERIAL_BUNDLE_STALE invalid --bundle-token") from exc
    if not isinstance(value, dict):
        raise RuntimeError("MATERIAL_BUNDLE_STALE invalid --bundle-token payload")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Operate the preparation-only current Lever Phase B material boundary."
    )
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--application-id", type=int)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "list",
        help="Read the current owner-selected Lever Phase B roster without mutation or ranking.",
    )
    sub.add_parser("prepare", help="Generate evidence-backed materials and open review.")
    sub.add_parser(
        "show",
        help="Read the exact latest material bundle and emit its review binding token.",
    )

    review = sub.add_parser("review", help="Record the owner's explicit material decision.")
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--notes", default=None)
    review.add_argument(
        "--bundle-token",
        required=True,
        help="Exact review_binding_token emitted by the earlier show command.",
    )
    review.add_argument(
        "--acknowledgment",
        default=None,
        help="Required for approval: APPROVE LEVER MATERIALS <application_id>",
    )

    args = parser.parse_args()
    if args.command != "list" and args.application_id is None:
        parser.error("--application-id is required for prepare, show, and review")

    db = SessionLocal()
    write_operation = args.command in {"prepare", "review"}
    try:
        user = _owner(db, args.owner_email)
        if args.command == "list":
            result = list_current_lever_phase_b_candidates(db, user)
            db.rollback()
        elif args.command == "prepare":
            result = prepare_current_lever_operator_materials(
                db,
                user,
                application_id=args.application_id,
            )
            db.commit()
        elif args.command == "show":
            result = show_current_lever_operator_materials(
                db,
                user,
                application_id=args.application_id,
            )
            result = {
                **result,
                "review_binding_token": _encode_bundle_token(
                    _displayed_bundle_binding(result)
                ),
            }
            db.rollback()
        else:
            approved = bool(args.approve)
            if approved:
                expected = f"APPROVE LEVER MATERIALS {args.application_id}"
                if str(args.acknowledgment or "").strip() != expected:
                    raise RuntimeError(
                        "MATERIAL_APPROVAL_BLOCKED exact owner acknowledgment required: "
                        + expected
                    )
            bundle = _decode_bundle_token(args.bundle_token)
            result = review_current_lever_operator_materials(
                db,
                user,
                application_id=args.application_id,
                approved=approved,
                notes=args.notes,
                **bundle,
            )
            db.commit()
        _print(result)
        return 0
    except Exception as exc:
        if write_operation:
            db.rollback()
        print(f"CURRENT_LEVER_PHASE_B_MATERIALS_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

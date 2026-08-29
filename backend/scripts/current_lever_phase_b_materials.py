#!/usr/bin/env python3
"""Prepare, inspect, and explicitly review current Lever Phase B materials.

This operator tool never issues submission approval, changes live flags, queues a
submission worker, or submits an application.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models.user import User
from app.services.lever_phase_b_current_materials_v4 import (
    prepare_current_lever_materials,
    review_current_lever_materials,
    show_current_lever_materials,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Operate the preparation-only current Lever Phase B material boundary."
    )
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--application-id", required=True, type=int)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare", help="Generate evidence-backed materials and open review.")
    sub.add_parser("show", help="Read the exact latest material bundle without mutation.")

    review = sub.add_parser("review", help="Record the owner's explicit material decision.")
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--notes", default=None)
    review.add_argument(
        "--acknowledgment",
        default=None,
        help="Required for approval: APPROVE LEVER MATERIALS <application_id>",
    )

    args = parser.parse_args()
    db = SessionLocal()
    write_operation = args.command in {"prepare", "review"}
    try:
        user = _owner(db, args.owner_email)
        if args.command == "prepare":
            result = prepare_current_lever_materials(
                db,
                user,
                application_id=args.application_id,
            )
            db.commit()
        elif args.command == "show":
            result = show_current_lever_materials(
                db,
                user,
                application_id=args.application_id,
            )
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
            result = review_current_lever_materials(
                db,
                user,
                application_id=args.application_id,
                approved=approved,
                notes=args.notes,
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

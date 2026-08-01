from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi import HTTPException

from app import auth


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_FILES = (
    ROOT / "backend" / "requirements.txt",
    ROOT / "backend" / "requirements.termux.txt",
    ROOT / "backend" / "requirements.android-server.txt",
)
VERIFY_SCRIPT = ROOT / "scripts" / "verify.sh"


class _DatabaseMustNotBeQueried:
    def query(self, *_args, **_kwargs):
        raise AssertionError("invalid tokens must be rejected before a database query")


def test_access_token_round_trips_with_pinned_pyjwt() -> None:
    token = auth.create_access_token(
        {"sub": "42"},
        expires_delta=timedelta(minutes=5),
    )

    payload = jwt.decode(
        token,
        auth.settings.secret_key,
        algorithms=[auth.settings.algorithm],
    )

    assert jwt.__version__ == "2.13.0"
    assert payload["sub"] == "42"
    assert isinstance(payload["exp"], int)


def test_expired_pyjwt_token_is_rejected_before_database_access() -> None:
    token = jwt.encode(
        {
            "sub": "42",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        auth.settings.secret_key,
        algorithm=auth.settings.algorithm,
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.get_current_user(token=token, db=_DatabaseMustNotBeQueried())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


def test_all_supported_backend_profiles_use_pyjwt_not_python_jose() -> None:
    for path in REQUIREMENT_FILES:
        requirements = path.read_text(encoding="utf-8")
        assert "PyJWT==2.13.0" in requirements
        assert "python-jose" not in requirements


def test_dependency_gate_audits_pinned_python_requirements() -> None:
    requirements = REQUIREMENT_FILES[0].read_text(encoding="utf-8")
    script = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "pip-audit==2.10.1" in requirements
    assert '"$PYTHON_BIN" -m pip_audit' in script
    assert "-r requirements.txt --progress-spinner off" in script

    full_case = script.split("  full)", 1)[1].split("    ;;", 1)[0]
    assert "dependency_check" in full_case

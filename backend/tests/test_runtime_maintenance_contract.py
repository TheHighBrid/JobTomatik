import json
import re
import warnings
from pathlib import Path

import bcrypt

from app.auth import hash_password, verify_password


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_password_backend_round_trips_and_accepts_existing_bcrypt_hashes():
    password = "correct horse battery staple"

    generated = hash_password(password)
    existing = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    assert generated.startswith(("$2a$", "$2b$", "$2y$"))
    assert verify_password(password, generated) is True
    assert verify_password("wrong password", generated) is False
    assert verify_password(password, existing) is True
    assert verify_password(password, "not-a-bcrypt-hash") is False


def test_dependency_manifests_use_bcrypt_without_passlib():
    manifests = (
        REPO_ROOT / "backend" / "requirements.txt",
        REPO_ROOT / "backend" / "requirements.termux.txt",
        REPO_ROOT / "backend" / "requirements.android-server.txt",
    )

    for path in manifests:
        content = path.read_text(encoding="utf-8")
        assert "passlib" not in content.lower(), path
        assert "bcrypt==4.0.1" in content, path


def test_form_filler_v3_compiles_without_escape_sequence_warnings():
    path = REPO_ROOT / "backend" / "app" / "services" / "form_filler_v3.py"
    source = path.read_text(encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(source, str(path), "exec")


def test_release_version_metadata_is_consistent():
    release_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (REPO_ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    android_gradle = (
        REPO_ROOT / "frontend" / "android" / "app" / "build.gradle"
    ).read_text(encoding="utf-8")
    android_match = re.search(r'versionName\s+"([^"]+)"', android_gradle)

    assert android_match is not None
    assert release_version == "1.0.0"
    assert package["version"] == release_version
    assert package_lock["version"] == release_version
    assert package_lock["packages"][""]["version"] == release_version
    assert android_match.group(1) == release_version

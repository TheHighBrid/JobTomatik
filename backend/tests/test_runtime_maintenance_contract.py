"""Regression coverage for auth, warnings, and release metadata."""

import json
import re
import warnings
from pathlib import Path

import bcrypt
import pytest

from app.auth import hash_password, verify_password
from app.version import APP_VERSION


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


def test_password_backend_enforces_bcrypt_utf8_byte_limit():
    exactly_72_bytes = "é" * 36
    over_72_bytes = exactly_72_bytes + "a"

    generated = hash_password(exactly_72_bytes)
    assert verify_password(exactly_72_bytes, generated) is True

    with pytest.raises(ValueError, match="72 UTF-8 bytes"):
        hash_password(over_72_bytes)
    assert verify_password(over_72_bytes, generated) is False


def test_dependency_manifests_use_supported_bcrypt_without_passlib():
    manifests = (
        REPO_ROOT / "backend" / "requirements.txt",
        REPO_ROOT / "backend" / "requirements.termux.txt",
        REPO_ROOT / "backend" / "requirements.android-server.txt",
    )
    versions: dict[str, tuple[int, int, int]] = {}

    for path in manifests:
        content = path.read_text(encoding="utf-8")
        assert "passlib" not in content.lower(), path

        match = re.search(r"(?m)^bcrypt==(\d+)\.(\d+)\.(\d+)$", content)
        assert match is not None, path
        version = tuple(int(part) for part in match.groups())
        assert (4, 0, 1) <= version < (6, 0, 0), (path, version)
        versions[path.name] = version

    assert len(set(versions.values())) == 1, versions


def test_form_filler_v3_compiles_without_escape_sequence_warnings():
    path = REPO_ROOT / "backend" / "app" / "services" / "form_filler_v3.py"
    source = path.read_text(encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(source, str(path), "exec")


def test_product_release_identity_and_private_package_tracks_are_consistent():
    product_version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (REPO_ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8")
    )
    android_gradle = (
        REPO_ROOT / "frontend" / "android" / "app" / "build.gradle"
    ).read_text(encoding="utf-8")
    backend_main = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    android_name = re.search(r'versionName\s+"([^"]+)"', android_gradle)
    android_code = re.search(r"versionCode\s+(\d+)", android_gradle)

    assert android_name is not None
    assert android_code is not None
    assert product_version == "2.1.0"
    assert APP_VERSION == product_version
    assert android_name.group(1) == product_version
    assert android_code.group(1) == "210"

    # The private npm package is an implementation manifest, not the shipped app version.
    assert package["private"] is True
    assert package["version"] == "1.0.0"
    assert package_lock["version"] == package["version"]
    assert package_lock["packages"][""]["version"] == package["version"]

    assert "from app.version import APP_VERSION" in backend_main
    assert "version=APP_VERSION" in backend_main
    assert backend_main.count('"version": APP_VERSION') == 2
    assert 'version="1.0.0"' not in backend_main
    assert '"version": "1.0.0"' not in backend_main

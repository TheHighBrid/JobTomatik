"""Audit exceptions must match every installed node, including nested copies."""

import importlib.util
import json
from pathlib import Path

import pytest


VALIDATOR_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_npm_audit.py"
spec = importlib.util.spec_from_file_location("node_security_audit", VALIDATOR_PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
ADVISORY = "https://github.com/advisories/GHSA-3pq3-5fj3-cg6v"


@pytest.mark.parametrize("nested_version,expected", [("1.18.1", False), ("1.20.0", True)])
def test_every_axios_node_must_have_reviewed_version(nested_version, expected):
    nodes = ["node_modules/axios", "node_modules/wrapper/node_modules/axios"]
    versions = dict(zip(nodes, ["1.20.0", nested_version]))
    assert audit._advisory_is_reviewed_for_installed_package(
        "axios", ADVISORY, nodes, versions,
    ) is expected


@pytest.mark.parametrize("nodes", [None, [], ["node_modules/missing"], [None], ["node_modules/axios", "node_modules/unresolved/node_modules/axios"]])
def test_unresolved_or_missing_nodes_fail_closed(nodes):
    assert not audit._advisory_is_reviewed_for_installed_package(
        "axios", ADVISORY, nodes, {"node_modules/axios": "1.20.0"},
    )


def test_lockfile_preserves_exact_nested_node_identity(monkeypatch, tmp_path):
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"packages": {
        "node_modules/axios": {"version": "1.20.0"},
        "node_modules/wrapper/node_modules/axios": {"version": "1.18.1"},
    }}))
    monkeypatch.setattr(audit, "PACKAGE_LOCK", lock)
    assert audit._installed_package_versions() == {
        "node_modules/axios": "1.20.0",
        "node_modules/wrapper/node_modules/axios": "1.18.1",
    }


def test_transitive_cycle_cannot_supply_security_provenance():
    findings = {
        "first": {"via": ["second"]},
        "second": {"via": ["first"]},
        "axios": {"via": [{"url": ADVISORY}], "nodes": ["node_modules/axios"]},
    }
    assert not audit._finding_is_reviewed("first", findings, {"node_modules/axios": "1.20.0"})


def test_reviewed_url_cannot_be_attached_to_an_unrelated_package():
    url = next(iter(audit.ALLOWED_ADVISORY_URLS))
    assert not audit._advisory_is_reviewed_for_installed_package(
        "unrelated", url, ["node_modules/unrelated"], {"node_modules/unrelated": "1.0.0"},
    )

"""Operational ATS manifest with canonical roadmap maturity annotations."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ats_maturity import annotate_adapter_manifest
from app.services.ats_registry import ats_certification_manifest as _raw_manifest
from app.services.autonomy_release_loader import load_lever_autonomy_release


def _with_retained_autonomy_release(item: Dict[str, Any]) -> Dict[str, Any]:
    """Attach only the retained Lever release record; maturity still validates it."""

    value = dict(item)
    if str(value.get("name") or "").strip().lower() != "lever":
        return value
    release = load_lever_autonomy_release()
    if release is not None:
        value["autonomy_release"] = release
    return value


def ats_certification_manifest() -> Dict[str, Any]:
    """Return adapter evidence plus the only maturity used for autonomy gates.

    The underlying registry keeps its detailed certification evidence and
    historical labels. This view annotates every adapter with a canonical
    roadmap maturity derived from that evidence and explicit release records.
    A retained Lever promotion file is inert until its signed certification
    manifest validates under the separately configured trusted runtime key.
    """

    raw = dict(_raw_manifest())
    adapters: List[Dict[str, Any]] = [
        annotate_adapter_manifest(_with_retained_autonomy_release(item))
        for item in raw.get("adapters", [])
        if isinstance(item, dict)
    ]
    raw["framework_version"] = "1.6.0"
    raw["maturity_model"] = "roadmap_issue_13_v1"
    raw["adapters"] = adapters

    invariants = dict(raw.get("safety_invariants") or {})
    invariants.update(
        {
            "certification_level_is_descriptive_only": True,
            "maturity_is_derived_from_manifest_evidence": True,
            "autonomous_maturity_requires_explicit_release_gates": True,
            "autonomous_maturity_requires_immutable_certification_manifest": True,
            "autonomous_maturity_requires_trusted_manifest_signature": True,
            "autonomous_manifest_binds_adapter_version_and_release_commit": True,
            "autonomous_manifest_binds_fixture_evidence_and_policy_digests": True,
            "retained_autonomy_release_without_trusted_signature_remains_inert": True,
            "unknown_or_missing_maturity_fails_closed": True,
        }
    )
    raw["safety_invariants"] = invariants
    raw["autonomous_adapters"] = sorted(
        item["name"]
        for item in adapters
        if item.get("maturity") == "certified_autonomous"
        and item.get("autonomous_submission_allowed") is True
    )
    return raw

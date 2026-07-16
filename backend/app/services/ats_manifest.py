"""Operational ATS manifest with canonical roadmap maturity annotations."""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.ats_maturity import annotate_adapter_manifest
from app.services.ats_registry import ats_certification_manifest as _raw_manifest


def ats_certification_manifest() -> Dict[str, Any]:
    """Return adapter evidence plus the only maturity used for autonomy gates.

    The underlying registry keeps its detailed certification evidence and
    historical labels. This view annotates every adapter with a canonical
    roadmap maturity derived from that evidence and explicit release records.
    """

    raw = dict(_raw_manifest())
    adapters: List[Dict[str, Any]] = [
        annotate_adapter_manifest(item)
        for item in raw.get("adapters", [])
        if isinstance(item, dict)
    ]
    raw["framework_version"] = "1.5.0"
    raw["maturity_model"] = "roadmap_issue_13_v1"
    raw["adapters"] = adapters

    invariants = dict(raw.get("safety_invariants") or {})
    invariants.update(
        {
            "certification_level_is_descriptive_only": True,
            "maturity_is_derived_from_manifest_evidence": True,
            "autonomous_maturity_requires_explicit_release_gates": True,
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

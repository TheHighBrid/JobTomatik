#!/usr/bin/env python3
"""Materialize the two narrow Lever Day 14 qualifier fixes."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


compatible = ROOT / "backend/scripts/finalize_lever_phase_a_ready_compatible.py"
replace_once(
    compatible,
    '_TITLE_DASH_PATTERN = re.compile(r"\\s*[-‐‑‒–—―−]\\s*")\n',
    '_TITLE_DASH_PATTERN = re.compile(r"\\s*[-‐‑‒–—―−]+\\s*")\n',
    "title dash pattern",
)

title_test = ROOT / "backend/tests/test_lever_phase_a_title_compat.py"
replace_once(
    title_test,
    '''    assert _normalized_title(
        "Principal Scientist − Applied AI"
    ) == _normalized_title(
        "Principal Scientist - Applied AI"
    )
''',
    '''    assert _normalized_title(
        "Principal Scientist − Applied AI"
    ) == _normalized_title(
        "Principal Scientist - Applied AI"
    )
    assert _normalized_title(
        "Product Manager-— Workspace"
    ) == _normalized_title(
        "Product Manager - Workspace"
    )
''',
    "double-dash title regression",
)

lever = ROOT / "backend/app/services/lever_certification.py"
helper_anchor = '''def build_synthetic_profile(dom_inventory: Dict[str, Any]) -> Dict[str, Any]:
    policies: List[Dict[str, Any]] = []
    for policy_id, record in enumerate(
        dom_inventory.get("required_custom_controls") or [], start=1
    ):
        descriptor = str(record.get("descriptor") or "").strip()
        if not descriptor:
            continue
        classification = classify_question(descriptor)
        answer = choose_synthetic_answer(
            descriptor,
            list(record.get("options") or []),
            control_type=str(record.get("control_type") or "text"),
        )
        canonical_key = classification.get("canonical_key")
        if canonical_key == "custom.unclassified":
            canonical_key = f"custom.lever_synthetic_{policy_id}"
        policies.append(
            _synthetic_policy(
                policy_id,
                canonical_key=str(canonical_key),
                category=str(
                    classification.get("category") or "synthetic_certification"
                ),
                sensitivity=str(
                    classification.get("sensitivity") or "synthetic"
                ),
                answer=answer,
                descriptor=descriptor,
            )
        )
'''
helper_replacement = '''_APPLICATION_SOURCE_MARKERS = (
    "indeed",
    "glassdoor",
    "referral",
    "employee",
    "career site",
    "company website",
    "job board",
    "monster",
    "career fair",
    "talent acquisition",
    "recruiter",
)


def _application_source_group_plan(
    records: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], set[int]]:
    """Identify only unmistakable synthetic application-source choice groups.

    Lever sometimes omits the question legend and exposes each option as a separate
    required record. Grouping is allowed only when the controls share one non-empty
    name, are native choice controls, expose LinkedIn, and contain at least two other
    independent recruitment-source markers. This helper is used only to build the
    fictional certification profile and is never part of real-user answer selection.
    """

    grouped: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any]]]] = {}
    for index, record in enumerate(records):
        name = str(record.get("name") or "").strip()
        control_type = str(record.get("control_type") or "").strip()
        if not name or control_type not in {"radio", "checkbox"}:
            continue
        grouped.setdefault((name, control_type), []).append((index, record))

    plans: Dict[int, Dict[str, Any]] = {}
    member_indices: set[int] = set()
    for (name, control_type), members in grouped.items():
        if len(members) < 2:
            continue
        option_text: List[str] = []
        for _, record in members:
            option_text.extend(str(value) for value in record.get("options") or [])
        normalized = _normalize(" ".join(option_text))
        if "linkedin" not in normalized:
            continue
        markers = {
            marker for marker in _APPLICATION_SOURCE_MARKERS
            if marker in normalized
        }
        if len(markers) < 2:
            continue

        first_index = members[0][0]
        indices = {index for index, _ in members}
        plans[first_index] = {
            "name": name,
            "control_type": control_type,
            "answer": "LinkedIn",
            "indices": indices,
            "markers": sorted(markers),
        }
        member_indices.update(indices)
    return plans, member_indices


def build_synthetic_profile(dom_inventory: Dict[str, Any]) -> Dict[str, Any]:
    policies: List[Dict[str, Any]] = []
    records = list(dom_inventory.get("required_custom_controls") or [])
    source_plans, source_members = _application_source_group_plan(records)
    next_policy_id = 1

    for index, record in enumerate(records):
        source_plan = source_plans.get(index)
        if source_plan is not None:
            policies.append(
                _synthetic_policy(
                    next_policy_id,
                    canonical_key="custom.application_source",
                    category="application_source",
                    sensitivity="standard",
                    answer=str(source_plan["answer"]),
                    descriptor=str(source_plan["name"]),
                )
            )
            next_policy_id += 1
            continue
        if index in source_members:
            continue

        descriptor = str(record.get("descriptor") or "").strip()
        if not descriptor:
            continue
        classification = classify_question(descriptor)
        answer = choose_synthetic_answer(
            descriptor,
            list(record.get("options") or []),
            control_type=str(record.get("control_type") or "text"),
        )
        canonical_key = classification.get("canonical_key")
        if canonical_key == "custom.unclassified":
            canonical_key = f"custom.lever_synthetic_{next_policy_id}"
        policies.append(
            _synthetic_policy(
                next_policy_id,
                canonical_key=str(canonical_key),
                category=str(
                    classification.get("category") or "synthetic_certification"
                ),
                sensitivity=str(
                    classification.get("sensitivity") or "synthetic"
                ),
                answer=answer,
                descriptor=descriptor,
            )
        )
        next_policy_id += 1
'''
replace_once(
    lever,
    helper_anchor,
    helper_replacement,
    "synthetic profile policy loop",
)

synthetic_test = ROOT / "backend/tests/test_lever_synthetic_certification.py"
replace_once(
    synthetic_test,
    '''from app.services.lever_certification import (
    SYNTHETIC_LOCATION,
    build_synthetic_profile,
    choose_synthetic_answer,
    inspect_lever_application_dom,
)
''',
    '''from app.services.control_policy import resolve_control_policy
from app.services.lever_certification import (
    SYNTHETIC_LOCATION,
    build_synthetic_profile,
    choose_synthetic_answer,
    inspect_lever_application_dom,
)
''',
    "synthetic test imports",
)
synthetic_test.write_text(
    synthetic_test.read_text(encoding="utf-8")
    + '''\n\ndef test_application_source_group_collapses_to_one_synthetic_policy() -> None:
    name = "cards[source-question][field0]"
    options = [
        "Linkedin",
        "Glassdoor",
        "Indeed",
        "Current/Former Employee",
        "School/Alumni Job Board",
        "Monster",
        "Career Fair",
        "Other",
    ]
    inventory = {
        "required_custom_controls": [
            {
                "descriptor": f"{name} | {option}",
                "control_type": "radio",
                "required": True,
                "options": options,
                "name": name,
                "id": "",
            }
            for option in options[1:]
        ],
        "controls": [],
    }

    profile = build_synthetic_profile(inventory)
    source_policies = [
        policy for policy in profile["answer_policies"]
        if policy["canonical_key"] == "custom.application_source"
    ]

    assert len(source_policies) == 1
    policy = source_policies[0]
    assert policy["match_phrases"] == [name]
    assert policy["answer_value"] == "LinkedIn"
    assert policy["category"] == "application_source"
    assert policy["consent_metadata"]["synthetic_only"] is True

    resolved = resolve_control_policy(f"{name} | Linkedin", profile["answer_policies"])
    assert resolved["can_autofill"] is True
    assert resolved["answer"] == "LinkedIn"
    assert resolved["policy"]["id"] == policy["id"]


def test_application_source_group_does_not_reclassify_generic_link_group() -> None:
    name = "cards[social-profile][field0]"
    options = ["Linkedin", "Twitter", "Other"]
    inventory = {
        "required_custom_controls": [
            {
                "descriptor": f"{name} | {option}",
                "control_type": "radio",
                "required": True,
                "options": options,
                "name": name,
                "id": "",
            }
            for option in options
        ],
        "controls": [],
    }

    profile = build_synthetic_profile(inventory)
    assert not any(
        policy["canonical_key"] == "custom.application_source"
        for policy in profile["answer_policies"]
    )
''',
    encoding="utf-8",
)

print("Materialized final Lever Day 14 qualifier fixes")

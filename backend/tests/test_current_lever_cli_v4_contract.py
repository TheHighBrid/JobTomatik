from pathlib import Path


def test_current_lever_cli_routes_mutations_through_fail_closed_operator_service():
    script = Path(__file__).resolve().parents[1] / "scripts" / "current_lever_phase_b_materials.py"
    text = script.read_text(encoding="utf-8")

    assert "lever_phase_b_current_operator" in text
    assert "prepare_current_lever_operator_materials" in text
    assert "review_current_lever_operator_materials" in text
    assert "show_current_lever_operator_materials" in text
    assert "_displayed_bundle_binding" in text
    assert "APPROVE LEVER MATERIALS <application_id>" in text
    assert "submission worker" in text
    assert "debug/emergency operator fallback" in text


def test_current_lever_cli_exposes_read_only_roster_without_ranking():
    script = Path(__file__).resolve().parents[1] / "scripts" / "current_lever_phase_b_materials.py"
    text = script.read_text(encoding="utf-8")

    assert "lever_phase_b_current_roster" in text
    assert 'sub.add_parser(\n        "list"' in text
    assert 'args.command != "list" and args.application_id is None' in text
    assert "without mutation or ranking" in text

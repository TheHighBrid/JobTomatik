from pathlib import Path


def test_current_lever_cli_routes_prepare_through_v5_service():
    script = Path(__file__).resolve().parents[1] / "scripts" / "current_lever_phase_b_materials.py"
    text = script.read_text(encoding="utf-8")

    assert "lever_phase_b_current_materials_v5" in text
    assert "APPROVE LEVER MATERIALS <application_id>" in text
    assert "submission worker" in text


def test_current_lever_cli_exposes_read_only_roster_without_ranking():
    script = Path(__file__).resolve().parents[1] / "scripts" / "current_lever_phase_b_materials.py"
    text = script.read_text(encoding="utf-8")

    assert "lever_phase_b_current_roster" in text
    assert 'sub.add_parser(\n        "list"' in text
    assert 'args.command != "list" and args.application_id is None' in text
    assert "without mutation or ranking" in text

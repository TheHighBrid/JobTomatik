from pathlib import Path


def test_current_lever_cli_routes_prepare_through_v4_service():
    script = Path(__file__).resolve().parents[1] / "scripts" / "current_lever_phase_b_materials.py"
    text = script.read_text(encoding="utf-8")

    assert "lever_phase_b_current_materials_v4" in text
    assert "APPROVE LEVER MATERIALS <application_id>" in text
    assert "submission worker" in text

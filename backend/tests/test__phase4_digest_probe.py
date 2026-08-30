from pathlib import Path

from app.services.phase4_candidate_gate import _current_component_digests


def test_phase4_lever_digest_probe():
    root = Path(__file__).resolve().parents[1]
    lever = _current_component_digests(root)["lever"]
    raise AssertionError(
        "PHASE4_LEVER_DIGEST_PROBE "
        f"source={lever['source_digest']} fixture={lever['fixture_digest']}"
    )

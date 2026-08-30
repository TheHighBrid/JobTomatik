from pathlib import Path

from app.services.phase4_candidate_gate import SOURCE_PATHS, _digest_paths, _fixture_paths


def test_phase4_lever_digest_probe():
    root = Path(__file__).resolve().parents[2]
    source = _digest_paths(root, [root / item for item in SOURCE_PATHS["lever"]])
    fixture = _digest_paths(root, _fixture_paths(root, "lever"))
    raise AssertionError(
        "PHASE4_LEVER_DIGEST_PROBE "
        f"source={source} fixture={fixture}"
    )

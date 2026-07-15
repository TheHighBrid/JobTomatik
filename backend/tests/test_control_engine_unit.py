from app.services.control_engine import (
    OptionRecord,
    certification_manifest,
    match_answers_to_options,
    parse_policy_answers,
)


def test_parse_policy_answers_preserves_commas_but_supports_explicit_lists():
    assert parse_policy_answers("Ottawa, Ontario") == ["Ottawa, Ontario"]
    assert parse_policy_answers('["Remote", "Hybrid"]') == ["Remote", "Hybrid"]
    assert parse_policy_answers("Remote; Hybrid") == ["Remote", "Hybrid"]


def test_exact_and_boolean_option_matching():
    options = [
        OptionRecord(key="yes", label="Yes", value="Y"),
        OptionRecord(key="no", label="No", value="N"),
    ]
    assert match_answers_to_options(["yes"], options, allow_multiple=False).matched[0].key == "yes"
    assert match_answers_to_options(["false"], options, allow_multiple=False).matched[0].key == "no"


def test_ambiguous_partial_match_is_rejected():
    options = [
        OptionRecord(key="citizen", label="Yes - citizen", value="citizen"),
        OptionRecord(key="resident", label="Yes - permanent resident", value="resident"),
    ]
    result = match_answers_to_options(["Yes"], options, allow_multiple=False)
    assert result.ok is False
    assert "Yes" in result.ambiguous_answers


def test_multi_answer_requires_every_answer_to_match():
    options = [
        OptionRecord(key="remote", label="Remote", value="remote"),
        OptionRecord(key="hybrid", label="Hybrid", value="hybrid"),
        OptionRecord(key="onsite", label="On-site", value="onsite"),
    ]
    result = match_answers_to_options(["Remote", "Hybrid"], options, allow_multiple=True)
    assert result.ok is True
    assert {item.key for item in result.matched} == {"remote", "hybrid"}

    missing = match_answers_to_options(["Remote", "Moon base"], options, allow_multiple=True)
    assert missing.ok is False
    assert missing.missing_answers == ["Moon base"]


def test_certification_manifest_never_overclaims_universal_coverage():
    manifest = certification_manifest()
    assert manifest["certification_level"] == "standards_fixture_certified"
    assert manifest["universally_certified"] is False
    assert all(manifest["safety_invariants"].values())

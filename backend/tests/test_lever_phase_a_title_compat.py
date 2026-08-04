from scripts.finalize_lever_phase_a_ready_compatible import _normalized_title


def test_title_normalization_accepts_typography_only_dash_variants():
    assert _normalized_title(
        "Lead Data Scientist — Growth & Experimentation"
    ) == _normalized_title(
        "Lead Data Scientist - Growth & Experimentation"
    )
    assert _normalized_title(
        "Staff Data Scientist– Pricing Science"
    ) == _normalized_title(
        "Staff Data Scientist - Pricing Science"
    )
    assert _normalized_title(
        "Principal Scientist − Applied AI"
    ) == _normalized_title(
        "Principal Scientist - Applied AI"
    )


def test_title_normalization_does_not_hide_word_changes():
    assert _normalized_title(
        "Staff Data Scientist - Pricing Science"
    ) != _normalized_title(
        "Senior Data Scientist - Pricing Science"
    )

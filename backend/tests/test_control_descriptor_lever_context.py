import asyncio

from app.services.control_descriptors import element_descriptor
from app.services.control_policy import classify_control_question


class _LeverRadioElement:
    async def evaluate(self, script):
        # Regression guard: hosted Lever questions often provide their human prompt
        # only through the .application-question wrapper rather than fieldset/ARIA.
        assert ".application-question" in script
        assert ":scope > label" in script
        return (
            "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0] | Yes | "
            "Are you physically located in Canada and legally authorized to work in Canada for any employer?"
        )


class _LeverCurrentCardElement:
    async def evaluate(self, script):
        # Current live Lever specimens can expose only an opaque cards[uuid][fieldN]
        # identity on the control while the human question is held by a nearby card
        # wrapper. The extractor must use a bounded nearest-ancestor fallback rather
        # than treating that opaque implementation identifier as the question.
        assert "for (let depth = 0; node && depth < 6" in script
        assert "cards\\\\[[^\\\\]]+\\\\]\\\\[field\\\\d+\\\\]" in script
        assert "child.contains(el)" in script
        return (
            "cards[f8056f26-ebef-4939-822f-7a39881a02b7][field0] | No | "
            "Are you based in Canada?"
        )


def test_lever_radio_descriptor_retains_human_question_context():
    descriptor = asyncio.run(element_descriptor(None, _LeverRadioElement()))

    assert "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0]" in descriptor
    assert "legally authorized to work in Canada" in descriptor
    assert classify_control_question(descriptor)["canonical_key"] == "work_authorization"


def test_current_lever_card_descriptor_retains_nearby_human_prompt():
    descriptor = asyncio.run(element_descriptor(None, _LeverCurrentCardElement()))

    assert "cards[f8056f26-ebef-4939-822f-7a39881a02b7][field0]" in descriptor
    assert "Are you based in Canada?" in descriptor
    assert classify_control_question(descriptor)["canonical_key"] != "custom.unclassified"

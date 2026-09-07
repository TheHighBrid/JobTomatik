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


def test_lever_radio_descriptor_retains_human_question_context():
    descriptor = asyncio.run(element_descriptor(None, _LeverRadioElement()))

    assert "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0]" in descriptor
    assert "legally authorized to work in Canada" in descriptor
    assert classify_control_question(descriptor)["canonical_key"] == "work_authorization"

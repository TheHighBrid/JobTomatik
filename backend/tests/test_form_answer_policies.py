import pytest

from app.services.form_filler import _fill_select_fields


class FakeOption:
    def __init__(self, value, label, disabled=False):
        self.value = value
        self.label = label
        self.disabled = disabled

    async def get_attribute(self, name):
        if name == "value":
            return self.value
        if name == "disabled" and self.disabled:
            return ""
        return None

    async def inner_text(self):
        return self.label


class FakeSelect:
    def __init__(self, descriptor, options, required=True):
        self.descriptor = descriptor
        self.options = options
        self.required = required
        self.selected = None

    async def get_attribute(self, name):
        if name == "aria-label":
            return self.descriptor
        if name == "required" and self.required:
            return ""
        if name == "aria-required":
            return "true" if self.required else "false"
        return None

    async def query_selector_all(self, selector):
        return self.options if selector == "option" else []

    async def select_option(self, value):
        self.selected = value


class FakePage:
    def __init__(self, selects):
        self.selects = selects

    async def query_selector_all(self, selector):
        return self.selects if selector == "select" else []

    async def query_selector(self, selector):
        return None


@pytest.mark.asyncio
async def test_required_select_without_policy_does_not_choose_fallback():
    select = FakeSelect(
        "Are you legally authorized to work in Canada?",
        [FakeOption("", "Select"), FakeOption("yes", "Yes"), FakeOption("no", "No")],
    )
    log = []
    review_items = []

    filled = await _fill_select_fields(FakePage([select]), [], log, review_items)

    assert filled == 0
    assert select.selected is None
    assert review_items[0]["reason_code"] == "legal_answer_missing"
    assert review_items[0]["details"]["canonical_key"] == "work_authorization"


@pytest.mark.asyncio
async def test_required_select_uses_only_confirmed_autofill_policy():
    select = FakeSelect(
        "Are you legally authorized to work in Canada?",
        [FakeOption("", "Select"), FakeOption("yes", "Yes"), FakeOption("no", "No")],
    )
    policies = [{
        "canonical_key": "work_authorization",
        "category": "work_authorization",
        "sensitivity": "legal",
        "mode": "answer",
        "answer_value": "Yes",
        "answer_label": "Yes",
        "match_phrases": [],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T10:00:00",
    }]
    log = []
    review_items = []

    filled = await _fill_select_fields(FakePage([select]), policies, log, review_items)

    assert filled == 1
    assert select.selected == "yes"
    assert review_items == []

import pytest

from app.services.ats_lever import LeverAdapter


class _BodyLocator:
    def __init__(self, text: str):
        self._text = text

    async def inner_text(self):
        return self._text


class _Element:
    def __init__(self, text: str, *, visible: bool = True):
        self._text = text
        self._visible = visible

    async def is_visible(self):
        return self._visible

    async def inner_text(self):
        return self._text


class _Surface:
    def __init__(self, *, url: str, body: str, selectors=None):
        self.url = url
        self._body = body
        self._selectors = selectors or {}

    def locator(self, selector: str):
        assert selector == "body"
        return _BodyLocator(self._body)

    async def query_selector(self, selector: str):
        text = self._selectors.get(selector)
        return _Element(text) if text is not None else None


class _TestLeverAdapter(LeverAdapter):
    def __init__(self, *, after_fingerprint: str, submit_control_present: bool):
        self._after_fingerprint = after_fingerprint
        self._submit_control_present = submit_control_present

    async def step_fingerprint(self, surface):
        return self._after_fingerprint

    async def find_submit_button(self, surface):
        return object() if self._submit_control_present else None


@pytest.mark.asyncio
async def test_strong_phrase_requires_url_transition_when_not_in_confirmation_selector():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=False,
    )
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/thanks",
        body="Thanks for applying. Our team will review your application.",
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url="https://jobs.lever.co/example/posting/apply",
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    assert evidence[0].is_sufficient is True
    assert evidence[0].evidence_type == "success_banner"
    assert evidence[0].confirmation_text == "thanks for applying"
    assert evidence[0].metadata["confirmation_basis"] == "strong_phrase_plus_url_change"


@pytest.mark.asyncio
async def test_weak_phrase_requires_confirmation_route_and_submit_control_absence():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=False,
    )
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/thanks",
        body="Thank you for your interest. We'll be in touch.",
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url="https://jobs.lever.co/example/posting/apply",
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    assert evidence[0].is_sufficient is True
    assert evidence[0].metadata["confirmation_basis"] == (
        "weak_phrase_plus_confirmation_route"
    )


@pytest.mark.asyncio
async def test_weak_phrase_does_not_certify_disabled_inflight_submit_state():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=False,
    )
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/apply",
        body="Thank you for your interest in Example. We'll be in touch.",
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url=surface.url,
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    item = evidence[0]
    assert item.is_sufficient is False
    assert item.evidence_type == "post_submit_diagnostic"
    assert item.metadata["submit_control_present"] is False
    assert item.metadata["fingerprint_changed"] is True
    assert item.metadata["url_changed"] is False
    assert item.metadata["weak_confirmation_phrase"] in {
        "we'll be in touch",
        "thank you for your interest",
    }


@pytest.mark.asyncio
async def test_preexisting_application_sent_copy_never_certifies_same_url():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=False,
    )
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/apply",
        body="Application sent by email will not be considered.",
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url=surface.url,
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    item = evidence[0]
    assert item.is_sufficient is False
    assert item.evidence_type == "post_submit_diagnostic"
    assert item.metadata["strong_confirmation_phrase"] is None
    assert item.metadata["url_changed"] is False


@pytest.mark.asyncio
async def test_confirmation_miss_returns_durable_structured_diagnostic():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=True,
    )
    surface = _Surface(
        url="https://jobs.lever.co/fullscript/posting/apply",
        body="Technical Support Specialist Fullscript",
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url=surface.url,
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    item = evidence[0]
    assert item.is_sufficient is False
    assert item.evidence_type == "post_submit_diagnostic"
    assert item.confirmation_text == (
        "Submit action occurred; explicit confirmation was not detected."
    )
    assert item.metadata == {
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "confirmation_url": False,
        "url_changed": False,
        "fingerprint_changed": True,
        "submit_control_present": True,
        "post_submit_diagnostic": True,
        "submit_clicked": True,
        "before_url": surface.url,
        "before_fingerprint": "before",
        "after_fingerprint": "after",
        "strong_confirmation_phrase": None,
        "weak_confirmation_phrase": None,
    }


@pytest.mark.asyncio
async def test_visible_confirmation_selector_remains_sufficient_on_same_url():
    adapter = _TestLeverAdapter(
        after_fingerprint="after",
        submit_control_present=False,
    )
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/apply",
        body="",
        selectors={
            "#application-confirmation": "Application successfully submitted",
        },
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url=surface.url,
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    assert evidence[0].is_sufficient is True
    assert evidence[0].evidence_type == "confirmation_page"
    assert evidence[0].selector == "#application-confirmation"

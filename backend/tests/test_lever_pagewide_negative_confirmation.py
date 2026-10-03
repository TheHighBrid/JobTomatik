import pytest

from app.services.ats_lever import LeverAdapter


class _BodyLocator:
    def __init__(self, text: str):
        self._text = text

    async def inner_text(self):
        return self._text


class _Element:
    def __init__(self, text: str):
        self._text = text

    async def is_visible(self):
        return True

    async def inner_text(self):
        return self._text


class _Surface:
    def __init__(self, *, url: str, body: str, confirmation: str):
        self.url = url
        self._body = body
        self._confirmation = confirmation

    def locator(self, selector: str):
        assert selector == "body"
        return _BodyLocator(self._body)

    async def query_selector(self, selector: str):
        if selector == ".application-confirmation":
            return _Element(self._confirmation)
        return None


class _TestLeverAdapter(LeverAdapter):
    async def step_fingerprint(self, surface):
        return "after"

    async def visible_submit_control_present(self, surface):
        return False


@pytest.mark.asyncio
async def test_positive_confirmation_container_with_pagewide_failure_never_certifies():
    adapter = _TestLeverAdapter()
    confirmation = "Thank you for applying. Your application has been submitted."
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/confirmation",
        body=(
            f"{confirmation} "
            "There was a problem processing your application. Please try again."
        ),
        confirmation=confirmation,
    )

    evidence = await adapter.detect_confirmation(
        surface,
        before_url="https://jobs.lever.co/example/posting/apply",
        before_fingerprint="before",
    )

    assert len(evidence) == 1
    item = evidence[0]
    assert item.is_sufficient is False
    assert item.evidence_type == "post_submit_diagnostic"
    assert item.metadata["confirmation_url"] is True
    assert item.metadata["url_changed"] is True
    assert item.metadata["negative_confirmation_copy"] is True

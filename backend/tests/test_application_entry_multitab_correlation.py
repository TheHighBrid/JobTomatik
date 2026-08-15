from __future__ import annotations

import asyncio

import pytest

from app.services import application_entry_runtime
from app.services.application_entry_runtime import (
    continue_from_employer_landing,
    correlated_external_target_from_browser,
    open_application_entry,
)
from app.services import (
    application_target_handoff,
    application_target_resolver,
    form_filler_handoff,
)


class _Context:
    def __init__(self, pages):
        self.pages = pages


class _StaticPage:
    def __init__(self, url: str, *, opener=None):
        self.url = url
        self.context = None
        self._opener = opener

    async def opener(self):
        return self._opener


class _ApplyControl:
    def __init__(
        self,
        page,
        *,
        href: str = "",
        popup_url: str = "",
        emit_popup: bool = True,
    ):
        self.page = page
        self.href = href
        self.popup_url = popup_url
        self.emit_popup = emit_popup

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def get_attribute(self, name):
        if name == "href":
            return self.href
        if name == "aria-label":
            return "Apply for this job"
        return None

    async def inner_text(self):
        return "Apply for this job"

    async def click(self, timeout=None):
        if self.popup_url:
            popup = _StaticPage(self.popup_url, opener=self.page)
            popup.context = self.page.context
            self.page.context.pages.append(popup)
            if self.emit_popup:
                for listener in list(self.page._listeners.get("popup", [])):
                    listener(popup)


class _ControlledPage:
    def __init__(
        self,
        url: str,
        *,
        href: str = "",
        popup_url: str = "",
        emit_popup: bool = True,
    ):
        self.url = url
        self.form_open = False
        self.frames = []
        self.main_frame = self
        self.control = _ApplyControl(
            self,
            href=href,
            popup_url=popup_url,
            emit_popup=emit_popup,
        )
        self.context = None
        self.goto_calls = []
        self._listeners = {}

    def on(self, event, listener):
        self._listeners.setdefault(event, []).append(listener)

    def remove_listener(self, event, listener):
        listeners = self._listeners.get(event, [])
        if listener in listeners:
            listeners.remove(listener)

    async def evaluate(self, _script):
        return {
            "visibleControls": 8 if self.form_open else 0,
            "applicantControls": 4 if self.form_open else 0,
            "uploadControls": 1 if self.form_open else 0,
            "emailControls": 1 if self.form_open else 0,
            "submitControls": 1 if self.form_open else 0,
            "url": self.url,
        }

    async def query_selector_all(self, selector):
        lowered = selector.lower()
        if "apply for this job" in lowered or "apply now" in lowered:
            return [self.control]
        if self.url.startswith("https://www.linkedin.com/") and "apply" in lowered:
            return [self.control]
        return []

    async def goto(self, url, **_kwargs):
        self.goto_calls.append(url)
        self.url = url
        if url.rstrip("/").endswith("/apply"):
            self.form_open = True

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None

    async def wait_for_timeout(self, _milliseconds):
        return None


@pytest.mark.asyncio
async def test_lever_apply_ignores_preexisting_jobtomatik_and_linkedin_tabs():
    job_url = (
        "https://jobs.lever.co/eqbank/"
        "7ef2757a-99f9-4000-8bd6-82fc3d2bc844"
    )
    primary = _ControlledPage(
        job_url,
        href="/eqbank/7ef2757a-99f9-4000-8bd6-82fc3d2bc844/apply",
    )
    jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    linkedin = _StaticPage("https://www.linkedin.com/feed/")
    context = _Context([primary, jobtomatik, linkedin])
    for page in context.pages:
        page.context = context

    log = []
    result = await open_application_entry(
        primary,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert result["application_form_detected"] is True
    assert result["application_url"].endswith("/apply")
    assert result["application_url"].startswith("https://jobs.lever.co/eqbank/")
    assert all(item.get("url") != jobtomatik.url for item in log)
    correlation = next(
        item for item in log if item["action"] == "application_entry_context_correlated"
    )
    assert correlation["page_popup_event_correlation"] is True


@pytest.mark.asyncio
async def test_popup_emitted_by_current_apply_remains_eligible():
    primary = _ControlledPage(
        "https://www.linkedin.com/jobs/view/123",
        popup_url="https://jobs.lever.co/eqbank/example/apply",
    )
    old_jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    context = _Context([primary, old_jobtomatik])
    primary.context = context
    old_jobtomatik.context = context

    log = []
    result = await open_application_entry(
        primary,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert result["application_url"] == "https://jobs.lever.co/eqbank/example/apply"
    assert primary.goto_calls == ["https://jobs.lever.co/eqbank/example/apply"]
    assert result["application_form_detected"] is True
    assert any(item["action"] == "external_application_target_observed" for item in log)
    assert all(item.get("url") != old_jobtomatik.url for item in log)
    assert primary._listeners.get("popup") == []


@pytest.mark.asyncio
async def test_unrelated_post_action_tab_without_primary_popup_event_is_ignored():
    primary = _ControlledPage(
        "https://www.linkedin.com/jobs/view/123",
        popup_url="https://mail.example.test/inbox",
        emit_popup=False,
    )
    old_jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    context = _Context([primary, old_jobtomatik])
    primary.context = context
    old_jobtomatik.context = context

    log = []
    result = await open_application_entry(
        primary,
        log,
        max_clicks=1,
        settle_timeout_seconds=0.5,
    )

    assert result == {}
    assert any(page.url == "https://mail.example.test/inbox" for page in context.pages)
    assert all(item.get("url") != "https://mail.example.test/inbox" for item in log)


@pytest.mark.asyncio
async def test_employer_continuation_keeps_shared_context_filtered(monkeypatch):
    primary = _ControlledPage("https://careers.example.org/job/42")
    old_jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    old_mail = _StaticPage("https://mail.example.test/inbox")
    context = _Context([primary, old_jobtomatik, old_mail])
    primary.context = context
    old_jobtomatik.context = context
    old_mail.context = context

    async def fake_continue(page, **_kwargs):
        assert [candidate.url for candidate in page.context.pages] == [primary.url]
        popup = _StaticPage(
            "https://jobs.lever.co/example/job-42/apply",
            opener=primary,
        )
        popup.context = context
        context.pages.append(popup)
        for listener in list(primary._listeners.get("popup", [])):
            listener(popup)
        assert [candidate.url for candidate in page.context.pages] == [
            primary.url,
            popup.url,
        ]
        return {
            "application_url": popup.url,
            "application_form_detected": True,
        }

    monkeypatch.setattr(
        application_entry_runtime,
        "_base_continue_from_employer_landing",
        fake_continue,
    )

    log = []
    result = await continue_from_employer_landing(
        primary,
        source_url="https://www.linkedin.com/jobs/view/42",
        log=log,
        max_steps=1,
        settle_timeout_seconds=0.5,
    )

    assert result["application_form_detected"] is True
    assert result["application_url"].endswith("/apply")
    assert all(item.get("url") != old_jobtomatik.url for item in log)
    assert primary._listeners.get("popup") == []


@pytest.mark.asyncio
async def test_resumed_handoff_accepts_only_controlled_or_opener_correlated_target():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    old_jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    old_mail = _StaticPage("https://mail.example.test/inbox")
    target = _StaticPage(
        "https://jobs.lever.co/eqbank/example/apply",
        opener=primary,
    )
    context = _Context([primary, old_jobtomatik, old_mail, target])
    for page in context.pages:
        page.context = context

    log = []
    observed = await correlated_external_target_from_browser(
        primary,
        source_url,
        log,
    )

    assert observed == target.url
    assert all(item.get("url") not in {old_jobtomatik.url, old_mail.url} for item in log)
    correlation = next(
        item
        for item in log
        if item["action"] == "application_target_existing_context_correlated"
    )
    assert correlation["eligible_opener_tab_count"] == 1
    assert correlation["unrelated_preexisting_tabs_eligible"] is False


@pytest.mark.asyncio
async def test_resumed_handoff_logs_existing_context_receipt_after_opener_tab_settles():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    old_mail = _StaticPage("https://mail.example.test/inbox")
    target = _StaticPage("about:blank", opener=primary)
    context = _Context([primary, old_mail, target])
    for page in context.pages:
        page.context = context

    async def settle_target():
        await asyncio.sleep(0)
        target.url = "https://jobs.lever.co/eqbank/example/apply"

    settle_task = asyncio.create_task(settle_target())
    log = []
    observed = await correlated_external_target_from_browser(
        primary,
        source_url,
        log,
    )
    await settle_task

    assert observed == target.url
    correlation = next(
        item
        for item in log
        if item["action"] == "application_target_existing_context_correlated"
    )
    assert correlation["eligible_opener_tab_count"] == 1
    assert correlation["unrelated_preexisting_tabs_eligible"] is False


@pytest.mark.asyncio
async def test_resumed_handoff_rejects_unrelated_preexisting_offboard_tabs():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    old_jobtomatik = _StaticPage("http://localhost:3000/shadow-campaigns")
    old_mail = _StaticPage("https://mail.example.test/inbox")
    context = _Context([primary, old_jobtomatik, old_mail])
    for page in context.pages:
        page.context = context

    observed = await correlated_external_target_from_browser(
        primary,
        source_url,
        [],
    )

    assert observed is None


def test_all_worker_entry_paths_use_correlated_runtime_entry():
    assert form_filler_handoff.open_application_entry is open_application_entry
    assert application_target_resolver.open_application_entry is open_application_entry
    assert application_target_handoff.open_application_entry is open_application_entry
    assert (
        application_target_handoff.external_target_from_browser
        is correlated_external_target_from_browser
    )
    assert (
        form_filler_handoff.continue_from_employer_landing
        is continue_from_employer_landing
    )
    assert (
        application_target_resolver.continue_from_employer_landing
        is continue_from_employer_landing
    )

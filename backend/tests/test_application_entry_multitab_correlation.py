from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import application_entry_runtime
from app.services.application_entry_runtime import (
    continue_from_employer_landing,
    correlated_application_target_evidence,
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
async def test_resumed_handoff_accepts_only_evidence_qualified_correlated_target():
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
    assert any(
        item.get("action") == "correlated_application_target_proven"
        and item.get("url") == target.url
        for item in log
    )


@pytest.mark.asyncio
async def test_later_auxiliary_opener_tab_cannot_supersede_real_ats_target():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    target = _StaticPage(
        "https://jobs.lever.co/eqbank/example/apply",
        opener=primary,
    )
    auxiliary = _StaticPage(
        "https://accounts.example.test/help",
        opener=primary,
    )
    context = _Context([primary, target, auxiliary])
    for page in context.pages:
        page.context = context

    observed = await correlated_external_target_from_browser(primary, source_url, [])

    assert observed == target.url


@pytest.mark.asyncio
async def test_opener_owned_auxiliary_page_without_application_evidence_is_rejected():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    auxiliary = _StaticPage(
        "https://accounts.example.test/help",
        opener=primary,
    )
    context = _Context([primary, auxiliary])
    for page in context.pages:
        page.context = context

    observed = await correlated_external_target_from_browser(primary, source_url, [])

    assert observed is None


@pytest.mark.parametrize(
    "auxiliary_url",
    [
        "https://jobs.lever.co/privacy",
        "https://boards.greenhouse.io/privacy",
        "https://app.greenhouse.io/users/sign_in?gh_jid=123",
        "https://boards.greenhouse.io/privacy?gh_jid=123",
        "https://jobs.ashbyhq.com/privacy",
        "https://jobs.smartrecruiters.com/privacy",
        "https://example.wd5.myworkdayjobs.com/en-US/CandidateHome",
    ],
)
@pytest.mark.asyncio
async def test_vendor_host_alone_cannot_prove_application_target(auxiliary_url):
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    auxiliary = _StaticPage(auxiliary_url, opener=primary)
    context = _Context([primary, auxiliary])
    for page in context.pages:
        page.context = context

    observed = await correlated_external_target_from_browser(primary, source_url, [])

    assert observed is None


def test_strict_ats_surface_requires_job_or_application_identity():
    strict = application_entry_runtime._strict_ats_surface

    assert strict("https://jobs.lever.co/eqbank/abc-123/apply") == "lever"
    assert strict("https://jobs.lever.co/privacy") is None

    assert strict("https://job-boards.greenhouse.io/acme/jobs/123456") == "greenhouse"
    assert strict("https://boards.greenhouse.io/embed/job_app?token=123456") == "greenhouse"
    assert strict("https://boards.greenhouse.io/privacy") is None
    assert strict("https://app.greenhouse.io/users/sign_in?gh_jid=123") is None
    assert strict("https://boards.greenhouse.io/privacy?gh_jid=123") is None

    assert (
        strict("https://jobs.ashbyhq.com/acme/123e4567-e89b-12d3-a456-426614174000/application")
        == "ashby"
    )
    assert strict("https://jobs.ashbyhq.com/privacy") is None

    assert (
        strict("https://jobs.smartrecruiters.com/acme/12345-senior-analyst")
        == "smartrecruiters"
    )
    assert strict("https://jobs.smartrecruiters.com/privacy") is None

    assert (
        strict("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Toronto/JR12345/apply")
        == "workday"
    )
    assert strict("https://acme.wd5.myworkdayjobs.com/en-US/CandidateHome") is None


@pytest.mark.asyncio
async def test_loading_correlated_popup_is_preserved_instead_of_rebaselined():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    pending = _StaticPage("about:blank", opener=primary)
    context = _Context([primary, pending])
    for page in context.pages:
        page.context = context

    result = await correlated_application_target_evidence(
        primary,
        source_url,
        [],
        settle_timeout_seconds=0,
    )

    assert result["status"] == "pending"
    assert result["application_url"] is None


@pytest.mark.asyncio
async def test_correlated_http_intermediate_remains_eligible_until_ats_redirect():
    source_url = "https://www.linkedin.com/jobs/view/123"
    primary = _ControlledPage(source_url)
    target = _StaticPage(
        "https://accounts.example.test/login",
        opener=primary,
    )
    context = _Context([primary, target])
    for page in context.pages:
        page.context = context

    async def redirect_target():
        await asyncio.sleep(0.05)
        target.url = "https://jobs.lever.co/eqbank/example/apply"

    redirect_task = asyncio.create_task(redirect_target())
    result = await correlated_application_target_evidence(
        primary,
        source_url,
        [],
        settle_timeout_seconds=0.3,
    )
    await redirect_task

    assert result["status"] == "resolved"
    assert result["application_url"] == target.url


@pytest.mark.asyncio
async def test_retained_navigation_accepts_inline_form_on_controlled_source(monkeypatch):
    source_url = "https://www.linkedin.com/jobs/view/123"
    page = SimpleNamespace(url=source_url)

    class _Evidence:
        present = True

        def as_dict(self):
            return {"present": True, "applicantControls": 4}

    async def fake_form_evidence(_page):
        return _Evidence()

    async def should_not_run(*_args, **_kwargs):
        raise AssertionError("correlated resolver should not run for direct form proof")

    monkeypatch.setattr(
        application_target_handoff,
        "application_form_evidence",
        fake_form_evidence,
    )
    monkeypatch.setattr(
        application_target_handoff,
        "_target_evidence_from_browser",
        should_not_run,
    )

    result = await application_target_handoff._observed_target_evidence(
        page,
        source_url,
        [],
    )

    assert result["status"] == "resolved"
    assert result["application_url"] == source_url
    assert result["application_form_detected"] is True


@pytest.mark.asyncio
async def test_retained_navigation_rejects_auxiliary_form_as_direct_proof(monkeypatch):
    source_url = "https://www.linkedin.com/jobs/view/123"
    page = SimpleNamespace(url="https://accounts.example.test/login")

    class _Evidence:
        present = True

        def as_dict(self):
            return {"present": True, "emailControls": 1, "submitControls": 1}

    async def fake_form_evidence(_page):
        return _Evidence()

    async def no_correlated_target(_page, _source_url, _log):
        return {
            "status": "none",
            "application_url": None,
            "application_form_detected": False,
            "form_evidence": {},
            "trusted_ats_adapter": None,
            "trusted_ats_adapter_version": None,
        }

    monkeypatch.setattr(
        application_target_handoff,
        "application_form_evidence",
        fake_form_evidence,
    )
    monkeypatch.setattr(
        application_target_handoff,
        "_target_evidence_from_browser",
        no_correlated_target,
    )

    result = await application_target_handoff._observed_target_evidence(
        page,
        source_url,
        [],
    )

    assert result["status"] == "none"
    assert result["application_url"] is None
    assert result["application_form_detected"] is False


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


@pytest.mark.asyncio
async def test_retained_target_page_uses_durable_cdp_identity_after_navigation(monkeypatch):
    controlled = _StaticPage("https://jobs.lever.co/eqbank/example/apply")
    unrelated = _StaticPage("https://mail.example.test/inbox")
    context = _Context([controlled, unrelated])
    controlled.context = context
    unrelated.context = context
    session = SimpleNamespace(
        challenge_type="captcha",
        current_url="https://accounts.example.test/login",
        handoff_metadata={
            "stage": "application_target_security_boundary",
            "target_resolution_only": True,
            "controlled_page_target_id": "target-controlled",
        },
    )

    async def fake_target_id(_context, page):
        return "target-controlled" if page is controlled else "target-unrelated"

    monkeypatch.setattr(application_target_handoff, "_page_target_id", fake_target_id)

    selected = await application_target_handoff._retained_target_page(
        context,
        session,
        unrelated,
    )

    assert selected is controlled


@pytest.mark.asyncio
async def test_legacy_target_handoff_never_falls_back_to_last_unrelated_tab():
    controlled = _StaticPage("https://jobs.lever.co/eqbank/example/apply")
    unrelated = _StaticPage("https://mail.example.test/inbox")
    context = _Context([controlled, unrelated])
    session = SimpleNamespace(
        challenge_type="captcha",
        current_url="https://accounts.example.test/login",
        handoff_metadata={
            "stage": "application_target_security_boundary",
            "target_resolution_only": True,
        },
    )

    selected = await application_target_handoff._retained_target_page(
        context,
        session,
        unrelated,
    )

    assert selected is None


def test_all_worker_entry_paths_use_correlated_runtime_entry():
    assert form_filler_handoff.open_application_entry is open_application_entry
    assert application_target_resolver.open_application_entry is open_application_entry
    assert application_target_handoff.open_application_entry is open_application_entry
    assert (
        application_target_handoff.external_target_from_browser
        is correlated_external_target_from_browser
    )
    assert (
        application_target_handoff._target_evidence_from_browser
        is correlated_application_target_evidence
    )
    assert (
        form_filler_handoff.continue_from_employer_landing
        is continue_from_employer_landing
    )
    assert (
        application_target_resolver.continue_from_employer_landing
        is continue_from_employer_landing
    )

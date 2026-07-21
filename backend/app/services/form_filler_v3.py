"""ATS-aware, policy-gated application form runner."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import (
    is_allowed_url,
    is_fake_url,
    navigate_job_board_listing,
    now_iso,
)
from app.services.control_engine import (
    CONTROL_ENGINE_VERSION,
    element_descriptor,
    fill_policy_controls,
    normalize_text,
)
from app.services.control_policy import resolve_control_policy
from app.services.form_filler_v2 import (
    SAFE_PROFILE_FIELDS,
    _SEARCH_FIELDS,
    _address_parts,
    _append_review,
    _first_name,
    _last_name,
    _profile_values,
    _required,
    _safe_field,
)
from app.services.supervised_target_identity import verify_supervised_browser_target
from app.services.upload_handler import fill_upload_fields


async def _is_combobox_internal(element: Any) -> bool:
    try:
        return bool(await element.evaluate(
            """(el) => Boolean(
              el.matches('[role="combobox"],[aria-autocomplete]')
              || el.closest('[role="combobox"]')
            )"""
        ))
    except Exception:
        return False


async def _anonymous_text_context(element: Any) -> Dict[str, Any]:
    try:
        return await element.evaluate(
            """(el) => {
              const root = el.closest(
                '[data-field],.field-wrapper,.application-field,' +
                '[class*="field-wrapper"],[class*="application-field"],fieldset'
              ) || el.parentElement;
              const text = (root?.innerText || '').replace(/\s+/g, ' ').trim();
              return {
                tag: el.tagName.toLowerCase(),
                id: el.id || '',
                name: el.getAttribute('name') || '',
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || '',
                ariaAutocomplete: el.getAttribute('aria-autocomplete') || '',
                placeholder: el.getAttribute('placeholder') || '',
                rootText: text.slice(0, 300),
                rootTextLength: text.length,
                hasFileInput: Boolean(root?.querySelector('input[type="file"]')),
                hasCombobox: Boolean(root?.querySelector('[role="combobox"],[aria-autocomplete]')),
                textInputCount: root?.querySelectorAll(
                  'input:not([type="hidden"]):not([type="file"]),textarea'
                ).length || 0
              };
            }"""
        )
    except Exception:
        return {}


async def _fill_text_fields(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    policies: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
    values = _profile_values(profile, cover_letter)
    filled = 0
    selector = (
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
        ':not([type="reset"]):not([type="checkbox"]):not([type="radio"])'
        ':not([type="file"]):not([list]):not([role="combobox"])'
        ':not([aria-autocomplete]),textarea'
    )
    for element in await surface.query_selector_all(selector):
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
            if await element.get_attribute("readonly") is not None:
                continue
            if await _is_combobox_internal(element):
                continue
            descriptor = await element_descriptor(surface, element)
            context: Dict[str, Any] = {}
            if not normalize_text(descriptor):
                context = await _anonymous_text_context(element)
                if context.get("hasFileInput") or context.get("hasCombobox"):
                    log.append({
                        "action": "subordinate_text_control_skipped",
                        "control": context,
                        "ts": now_iso(),
                    })
                    continue
                root_text = str(context.get("rootText") or "").strip()
                if root_text and int(context.get("rootTextLength") or 0) <= 300:
                    descriptor = root_text

            if normalize_text(await element.get_attribute("name")) in _SEARCH_FIELDS:
                continue

            current = str(await element.input_value())
            policy = resolve_control_policy(descriptor, policies)
            if policy.get("matched"):
                if policy.get("can_autofill"):
                    answer = str(policy.get("answer") or "")
                    if current == answer:
                        continue
                    await element.fill(answer)
                    if str(await element.input_value()) == answer:
                        filled += 1
                        log.append({
                            "action": "fill",
                            "descriptor": descriptor[:200],
                            "canonical_key": policy.get("canonical_key"),
                            "source": "answer_policy",
                            "verified": True,
                            "ts": now_iso(),
                        })
                    else:
                        _append_review(
                            review_items,
                            descriptor=descriptor,
                            policy=policy,
                            control_type="text",
                            reason_code="unsupported_control",
                            summary=f"Policy answer could not be verified: {descriptor}",
                        )
                elif await _required(element):
                    before = len(review_items)
                    _append_review(
                        review_items,
                        descriptor=descriptor,
                        policy=policy,
                        control_type="text",
                    )
                    if context and len(review_items) > before:
                        review_items[-1].setdefault("details", {})["control_metadata"] = context
                continue

            field = _safe_field(descriptor)
            if field:
                value = str(values.get(field, "") or "")
                if value:
                    if current == value:
                        continue
                    await element.fill(value)
                    if str(await element.input_value()) == value:
                        filled += 1
                        log.append({
                            "action": "fill",
                            "field": field,
                            "descriptor": descriptor[:200],
                            "source": "profile",
                            "verified": True,
                            "ts": now_iso(),
                        })
                    else:
                        _append_review(
                            review_items,
                            descriptor=descriptor,
                            policy={"canonical_key": f"profile.{field}", "category": "profile"},
                            control_type="text",
                            reason_code="unsupported_control",
                            summary=f"Profile field could not be verified: {descriptor}",
                        )
                elif await _required(element):
                    before = len(review_items)
                    _append_review(
                        review_items,
                        descriptor=descriptor,
                        policy={"canonical_key": f"profile.{field}", "category": "profile"},
                        control_type="text",
                        reason_code="ambiguous_question",
                        summary=f"Required profile value is missing: {descriptor or field}",
                    )
                    if context and len(review_items) > before:
                        review_items[-1].setdefault("details", {})["control_metadata"] = context
                continue

            if await _required(element):
                before = len(review_items)
                _append_review(
                    review_items,
                    descriptor=descriptor,
                    policy=policy,
                    control_type="text",
                )
                if context and len(review_items) > before:
                    review_items[-1].setdefault("details", {})["control_metadata"] = context
        except Exception as exc:
            log.append({
                "action": "fill_skipped",
                "detail": str(exc)[:200],
                "ts": now_iso(),
            })
    return filled


def _merge_review_items(
    target: List[Dict[str, Any]],
    source: List[Dict[str, Any]],
) -> None:
    for item in source:
        signature = (
            item.get("reason_code"),
            item.get("details", {}).get("descriptor"),
            item.get("details", {}).get("control_type"),
        )
        if not any(signature == (
            existing.get("reason_code"),
            existing.get("details", {}).get("descriptor"),
            existing.get("details", {}).get("control_type"),
        ) for existing in target):
            target.append(item)


async def _fill_step_fields(
    surface: Any,
    *,
    profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    log: List[Dict[str, Any]],
    step_number: int,
) -> Dict[str, Any]:
    policies = list(profile.get("answer_policies") or [])
    review_items: List[Dict[str, Any]] = []
    filled = 0

    filled += await _fill_text_fields(
        surface,
        profile=profile,
        cover_letter=cover_letter,
        policies=policies,
        log=log,
        review_items=review_items,
    )

    control_outcome = await fill_policy_controls(surface, policies, log)
    filled += control_outcome.filled_count
    _merge_review_items(review_items, control_outcome.review_items)

    filled += await _fill_text_fields(
        surface,
        profile=profile,
        cover_letter=cover_letter,
        policies=policies,
        log=log,
        review_items=review_items,
    )

    upload_outcome = await fill_upload_fields(
        surface,
        resume_path=resume_path,
        cover_letter_path=str(profile.get("cover_letter_path") or ""),
        portfolio_path=str(profile.get("portfolio_path") or ""),
        log=log,
    )
    filled += upload_outcome.filled_count
    _merge_review_items(review_items, upload_outcome.review_items)

    return {
        "filled_count": filled,
        "review_items": review_items,
        "control_evidence": control_outcome.evidence,
        "control_passes": control_outcome.passes,
        "upload_evidence": upload_outcome.evidence,
        "step": step_number,
    }


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
    supervised_target: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "success": False,
        "dry_run": dry_run,
        "url": job_url,
        "log": log,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "control_evidence": [],
        "upload_evidence": [],
        "step_evidence": [],
        "validation_errors": [],
        "confirmation_evidence": [],
        "ready_to_submit": False,
        "ats_adapter": "generic",
        "ats_adapter_version": "1.0.0",
    }
    if not is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        result["requires_manual_review"] = True
        return result
    if is_fake_url(job_url):
        result["error"] = "Placeholder URL; manual application required"
        result["requires_manual_review"] = True
        return result

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            log.append({"action": "navigate", "url": job_url, "ts": now_iso()})
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    log.append({"action": "network_idle_timeout", "ts": now_iso()})
            except PlaywrightTimeoutError:
                log.append({"action": "navigation_timeout", "ts": now_iso()})

            handoff = await navigate_job_board_listing(page, log)
            result.update({
                key: handoff[key]
                for key in ("application_url", "contact_email")
                if handoff.get(key)
            })
            if handoff.get("manual_review_only"):
                result["requires_manual_review"] = True
                result["success"] = bool(dry_run)
                result["error"] = handoff.get("reason")
                await browser.close()
                return result

            adapter = await detect_ats_adapter(page, page.url)
            result["ats_adapter"] = adapter.name
            result["ats_adapter_version"] = adapter.version
            log.append({
                "action": "ats_adapter_detected",
                "adapter": adapter.name,
                "version": adapter.version,
                "ts": now_iso(),
            })

            async def fill_step(surface: Any, step_number: int) -> Dict[str, Any]:
                return await _fill_step_fields(
                    surface,
                    profile=user_profile,
                    cover_letter=cover_letter,
                    resume_path=resume_path,
                    log=log,
                    step_number=step_number,
                )

            async def pre_submit_check(current_page: Any, _current_adapter: Any) -> Dict[str, Any]:
                detected = await detect_ats_adapter(current_page, current_page.url)
                return await verify_supervised_browser_target(
                    current_url=current_page.url,
                    adapter_name=detected.name,
                    adapter_version=detected.version,
                    expected_metadata=supervised_target,
                    refresh_official_metadata=True,
                )

            flow = await run_ats_application_flow(
                page,
                adapter,
                fill_step=fill_step,
                dry_run=dry_run,
                log=log,
                pre_submit_check=(
                    pre_submit_check
                    if supervised_target and not dry_run
                    else None
                ),
            )
            result.update(flow.as_dict())
            result["ats_adapter"] = flow.adapter_name
            result["ats_adapter_version"] = flow.adapter_version
            if flow.success and not dry_run:
                result["submitted_at"] = now_iso()
            await browser.close()
    except ImportError:
        result["error"] = "Playwright not installed"
        result["requires_manual_review"] = True
    except Exception as exc:
        result["error"] = str(exc)
        result["requires_manual_review"] = True
        log.append({"action": "error", "detail": str(exc)[:300], "ts": now_iso()})
    return result


_navigate_job_board_listing = navigate_job_board_listing

__all__ = [
    "SAFE_PROFILE_FIELDS",
    "_address_parts",
    "_first_name",
    "_last_name",
    "_navigate_job_board_listing",
    "fill_and_submit_application",
]

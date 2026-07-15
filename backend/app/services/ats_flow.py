"""Reusable bounded multi-step application flow runner."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List

from app.services.ats_base import ATSAdapter, ATSFlowResult
from app.services.browser_navigation import detect_blocking_challenge

FillStep = Callable[[Any, int], Awaitable[Dict[str, Any]]]

MAX_ATS_STEPS = 12
STEP_SETTLE_MS = 350
STEP_ADVANCE_TIMEOUT_SECONDS = 8.0


def _now() -> str:
    return datetime.utcnow().isoformat()


def _review(reason_code: str, summary: str, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reason_code": reason_code,
        "summary": summary,
        "details": details,
    }


def _merge_unique(target: List[Dict[str, Any]], source: List[Dict[str, Any]]) -> None:
    for item in source:
        signature = (
            item.get("reason_code") or item.get("action"),
            item.get("details", {}).get("descriptor") or item.get("control_id"),
            item.get("details", {}).get("control_type") or item.get("upload_type"),
            item.get("filename"),
        )
        exists = any(signature == (
            existing.get("reason_code") or existing.get("action"),
            existing.get("details", {}).get("descriptor") or existing.get("control_id"),
            existing.get("details", {}).get("control_type") or existing.get("upload_type"),
            existing.get("filename"),
        ) for existing in target)
        if not exists:
            target.append(item)


async def _wait_for_step_change(
    adapter: ATSAdapter,
    page: Any,
    before_fingerprint: str,
) -> tuple[Any, str]:
    deadline = asyncio.get_running_loop().time() + STEP_ADVANCE_TIMEOUT_SECONDS
    last_surface = await adapter.resolve_surface(page)
    last_fingerprint = await adapter.step_fingerprint(last_surface)
    while asyncio.get_running_loop().time() < deadline:
        if last_fingerprint != before_fingerprint:
            return last_surface, last_fingerprint
        await page.wait_for_timeout(STEP_SETTLE_MS)
        last_surface = await adapter.resolve_surface(page)
        last_fingerprint = await adapter.step_fingerprint(last_surface)
    return last_surface, last_fingerprint


async def run_ats_application_flow(
    page: Any,
    adapter: ATSAdapter,
    *,
    fill_step: FillStep,
    dry_run: bool,
    log: List[Dict[str, Any]],
    max_steps: int = MAX_ATS_STEPS,
) -> ATSFlowResult:
    """Fill and traverse a bounded ATS flow, never bypassing manual boundaries."""
    result = ATSFlowResult(
        adapter_name=adapter.name,
        adapter_version=adapter.version,
    )
    seen: set[str] = set()

    surface = await adapter.resolve_surface(page)
    await adapter.prepare(surface, log)
    surface = await adapter.resolve_surface(page)

    for step_number in range(1, max_steps + 1):
        challenge = await detect_blocking_challenge(page)
        if challenge:
            result.requires_manual_review = True
            result.error = challenge["summary"]
            result.review_items.append(challenge)
            return result

        fingerprint = await adapter.step_fingerprint(surface)
        if fingerprint in seen:
            result.requires_manual_review = True
            result.error = "The ATS flow repeated a previously visited step."
            result.review_items.append(_review(
                "step_navigation_failed",
                result.error,
                {
                    "adapter": adapter.name,
                    "step": step_number,
                    "fingerprint": fingerprint,
                },
            ))
            return result
        seen.add(fingerprint)

        step_outcome = await fill_step(surface, step_number)
        result.fields_filled += int(step_outcome.get("filled_count", 0))
        _merge_unique(result.review_items, step_outcome.get("review_items") or [])
        _merge_unique(result.control_evidence, step_outcome.get("control_evidence") or [])
        _merge_unique(result.upload_evidence, step_outcome.get("upload_evidence") or [])
        result.steps_completed = step_number
        result.step_evidence.append({
            "action": "ats_step_filled",
            "adapter": adapter.name,
            "adapter_version": adapter.version,
            "step": step_number,
            "fingerprint": fingerprint,
            "fields_filled": int(step_outcome.get("filled_count", 0)),
            "control_passes": step_outcome.get("control_passes", 0),
            "ts": _now(),
        })

        if result.review_items:
            result.requires_manual_review = True
            result.error = "Required application fields need review before the ATS flow can continue."
            return result

        submit = await adapter.find_submit_button(surface)
        next_button = await adapter.find_next_button(surface)

        if next_button:
            before_url = getattr(surface, "url", "") or getattr(page, "url", "")
            before = fingerprint
            try:
                await next_button.click()
                log.append({
                    "action": "ats_next_clicked",
                    "adapter": adapter.name,
                    "step": step_number,
                    "ts": _now(),
                })
            except Exception as exc:
                result.requires_manual_review = True
                result.error = f"Could not advance the ATS step: {str(exc)[:180]}"
                result.review_items.append(_review(
                    "step_navigation_failed",
                    result.error,
                    {"adapter": adapter.name, "step": step_number},
                ))
                return result

            await page.wait_for_timeout(STEP_SETTLE_MS)
            validation = await adapter.extract_validation_errors(surface)
            if validation:
                result.validation_errors.extend(item.as_dict() for item in validation)
                result.requires_manual_review = True
                result.error = "The ATS rejected one or more values on the current step."
                result.review_items.append(_review(
                    "validation_error",
                    result.error,
                    {
                        "adapter": adapter.name,
                        "step": step_number,
                        "url": before_url,
                        "errors": [item.as_dict() for item in validation],
                    },
                ))
                return result

            surface, after = await _wait_for_step_change(adapter, page, before)
            if after == before:
                result.requires_manual_review = True
                result.error = "The ATS did not advance after the next-step action."
                result.review_items.append(_review(
                    "step_navigation_failed",
                    result.error,
                    {
                        "adapter": adapter.name,
                        "step": step_number,
                        "fingerprint": before,
                    },
                ))
                return result
            result.step_evidence.append({
                "action": "ats_step_advanced",
                "adapter": adapter.name,
                "from_step": step_number,
                "from_fingerprint": before,
                "to_fingerprint": after,
                "ts": _now(),
            })
            continue

        if submit:
            result.final_url = getattr(surface, "url", "") or getattr(page, "url", "")
            if dry_run:
                result.success = True
                result.ready_to_submit = True
                result.step_evidence.append({
                    "action": "ats_final_submit_ready",
                    "adapter": adapter.name,
                    "step": step_number,
                    "submit_clicked": False,
                    "ts": _now(),
                })
                return result

            before_url = result.final_url
            before_fingerprint = fingerprint
            try:
                await submit.click()
                log.append({
                    "action": "ats_submit_clicked",
                    "adapter": adapter.name,
                    "step": step_number,
                    "ts": _now(),
                })
            except Exception as exc:
                result.requires_manual_review = True
                result.error = f"Final submit action failed: {str(exc)[:180]}"
                result.review_items.append(_review(
                    "submission_confirmation_uncertain",
                    result.error,
                    {"adapter": adapter.name, "step": step_number},
                ))
                return result

            await page.wait_for_timeout(1000)
            surface = await adapter.resolve_surface(page)
            validation = await adapter.extract_validation_errors(surface)
            if validation:
                result.validation_errors.extend(item.as_dict() for item in validation)
                result.requires_manual_review = True
                result.error = "The ATS rejected the final application submission."
                result.review_items.append(_review(
                    "validation_error",
                    result.error,
                    {
                        "adapter": adapter.name,
                        "step": step_number,
                        "errors": [item.as_dict() for item in validation],
                    },
                ))
                return result

            confirmation = await adapter.detect_confirmation(
                surface,
                before_url=before_url,
                before_fingerprint=before_fingerprint,
            )
            result.confirmation_evidence = [item.as_dict() for item in confirmation]
            sufficient = any(item.is_sufficient for item in confirmation)
            result.final_url = getattr(surface, "url", "") or getattr(page, "url", "")
            if sufficient:
                result.success = True
                return result

            result.requires_manual_review = True
            result.error = (
                "The ATS submit action occurred, but explicit confirmation evidence "
                "was not detected."
            )
            result.review_items.append(_review(
                "submission_confirmation_uncertain",
                result.error,
                {
                    "adapter": adapter.name,
                    "step": step_number,
                    "final_url": result.final_url,
                },
            ))
            return result

        result.requires_manual_review = True
        result.error = "No next-step or final-submit control was found."
        result.review_items.append(_review(
            "unsupported_control",
            result.error,
            {
                "adapter": adapter.name,
                "step": step_number,
                "fingerprint": fingerprint,
            },
        ))
        return result

    result.requires_manual_review = True
    result.error = f"The ATS flow exceeded the maximum of {max_steps} steps."
    result.review_items.append(_review(
        "step_navigation_failed",
        result.error,
        {"adapter": adapter.name, "max_steps": max_steps},
    ))
    return result

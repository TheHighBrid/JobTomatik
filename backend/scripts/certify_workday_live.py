"""Supervised Workday Candidate Experience dry-run certification.

This script never clicks a final submit control, never enters credentials, and never
creates a candidate account. It verifies public CXS metadata, inspects the current UI
boundary, and optionally exercises the safe form path with a fictional profile.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.ats_registry import detect_ats_adapter
from app.services.ats_workday import (
    fetch_workday_job_metadata,
    inspect_workday_job_metadata,
    parse_workday_target,
)
from app.services.browser_navigation import detect_blocking_challenge
from app.services.form_filler import fill_and_submit_application
from app.services.workday_certification import (
    SYNTHETIC_TEXT_RESPONSE,
    build_synthetic_profile_for_page,
    inspect_workday_application_dom,
    write_synthetic_resume,
)


MANUAL_REASONS = {
    "captcha_detected",
    "mfa_required",
    "login_required",
    "account_creation_required",
    "anti_bot_challenge",
    "assessment_required",
}


def parse_urls(raw: str) -> List[str]:
    values = [item.strip() for item in re.split(r"[\n,]+", raw or "") if item.strip()]
    return list(dict.fromkeys(values))


async def _load_surface(url: str, browser) -> Tuple[Any, Any, Any, List[Dict[str, Any]]]:
    page = await browser.new_page()
    log: List[Dict[str, Any]] = []
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=50000)
        except Exception as exc:
            log.append({"action": "navigation_warning", "detail": str(exc)[:500]})
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        adapter = await detect_ats_adapter(page, page.url or url)
        surface = await adapter.resolve_surface(page)
        await adapter.prepare(surface, log)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        surface = await adapter.resolve_surface(page)
        return page, adapter, surface, log
    except Exception:
        await page.close()
        raise


async def _metadata(url: str) -> Dict[str, Any]:
    target = parse_workday_target(url)
    if target is None:
        return {
            "public_metadata_certified": False,
            "error": "The URL did not contain strict Workday tenant, site, and requisition evidence.",
        }
    try:
        payload = await fetch_workday_job_metadata(target)
        return inspect_workday_job_metadata(payload, target)
    except Exception as exc:
        return {
            "target": target.as_dict(),
            "public_metadata_certified": False,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }


async def inspect_live_url(url: str, browser) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "url": url,
        "mode": "inspect",
        "passed": False,
        "final_submit_clicked": False,
    }
    page = None
    try:
        report["public_metadata"] = await _metadata(url)
        page, adapter, surface, log = await _load_surface(url, browser)
        report["loaded_url"] = page.url
        report["title"] = await page.title()
        report["adapter"] = adapter.name
        report["adapter_version"] = adapter.version
        report["navigation_log"] = log
        if adapter.name != "workday":
            report["error"] = "The supplied URL was not detected as a Workday target."
            return report

        report["surface_url"] = getattr(surface, "url", "") or page.url
        report["dom"] = await inspect_workday_application_dom(surface)
        report["next_control_present"] = bool(await adapter.find_next_button(surface))
        report["submit_control_present"] = bool(await adapter.find_submit_button(surface))
        challenge = await detect_blocking_challenge(page)
        report["challenge"] = challenge

        rendered = bool(
            report["dom"].get("visible_control_count", 0) > 0
            and (report["next_control_present"] or report["submit_control_present"])
        )
        manual_boundary = bool(
            challenge and challenge.get("reason_code") in MANUAL_REASONS
        )
        report["rendered_application_surface"] = rendered
        report["manual_boundary"] = manual_boundary
        report["certified_boundary"] = (
            "rendered_application_surface"
            if rendered and not manual_boundary
            else str((challenge or {}).get("reason_code") or "unresolved")
        )
        report["passed"] = bool(
            report["public_metadata"].get("public_metadata_certified")
            and (rendered or manual_boundary)
            and report["final_submit_clicked"] is False
        )
        if not report["passed"]:
            report["error"] = report.get("error") or (
                "Workday metadata or current UI boundary was not certification-ready."
            )
        return report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        report["traceback"] = traceback.format_exc(limit=8)[-4000:]
        return report
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass


def _manual_result_boundary(result: Dict[str, Any], submit_clicked: bool) -> Optional[str]:
    for item in result.get("review_items") or []:
        reason = item.get("reason_code")
        if reason not in MANUAL_REASONS:
            continue
        details = item.get("details") or {}
        fields = int(result.get("fields_filled") or 0)
        verified_upload = any(
            evidence.get("verification") == "passed"
            for evidence in result.get("upload_evidence") or []
        )
        if fields > 0 and verified_upload and not submit_clicked:
            return "post_fill_manual_challenge_handoff"
        if fields == 0 and not submit_clicked:
            return "pre_form_manual_handoff"
        if details.get("handoff_stage") == "post_fill_pre_action" and not submit_clicked:
            return "post_fill_manual_challenge_handoff"
    return None


async def _profile_for_url(url: str, browser) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    page = None
    try:
        page, adapter, surface, log = await _load_surface(url, browser)
        if adapter.name != "workday":
            raise RuntimeError("The URL was not detected as Workday.")
        challenge = await detect_blocking_challenge(page)
        if challenge:
            return {
                "full_name": "Avery Certification",
                "first_name": "Avery",
                "last_name": "Certification",
                "email": "avery.certification@example.test",
                "phone": "+1 613 555 0199",
                "answer_policies": [],
                "synthetic_certification_only": True,
                "synthetic_platform": "workday",
            }, {
                "synthetic_profile": True,
                "profile_policy_generation": "not_reached_due_to_manual_boundary",
                "challenge": challenge,
                "navigation_log": log,
            }
        profile, metadata = await build_synthetic_profile_for_page(surface)
        metadata.update({
            "synthetic_profile": True,
            "profile_policy_generation": "hosted_dom",
            "navigation_log": log,
        })
        return profile, metadata
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass


async def exercise_live_url(
    url: str,
    *,
    profile: Dict[str, Any],
    resume_path: str,
    cover_letter: str,
    certification_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = await _metadata(url)
    try:
        result = await fill_and_submit_application(
            job_url=url,
            user_profile=profile,
            cover_letter=cover_letter,
            resume_path=resume_path,
            dry_run=True,
        )
    except Exception as exc:
        return {
            "url": url,
            "mode": "exercise",
            "passed": False,
            "public_metadata": metadata,
            "final_submit_clicked": False,
            "certification_metadata": certification_metadata or {},
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }

    submit_clicked = any(
        item.get("action") in {"ats_submit_clicked", "submit_click", "submit_clicked"}
        for item in result.get("log") or []
    )
    ready = bool(
        result.get("success")
        and result.get("ready_to_submit")
        and result.get("ats_adapter") == "workday"
        and not submit_clicked
    )
    manual_boundary = _manual_result_boundary(result, submit_clicked)
    passed = bool(
        metadata.get("public_metadata_certified")
        and result.get("ats_adapter") == "workday"
        and (ready or manual_boundary)
        and not submit_clicked
    )
    outcome = "ready_to_submit" if ready else manual_boundary or "failed"
    return {
        "url": url,
        "mode": "exercise",
        "passed": passed,
        "certification_outcome": outcome,
        "adapter": result.get("ats_adapter"),
        "adapter_version": result.get("ats_adapter_version"),
        "public_metadata": metadata,
        "ready_to_submit": result.get("ready_to_submit"),
        "requires_manual_review": result.get("requires_manual_review"),
        "steps_completed": result.get("steps_completed"),
        "fields_filled": result.get("fields_filled"),
        "review_items": result.get("review_items") or [],
        "validation_errors": result.get("validation_errors") or [],
        "upload_evidence": result.get("upload_evidence") or [],
        "step_evidence": result.get("step_evidence") or [],
        "control_evidence_count": len(result.get("control_evidence") or []),
        "final_submit_clicked": submit_clicked,
        "certification_metadata": certification_metadata or {},
        "error": result.get("error"),
    }


async def main_async(args) -> int:
    urls = parse_urls(args.urls or os.getenv("WORKDAY_CERT_URLS", ""))
    if not urls:
        raise RuntimeError("At least one Workday URL is required.")

    from playwright.async_api import async_playwright

    reports: List[Dict[str, Any]] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            for url in urls:
                reports.append(await inspect_live_url(url, browser))

            if args.exercise:
                resume_path = args.synthetic_resume_path or os.getenv(
                    "WORKDAY_CERT_RESUME_PATH", "workday-synthetic-resume.pdf"
                )
                write_synthetic_resume(resume_path)
                cover_letter = os.getenv(
                    "WORKDAY_CERT_COVER_LETTER", SYNTHETIC_TEXT_RESPONSE
                )
                for url in urls:
                    try:
                        profile, metadata = await _profile_for_url(url, browser)
                        reports.append(await exercise_live_url(
                            url,
                            profile=profile,
                            resume_path=resume_path,
                            cover_letter=cover_letter,
                            certification_metadata=metadata,
                        ))
                    except Exception as exc:
                        reports.append({
                            "url": url,
                            "mode": "exercise",
                            "passed": False,
                            "final_submit_clicked": False,
                            "certification_metadata": {"synthetic_profile": True},
                            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                            "traceback": traceback.format_exc(limit=8)[-4000:],
                        })
        finally:
            await browser.close()

    summary = {
        "certification": "workday_supervised_live_dry_run",
        "final_submit_clicked": any(
            item.get("final_submit_clicked", False) for item in reports
        ),
        "url_count": len(urls),
        "exercise_enabled": bool(args.exercise),
        "reports": reports,
        "passed": bool(reports) and all(item.get("passed") for item in reports),
    }
    Path(args.report).write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0 if summary["passed"] and not summary["final_submit_clicked"] else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", default="")
    parser.add_argument("--exercise", action="store_true")
    parser.add_argument(
        "--synthetic-resume-path",
        default="workday-synthetic-resume.pdf",
    )
    parser.add_argument("--report", default="workday-live-certification.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

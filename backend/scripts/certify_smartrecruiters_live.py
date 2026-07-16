"""Supervised SmartRecruiters live dry-run certification.

This script never clicks a final submit control. Public CI combines the official
public Posting API with hosted-form DOM inspection. When a SmartRecruiters token
is explicitly configured, it also validates screening questions, conditionals,
and privacy policies through the official application configuration endpoint.
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
from app.services.ats_smartrecruiters import (
    fetch_smartrecruiters_configuration,
    fetch_smartrecruiters_posting,
    inspect_smartrecruiters_configuration,
    inspect_smartrecruiters_posting,
    parse_smartrecruiters_job_url,
)
from app.services.form_filler import fill_and_submit_application
from app.services.smartrecruiters_certification import (
    SYNTHETIC_TEXT_RESPONSE,
    build_synthetic_profile_for_page,
    inspect_smartrecruiters_application_dom,
    write_synthetic_resume,
)


def parse_urls(raw: str) -> List[str]:
    values = [item.strip() for item in re.split(r"[\n,]+", raw or "") if item.strip()]
    return list(dict.fromkeys(values))


async def _load_application_surface(
    url: str,
    browser: Any,
) -> Tuple[Any, Any, Any, List[Dict[str, Any]]]:
    page = await browser.new_page()
    log: List[Dict[str, Any]] = []
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
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


async def _public_posting_for_url(
    url: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    company, posting_id, surface_kind = parse_smartrecruiters_job_url(url)
    metadata: Dict[str, Any] = {
        "company_identifier": company,
        "posting_identifier": posting_id,
        "surface_kind": surface_kind,
    }
    if not company or not posting_id:
        return None, metadata
    posting = await fetch_smartrecruiters_posting(company, posting_id)
    metadata["posting_id"] = posting.get("id")
    metadata["posting_uuid"] = posting.get("uuid")
    return posting, metadata


async def inspect_live_url(url: str, browser: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "url": url,
        "mode": "inspect",
        "passed": False,
        "final_submit_clicked": False,
    }
    page = None
    try:
        page, adapter, surface, log = await _load_application_surface(url, browser)
        report["loaded_url"] = page.url
        report["title"] = await page.title()
        report["adapter"] = adapter.name
        report["adapter_version"] = adapter.version
        report["navigation_log"] = log
        if adapter.name != "smartrecruiters":
            report["error"] = (
                "The supplied URL was not detected as a SmartRecruiters application."
            )
            return report

        report["surface_url"] = getattr(surface, "url", "") or page.url
        report["dom"] = await inspect_smartrecruiters_application_dom(surface)
        report["next_control_present"] = bool(await adapter.find_next_button(surface))
        report["submit_control_present"] = bool(await adapter.find_submit_button(surface))

        posting, parse_metadata = await _public_posting_for_url(
            report["surface_url"] or url
        )
        if posting is None:
            posting, parse_metadata = await _public_posting_for_url(url)
        report.update(parse_metadata)
        if posting is not None:
            report["public_metadata"] = inspect_smartrecruiters_posting(posting)
        else:
            report["public_metadata_error"] = (
                "Posting details could not be resolved from the official public API."
            )

        smart_token = os.getenv("SMARTRECRUITERS_SMART_TOKEN", "").strip()
        posting_uuid = str(report.get("posting_uuid") or "")
        if smart_token and posting_uuid:
            try:
                configuration = await fetch_smartrecruiters_configuration(
                    smart_token,
                    posting_uuid,
                    language=os.getenv("SMARTRECRUITERS_ACCEPT_LANGUAGE", "en"),
                )
                report["official_configuration"] = (
                    inspect_smartrecruiters_configuration(configuration)
                )
                report["official_configuration_status"] = "validated"
            except Exception as exc:
                report["official_configuration_status"] = "error"
                report["official_configuration_error"] = (
                    f"{type(exc).__name__}: {str(exc)[:500]}"
                )
        else:
            report["official_configuration_status"] = "not_configured"

        public_metadata = report.get("public_metadata") or {}
        dom = report["dom"]
        official_configuration = report.get("official_configuration")
        configuration_ok = (
            official_configuration is None
            or bool(official_configuration.get("configuration_certified"))
        )
        report["passed"] = bool(
            dom.get("visible_control_count", 0) > 0
            and report["submit_control_present"]
            and public_metadata.get("posting_metadata_certified")
            and configuration_ok
            and report["final_submit_clicked"] is False
        )
        if not report["passed"]:
            report["error"] = report.get("error") or (
                "SmartRecruiters surface was detected but public metadata, hosted "
                "controls, or configured official schema validation was not ready."
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


def _manual_challenge_ready(result: Dict[str, Any], submit_clicked: bool) -> bool:
    review_items = result.get("review_items") or []
    handoff = any(
        item.get("reason_code") in {
            "captcha_detected",
            "mfa_required",
            "login_required",
            "anti_bot_challenge",
        }
        and (item.get("details") or {}).get("handoff_stage") == "post_fill_pre_action"
        for item in review_items
    )
    verified_upload = any(
        item.get("verification") == "passed"
        for item in result.get("upload_evidence") or []
    )
    return bool(
        handoff
        and result.get("requires_manual_review")
        and int(result.get("fields_filled") or 0) > 0
        and verified_upload
        and not submit_clicked
    )


async def _build_profile_for_url(
    url: str,
    browser: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    page = None
    try:
        page, adapter, surface, _ = await _load_application_surface(url, browser)
        if adapter.name != "smartrecruiters":
            raise RuntimeError(
                "The URL was not detected as a SmartRecruiters application."
            )
        profile, metadata = await build_synthetic_profile_for_page(surface)
        company, posting_identifier, surface_kind = parse_smartrecruiters_job_url(
            page.url or url
        )
        metadata.update({
            "company_identifier": company,
            "posting_identifier": posting_identifier,
            "surface_kind": surface_kind,
            "synthetic_profile": True,
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
            "final_submit_clicked": False,
            "certification_metadata": certification_metadata or {},
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }

    submit_clicked = any(
        item.get("action") in {"ats_submit_clicked", "submit_click", "submit_clicked"}
        for item in result.get("log") or []
    )
    ready_to_submit = bool(
        result.get("success")
        and result.get("ready_to_submit")
        and result.get("ats_adapter") == "smartrecruiters"
        and not submit_clicked
    )
    manual_challenge_ready = _manual_challenge_ready(result, submit_clicked)
    passed = bool(
        result.get("ats_adapter") == "smartrecruiters"
        and (ready_to_submit or manual_challenge_ready)
        and not submit_clicked
    )
    outcome = (
        "ready_to_submit"
        if ready_to_submit
        else "manual_challenge_handoff"
        if manual_challenge_ready
        else "failed"
    )
    return {
        "url": url,
        "mode": "exercise",
        "passed": passed,
        "certification_outcome": outcome,
        "manual_challenge_ready": manual_challenge_ready,
        "adapter": result.get("ats_adapter"),
        "adapter_version": result.get("ats_adapter_version"),
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


async def main_async(args: Any) -> int:
    urls = parse_urls(args.urls or os.getenv("SMARTRECRUITERS_CERT_URLS", ""))
    if not urls:
        raise RuntimeError("At least one SmartRecruiters URL is required.")

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
                    "SMARTRECRUITERS_CERT_RESUME_PATH",
                    "smartrecruiters-synthetic-resume.pdf",
                )
                write_synthetic_resume(resume_path)
                cover_letter = os.getenv(
                    "SMARTRECRUITERS_CERT_COVER_LETTER",
                    SYNTHETIC_TEXT_RESPONSE,
                )
                for url in urls:
                    try:
                        profile, metadata = await _build_profile_for_url(url, browser)
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
        "certification": "smartrecruiters_supervised_live_dry_run",
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
        default="smartrecruiters-synthetic-resume.pdf",
    )
    parser.add_argument(
        "--report",
        default="smartrecruiters-live-certification.json",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

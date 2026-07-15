"""Supervised live Greenhouse dry-run certification.

This script never clicks a final submit control. It can inspect public Greenhouse
forms and, when explicitly configured, exercise all earlier form steps using a
user-provided synthetic certification profile.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List

from app.services.ats_greenhouse import (
    fetch_greenhouse_job_schema,
    inspect_greenhouse_schema,
    parse_greenhouse_job_url,
)
from app.services.ats_registry import detect_ats_adapter
from app.services.form_filler import fill_and_submit_application


def parse_urls(raw: str) -> List[str]:
    values = [
        item.strip()
        for item in re.split(r"[\n,]+", raw or "")
        if item.strip()
    ]
    return list(dict.fromkeys(values))


def load_profile() -> Dict[str, Any]:
    raw = os.getenv("GREENHOUSE_CERT_PROFILE_JSON", "").strip()
    if not raw:
        raise RuntimeError(
            "GREENHOUSE_CERT_PROFILE_JSON is required when --exercise is enabled."
        )
    profile = json.loads(raw)
    if not isinstance(profile, dict):
        raise RuntimeError("GREENHOUSE_CERT_PROFILE_JSON must decode to an object.")
    return profile


async def _visible_control_count(surface: Any) -> int:
    return int(await surface.locator(
        'input:not([type="hidden"]),textarea,select,button,[role="combobox"],'
        '[role="radio"],[role="checkbox"]'
    ).evaluate_all(
        """(elements) => elements.filter((el) => {
          const style = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.visibility !== 'hidden' && style.display !== 'none'
            && rect.width > 0 && rect.height > 0;
        }).length"""
    ))


async def inspect_live_url(url: str, browser) -> Dict[str, Any]:
    page = await browser.new_page()
    report: Dict[str, Any] = {"url": url, "mode": "inspect", "passed": False}
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            report["navigation_warning"] = str(exc)[:500]
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass

        report["loaded_url"] = page.url
        report["title"] = await page.title()
        adapter = await detect_ats_adapter(page, page.url or url)
        report["adapter"] = adapter.name
        report["adapter_version"] = adapter.version
        if adapter.name != "greenhouse":
            report["error"] = "The supplied URL was not detected as a Greenhouse application."
            return report

        surface = await adapter.resolve_surface(page)
        await adapter.prepare(surface, [])
        surface = await adapter.resolve_surface(page)
        report["surface_url"] = getattr(surface, "url", "") or page.url
        report["visible_controls"] = await _visible_control_count(surface)
        report["next_control_present"] = bool(await adapter.find_next_button(surface))
        report["submit_control_present"] = bool(await adapter.find_submit_button(surface))

        board_token, job_id = parse_greenhouse_job_url(report["surface_url"])
        if not job_id:
            board_token2, job_id2 = parse_greenhouse_job_url(page.url or url)
            board_token = board_token or board_token2
            job_id = job_id or job_id2
        report["board_token"] = board_token
        report["board_token_detected"] = bool(board_token)
        report["job_id"] = job_id

        if board_token and job_id:
            try:
                schema = await fetch_greenhouse_job_schema(board_token, job_id)
                report["schema"] = inspect_greenhouse_schema(schema)
            except Exception as exc:
                report["schema_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

        report["passed"] = (
            report["visible_controls"] > 0
            and (report["next_control_present"] or report["submit_control_present"])
            and not (report.get("schema") or {}).get("unsupported_fields")
        )
        if not report["passed"] and not report.get("error"):
            report["error"] = "Greenhouse surface was detected but was not certification-ready."
        return report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        report["traceback"] = traceback.format_exc(limit=8)[-4000:]
        return report
    finally:
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
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
    submit_clicked = any(
        item.get("action") in {"ats_submit_clicked", "submit_click", "submit_clicked"}
        for item in result.get("log") or []
    )
    passed = bool(
        result.get("success")
        and result.get("ready_to_submit")
        and result.get("ats_adapter") == "greenhouse"
        and not submit_clicked
    )
    return {
        "url": url,
        "mode": "exercise",
        "passed": passed,
        "adapter": result.get("ats_adapter"),
        "adapter_version": result.get("ats_adapter_version"),
        "ready_to_submit": result.get("ready_to_submit"),
        "steps_completed": result.get("steps_completed"),
        "fields_filled": result.get("fields_filled"),
        "review_items": result.get("review_items") or [],
        "validation_errors": result.get("validation_errors") or [],
        "upload_evidence": result.get("upload_evidence") or [],
        "step_evidence": result.get("step_evidence") or [],
        "final_submit_clicked": submit_clicked,
        "error": result.get("error"),
    }


async def main_async(args) -> int:
    urls = parse_urls(args.urls or os.getenv("GREENHOUSE_CERT_URLS", ""))
    if not urls:
        raise RuntimeError("At least one Greenhouse URL is required.")

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
        finally:
            await browser.close()

    if args.exercise:
        profile = load_profile()
        resume_path = os.getenv("GREENHOUSE_CERT_RESUME_PATH", "").strip()
        if not resume_path or not Path(resume_path).exists():
            raise RuntimeError(
                "GREENHOUSE_CERT_RESUME_PATH must point to a synthetic resume file "
                "when --exercise is enabled."
            )
        cover_letter = os.getenv("GREENHOUSE_CERT_COVER_LETTER", "")
        for url in urls:
            reports.append(await exercise_live_url(
                url,
                profile=profile,
                resume_path=resume_path,
                cover_letter=cover_letter,
            ))

    summary = {
        "certification": "greenhouse_supervised_live_dry_run",
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
    parser.add_argument("--report", default="greenhouse-live-certification.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

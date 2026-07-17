"""Supervised live Greenhouse dry-run certification.

This script never clicks a final submit control. It can inspect public Greenhouse
forms and exercise all earlier form steps using either an explicitly configured
profile or a generated synthetic certification identity.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.ats_greenhouse import (
    fetch_greenhouse_job_schema,
    inspect_greenhouse_schema,
    parse_greenhouse_job_url,
)
from app.services.ats_registry import detect_ats_adapter
from app.services.form_filler import fill_and_submit_application
from app.services.greenhouse_certification import (
    SYNTHETIC_TEXT_RESPONSE,
    build_synthetic_profile_for_url,
    write_synthetic_resume,
)


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
            "GREENHOUSE_CERT_PROFILE_JSON is required when --exercise is enabled "
            "without --synthetic-profile."
        )
    profile = json.loads(raw)
    if not isinstance(profile, dict):
        raise RuntimeError("GREENHOUSE_CERT_PROFILE_JSON must decode to an object.")
    return profile


def resolve_greenhouse_job_target(*urls: str) -> tuple[Optional[str], Optional[str]]:
    """Return the first usable Greenhouse board token and job id across URL candidates."""
    board_token: Optional[str] = None
    job_id: Optional[str] = None
    for candidate in urls:
        parsed_board_token, parsed_job_id = parse_greenhouse_job_url(candidate)
        if not board_token and parsed_board_token:
            board_token = parsed_board_token
        if not job_id and parsed_job_id:
            job_id = parsed_job_id
        if board_token and job_id:
            break
    return board_token, job_id


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

        board_token, job_id = resolve_greenhouse_job_target(
            report["surface_url"],
            page.url or "",
            url,
        )
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


def _manual_challenge_ready(result: Dict[str, Any], submit_clicked: bool) -> bool:
    review_items = result.get("review_items") or []
    captcha_handoff = any(
        item.get("reason_code") == "captcha_detected"
        and (item.get("details") or {}).get("handoff_stage") == "post_fill_pre_action"
        for item in review_items
    )
    verified_upload = any(
        item.get("verification") == "passed"
        for item in result.get("upload_evidence") or []
    )
    return bool(
        captcha_handoff
        and result.get("requires_manual_review")
        and int(result.get("fields_filled") or 0) > 0
        and verified_upload
        and not submit_clicked
    )


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
        and result.get("ats_adapter") == "greenhouse"
        and not submit_clicked
    )
    manual_challenge_ready = _manual_challenge_ready(result, submit_clicked)
    passed = bool(
        result.get("ats_adapter") == "greenhouse"
        and (ready_to_submit or manual_challenge_ready)
        and not submit_clicked
    )
    certification_outcome = (
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
        "certification_outcome": certification_outcome,
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
        synthetic_mode = bool(args.synthetic_profile)
        shared_profile: Optional[Dict[str, Any]] = None
        if synthetic_mode:
            resume_path = args.synthetic_resume_path or os.getenv(
                "GREENHOUSE_CERT_RESUME_PATH", "greenhouse-synthetic-resume.pdf"
            )
            write_synthetic_resume(resume_path)
            cover_letter = os.getenv(
                "GREENHOUSE_CERT_COVER_LETTER", SYNTHETIC_TEXT_RESPONSE
            )
        else:
            shared_profile = load_profile()
            resume_path = os.getenv("GREENHOUSE_CERT_RESUME_PATH", "").strip()
            if not resume_path or not Path(resume_path).exists():
                raise RuntimeError(
                    "GREENHOUSE_CERT_RESUME_PATH must point to a synthetic resume file "
                    "when --exercise is enabled."
                )
            cover_letter = os.getenv("GREENHOUSE_CERT_COVER_LETTER", "")

        for url in urls:
            try:
                if synthetic_mode:
                    profile, metadata = await build_synthetic_profile_for_url(url)
                    metadata["synthetic_profile"] = True
                else:
                    profile = dict(shared_profile or {})
                    metadata = {
                        "synthetic_profile": False,
                        "policy_count": len(profile.get("answer_policies") or []),
                    }
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
                    "certification_metadata": {"synthetic_profile": synthetic_mode},
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                    "traceback": traceback.format_exc(limit=8)[-4000:],
                })

    summary = {
        "certification": "greenhouse_supervised_live_dry_run",
        "final_submit_clicked": any(
            item.get("final_submit_clicked", False) for item in reports
        ),
        "url_count": len(urls),
        "exercise_enabled": bool(args.exercise),
        "synthetic_profile": bool(args.synthetic_profile),
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
    parser.add_argument("--synthetic-profile", action="store_true")
    parser.add_argument(
        "--synthetic-resume-path",
        default="greenhouse-synthetic-resume.pdf",
    )
    parser.add_argument("--report", default="greenhouse-live-certification.json")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

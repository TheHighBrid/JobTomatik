#!/usr/bin/env python3
"""Run one locked Lever Phase A target through a local human-verification handoff."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional


SUBMIT_GUARD_SCRIPT = r"""
() => {
  if (window.__jobtomatikPhaseAGuard) {
    return {
      installed: true,
      blocked_clicks: window.__jobtomatikPhaseAGuard.blockedClicks,
      blocked_submits: window.__jobtomatikPhaseAGuard.blockedSubmits,
    };
  }
  const state = { blockedClicks: 0, blockedSubmits: 0 };
  const applicationFormSelector = [
    'form.application-form',
    'form.postings-form',
    'form[action*="jobs.lever.co" i]',
    'form[action*="jobs.eu.lever.co" i]',
  ].join(',');
  const explicitFinalSelector = [
    '.application-submit button[type="submit"]',
    '.application-submit input[type="submit"]',
    '.postings-btn[type="submit"]',
  ].join(',');
  const normalizedLabel = (control) => String(
    control?.innerText || control?.value || control?.getAttribute?.('aria-label') || ''
  ).toLowerCase().replace(/\s+/g, ' ').trim();
  const looksLikeApplicationForm = (form) => Boolean(
    form instanceof HTMLFormElement && (
      form.matches(applicationFormSelector) || (
        form.querySelector('input[type="file"]') &&
        form.querySelector('input[type="email"], input[name*="email" i]')
      )
    )
  );
  const finalApplicationControl = (element) => {
    const control = element instanceof Element
      ? element.closest('button, input[type="submit"]')
      : null;
    if (!control) return null;
    const form = control.form || control.closest('form');
    if (!looksLikeApplicationForm(form)) return null;
    const label = normalizedLabel(control);
    if (
      control.matches(explicitFinalSelector) ||
      /^(submit|send) (your )?application$/.test(label) ||
      label === 'submit application'
    ) {
      return control;
    }
    return null;
  };
  const clickHandler = (event) => {
    const target = finalApplicationControl(event.target);
    if (!target) return;
    state.blockedClicks += 1;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  const submitHandler = (event) => {
    const form = event.target;
    if (!looksLikeApplicationForm(form)) return;
    const submitter = finalApplicationControl(event.submitter);
    const hasFinalControl = submitter || Array.from(
      form.querySelectorAll('button, input[type="submit"]')
    ).some((control) => Boolean(finalApplicationControl(control)));
    if (!hasFinalControl) return;
    state.blockedSubmits += 1;
    event.preventDefault();
    event.stopImmediatePropagation();
  };
  document.addEventListener('click', clickHandler, true);
  document.addEventListener('submit', submitHandler, true);
  window.__jobtomatikPhaseAGuard = {
    state,
    clickHandler,
    submitHandler,
    get blockedClicks() { return state.blockedClicks; },
    get blockedSubmits() { return state.blockedSubmits; },
  };
  return { installed: true, blocked_clicks: 0, blocked_submits: 0 };
}
"""

SUBMIT_GUARD_STATE_SCRIPT = r"""
() => {
  const guard = window.__jobtomatikPhaseAGuard;
  return {
    installed: Boolean(guard),
    blocked_clicks: guard ? guard.blockedClicks : 0,
    blocked_submits: guard ? guard.blockedSubmits : 0,
  };
}
"""


def _configure_safe_environment() -> None:
    os.environ["APPLICATION_BROWSER_HEADLESS"] = "false"
    os.environ["ALLOW_REAL_APPLICATION_SUBMIT"] = "false"
    os.environ["LEVER_SUPERVISED_PILOT_ENABLED"] = "false"
    os.environ["AUTOPILOT_ENABLED"] = "false"
    os.environ["ENABLE_RESUMABLE_HANDOFFS"] = "false"
    os.environ.setdefault("AI_PROVIDER", "template")
    os.environ.setdefault("SECRET_KEY", "lever-phase-a-local-synthetic-secret")

    from app.config import get_settings

    get_settings.cache_clear()


async def _inspect_profile_and_target(
    target: Mapping[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    from playwright.async_api import async_playwright

    from app.services.lever_phase_a_operator import frozen_target_identity
    from app.services.supervised_target_identity import resolve_supervised_target_metadata
    from scripts.certify_lever_live import _build_profile_for_url, inspect_live_url

    url = str(target["canonical_application_url"])
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            inspection = await inspect_live_url(url, browser)
            profile, certification_metadata = await _build_profile_for_url(url, browser)
        finally:
            await browser.close()

    if inspection.get("passed") is not True:
        raise RuntimeError(
            "The locked target no longer passes official posting and hosted-form inspection: "
            + str(inspection.get("error") or "inspection failed")
        )

    job = SimpleNamespace(
        title=target["role"],
        url=url,
        raw_data={"selected_apply_url": url},
    )
    target_metadata = await resolve_supervised_target_metadata(job)
    if target_metadata.get("verified") is not True:
        blockers = ", ".join(target_metadata.get("blockers") or ["target_unverified"])
        raise RuntimeError(
            f"The locked target identity no longer matches official Lever metadata: {blockers}"
        )
    return inspection, profile, certification_metadata | {
        "supervised_target": target_metadata,
        "frozen_target": frozen_target_identity(target),
        "review_id": target["review_id"],
        "locked_corpus_path": target["corpus_path"],
        "locked_corpus_sha256": target["corpus_sha256"],
    }


async def _browser_evaluate(session: Any, expression: str) -> Dict[str, Any]:
    from app.services.retained_browser_operator import evaluate_retained_browser

    value = await evaluate_retained_browser(session, expression)
    return dict(value or {})


async def _wait_for_challenge(
    session: Any,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    from app.services.browser_handoff import verify_browser_handoff_completion

    await _browser_evaluate(session, SUBMIT_GUARD_SCRIPT)
    print()
    print("A visible Chromium window is holding the exact filled Lever application.")
    print("Complete only the CAPTCHA or human-verification widget.")
    print("Do not press the application submit button. JobTomatik blocks submit events.")
    while True:
        answer = await asyncio.to_thread(
            input,
            "After the challenge is complete, press Enter to verify it, or type q to cancel: ",
        )
        if answer.strip().lower() in {"q", "quit", "cancel"}:
            raise RuntimeError("Operator cancelled the interactive handoff")
        verification = await verify_browser_handoff_completion(session)
        if verification.challenge_cleared:
            session.current_url = verification.current_url
            session.current_fingerprint = verification.current_fingerprint
            guard = await _browser_evaluate(session, SUBMIT_GUARD_STATE_SCRIPT)
            return verification.as_dict(), guard
        method = verification.evidence.get("verification_method") or "browser_state"
        print(f"The protected step is still active ({method}). Complete it and try again.")


async def run(args: argparse.Namespace) -> int:
    from app.services.browser_handoff import resume_handoff_application
    from app.services.form_filler import fill_and_submit_application
    from app.services.lever_certification import (
        SYNTHETIC_TEXT_RESPONSE,
        write_synthetic_resume,
    )
    from app.services.lever_phase_a_operator import (
        LeverPhaseAOperatorError,
        build_phase_a_report,
        build_resumed_exercise,
        challenge_reason,
        load_locked_target,
        transient_cleanup_session,
        transient_handoff_session,
        write_report,
    )
    from app.services.retained_browser_operator import (
        terminate_and_cleanup_retained_browser,
    )
    from scripts.certify_lever_live import _manual_challenge_ready

    target = load_locked_target(args.review_id, Path(args.corpus_root))
    output_dir = Path(args.output_dir) / str(target["review_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "lever-phase-a-interactive-report.json"
    resume_path = output_dir / "lever-phase-a-synthetic-resume.pdf"
    write_synthetic_resume(str(resume_path))

    inspection, profile, certification_metadata = await _inspect_profile_and_target(target)
    certification_metadata["interactive_operator"] = args.operator
    target_metadata = certification_metadata["supervised_target"]
    url = str(target["canonical_application_url"])
    initial_result = await fill_and_submit_application(
        job_url=url,
        user_profile=profile,
        cover_letter=SYNTHETIC_TEXT_RESPONSE,
        resume_path=str(resume_path),
        dry_run=True,
        supervised_target=target_metadata,
    )

    session: Optional[Any] = None
    cleanup_session: Optional[Any] = None
    try:
        reason = challenge_reason(initial_result)
        snapshot = dict(initial_result.get("handoff_snapshot") or {})
        if snapshot:
            cleanup_session = transient_cleanup_session(snapshot)
        if snapshot and reason:
            session = transient_handoff_session(
                snapshot,
                reason_code=reason,
                target_metadata=target_metadata,
            )
        if not _manual_challenge_ready(
            dict(initial_result),
            any(
                item.get("action") in {
                    "ats_submit_clicked",
                    "submit_click",
                    "submit_clicked",
                }
                for item in initial_result.get("log") or []
            ),
        ):
            raise LeverPhaseAOperatorError(
                "The selected target did not reach a clean resumable human-verification "
                "boundary. This interactive runner does not certify ordinary dry runs, "
                "and no answer or control will be guessed."
            )
        if session is None:
            raise LeverPhaseAOperatorError(
                "The clean handoff boundary did not retain a local browser session"
            )

        handoff_verification, submit_guard = await _wait_for_challenge(session)
        resumed_result = await resume_handoff_application(
            session,
            user_profile=profile,
            cover_letter=SYNTHETIC_TEXT_RESPONSE,
            resume_path=str(resume_path),
            dry_run=True,
        )
        exercise = build_resumed_exercise(
            url=url,
            initial_result=initial_result,
            resumed_result=resumed_result,
            certification_metadata=certification_metadata,
            handoff_verification=handoff_verification,
            submit_guard=submit_guard,
        )
        report = build_phase_a_report(inspection, exercise)
        digest = write_report(report_path, report)

        if report.get("passed") is not True:
            print(json.dumps(report, indent=2, default=str))
            print(f"Nonqualifying report retained at {report_path}")
            return 1

        print()
        print("Lever Phase A interactive handoff completed without submission.")
        print(f"Report:  {report_path}")
        print(f"SHA-256: {digest}")
        print("No candidate CSV was emitted. Local evidence cannot self-certify.")
        print(
            "Commit the report, retain it with the Lever Phase A interactive "
            "retention workflow, then run finalize_lever_phase_a_handoff.py with "
            "the GitHub workflow run ID, artifact ID, and artifact digest."
        )
        return 0
    finally:
        if cleanup_session is not None:
            try:
                terminate_and_cleanup_retained_browser(cleanup_session)
            except Exception as exc:
                print(f"Warning: retained Chromium cleanup failed: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-id", required=True)
    parser.add_argument(
        "--corpus-root",
        default="evidence/lever-phase-a-target-corpus",
    )
    parser.add_argument(
        "--output-dir",
        default="evidence/lever-phase-a-artifacts",
    )
    parser.add_argument("--operator", default=getpass.getuser())
    args = parser.parse_args()

    if sys.platform.startswith("linux") and not (
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    ):
        raise SystemExit(
            "Interactive Phase A handoff requires a visible desktop session. "
            "Run it from XFCE/X11 or another graphical Linux session."
        )
    _configure_safe_environment()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

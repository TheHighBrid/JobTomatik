"""Compatibility surface for ATS-aware application form runners."""

from app.services.browser_runtime import resumable_handoffs_enabled
from app.services.form_filler_handoff import fill_and_submit_application_with_handoff
from app.services.form_filler_v3 import (
    _navigate_job_board_listing,
    fill_and_submit_application as fill_and_submit_application_standard,
)
from app.services.greenhouse_aria_id_widget import (
    install_greenhouse_aria_id_compat,
)
from app.services.greenhouse_location_widget import (
    install_greenhouse_location_widget_compat,
)
from app.services.greenhouse_phone_widget import (
    install_greenhouse_phone_widget_compat,
)
from app.services.supervised_runtime import current_supervised_target


install_greenhouse_aria_id_compat()
install_greenhouse_phone_widget_compat()
install_greenhouse_location_widget_compat()


def _dry_run_requested(args, kwargs) -> bool:
    if "dry_run" in kwargs:
        return bool(kwargs["dry_run"])
    if len(args) >= 5:
        return bool(args[4])
    return True


async def fill_and_submit_application(*args, **kwargs):
    # A live supervised worker binds the exact approved target only for the
    # duration of its own task call. Explicit kwargs remain authoritative.
    if "supervised_target" not in kwargs:
        supervised_target = current_supervised_target()
        if supervised_target:
            kwargs["supervised_target"] = supervised_target

    # Dry runs must preserve CAPTCHA/login boundaries so the user can complete
    # them in the same filled browser session. Explicit configuration extends
    # the same retained-browser behavior to supervised non-dry runs.
    if _dry_run_requested(args, kwargs) or resumable_handoffs_enabled():
        return await fill_and_submit_application_with_handoff(*args, **kwargs)
    return await fill_and_submit_application_standard(*args, **kwargs)


__all__ = ["fill_and_submit_application", "_navigate_job_board_listing"]

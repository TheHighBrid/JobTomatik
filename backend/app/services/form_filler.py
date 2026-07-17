"""Compatibility surface for ATS-aware application form runners."""

from app.services.browser_runtime import resumable_handoffs_enabled
from app.services.form_filler_handoff import fill_and_submit_application_with_handoff
from app.services.form_filler_v3 import (
    _navigate_job_board_listing,
    fill_and_submit_application as fill_and_submit_application_standard,
)
from app.services.greenhouse_location_widget import (
    install_greenhouse_location_widget_compat,
)
from app.services.greenhouse_phone_widget import (
    install_greenhouse_phone_widget_compat,
)


install_greenhouse_phone_widget_compat()
install_greenhouse_location_widget_compat()


async def fill_and_submit_application(*args, **kwargs):
    if resumable_handoffs_enabled():
        return await fill_and_submit_application_with_handoff(*args, **kwargs)
    return await fill_and_submit_application_standard(*args, **kwargs)


__all__ = ["fill_and_submit_application", "_navigate_job_board_listing"]

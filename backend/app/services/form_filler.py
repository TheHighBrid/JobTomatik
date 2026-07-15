"""Compatibility surface for the verified application form filler."""

from app.services.form_filler_v2 import (
    _navigate_job_board_listing,
    fill_and_submit_application,
)

__all__ = ["fill_and_submit_application", "_navigate_job_board_listing"]

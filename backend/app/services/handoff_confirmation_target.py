"""Confirmation-aware compatibility for retained supervised target checks.

Some ATS confirmation pages remain on the approved employer site but omit the
posting identifier from the final URL. The target lock may accept that shape only
when explicit employer confirmation text is present. URL shape alone is never
sufficient.
"""

from __future__ import annotations


_INSTALLED = False
_ORIGINAL_VERIFY = None


def install_handoff_confirmation_target_support() -> None:
    global _INSTALLED, _ORIGINAL_VERIFY
    if _INSTALLED:
        return

    from app.services import browser_handoff

    _ORIGINAL_VERIFY = browser_handoff._verify_session_target

    async def confirmation_aware_verify(
        page,
        session,
        *,
        refresh_official_metadata: bool = False,
        allow_same_site_confirmation: bool = False,
    ):
        expected = browser_handoff._session_supervised_target(session)
        if expected and not allow_same_site_confirmation:
            confirmation = await browser_handoff._submission_confirmation_state(page)
            allow_same_site_confirmation = bool(
                confirmation.get("submission_confirmed")
            )

        return await _ORIGINAL_VERIFY(
            page,
            session,
            refresh_official_metadata=refresh_official_metadata,
            allow_same_site_confirmation=allow_same_site_confirmation,
        )

    browser_handoff._verify_session_target = confirmation_aware_verify
    _INSTALLED = True


__all__ = ["install_handoff_confirmation_target_support"]

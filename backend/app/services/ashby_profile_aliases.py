"""Install narrowly scoped Ashby system-field aliases into the shared profile mapper."""

from app.services.form_filler_v2 import SAFE_PROFILE_FIELDS

_ASHBY_NAME_PATTERN = r"^\s*name\s*$|\b_systemfield_name\b"


def install_ashby_profile_aliases() -> None:
    """Map only Ashby's exact bare Name system field to the full-name profile value."""
    if any(pattern == _ASHBY_NAME_PATTERN for pattern, _ in SAFE_PROFILE_FIELDS):
        return
    SAFE_PROFILE_FIELDS.insert(2, (_ASHBY_NAME_PATTERN, "full_name"))

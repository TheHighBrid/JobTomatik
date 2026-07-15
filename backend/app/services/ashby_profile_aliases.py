"""Install narrowly scoped Ashby system-field aliases into the shared profile mapper."""

from app.services.form_filler_v2 import SAFE_PROFILE_FIELDS

# The descriptor engine includes both stable attributes and explicit labels, so
# Ashby's system Name field commonly resolves to ``name | Name``. Match only one
# or more exact ``name`` tokens separated by descriptor pipes. This deliberately
# excludes company name, reference name, preferred name, and other custom fields.
_ASHBY_NAME_PATTERN = r"^\s*name(?:\s*\|\s*name)*\s*$|\b_systemfield_name\b"


def install_ashby_profile_aliases() -> None:
    """Map only Ashby's exact Name system descriptor to the full-name value."""
    if any(pattern == _ASHBY_NAME_PATTERN for pattern, _ in SAFE_PROFILE_FIELDS):
        return
    SAFE_PROFILE_FIELDS.insert(2, (_ASHBY_NAME_PATTERN, "full_name"))

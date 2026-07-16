"""Runtime normalization for documented SmartRecruiters public-posting variability."""

from app.services import ats_smartrecruiters


def install_smartrecruiters_contract_normalization() -> None:
    """Treat ``ref`` as optional because current posting details may omit it.

    The stable certification identity is the posting id/uuid, company identifier,
    active status, and apply URL. A missing convenience reference URL must not turn
    otherwise valid official metadata into a false failure.
    """
    ats_smartrecruiters.SMARTRECRUITERS_POSTING_FIELDS.discard("ref")

"""Owner-reviewed recovery of an existing JT5 attempt, never an Apply request."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JT5OutcomeResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    attempt_reference: str = Field(min_length=1, max_length=96)
    outcome: Literal["confirmed", "not_submitted"]
    evidence_source: Literal["retained_confirmation", "employer_response", "employer_portal"]
    evidence_reference: str = Field(min_length=1, max_length=1000)
    notes: str = Field(min_length=20, max_length=4000)
    outcome_verified: Literal[True]
    evidence_id: int | None = Field(default=None, gt=0)
    evidence_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ShadowCampaignStartRequest(BaseModel):
    target_evidence_type: Literal["shadow_run_4h", "shadow_run_8h", "shadow_run_24h"]
    acknowledgment: str = Field(min_length=1, max_length=200)
    cycle_interval_seconds: int = Field(default=900, ge=60, le=3600)

    @field_validator("acknowledgment")
    @classmethod
    def normalize_acknowledgment(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ShadowCampaignStopRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=160)

    @field_validator("acknowledgment")
    @classmethod
    def normalize_acknowledgment(cls, value: str) -> str:
        return " ".join(value.strip().split())


class ShadowCampaignDispatchOut(BaseModel):
    session_id: int
    status: str
    celery_task_id: str | None = None
    candidate_revision: str
    target_evidence_type: str
    requested_duration_seconds: int
    expected_end_at: str | None = None
    submission_authorized: bool = False
    outreach_authorized: bool = False

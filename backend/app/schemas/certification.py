from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CertificationEvidenceCreate(BaseModel):
    evidence_type: str = Field(min_length=1, max_length=80)
    adapter: str | None = Field(default=None, max_length=80)
    commit_sha: str = Field(min_length=7, max_length=64)
    environment: str = Field(min_length=1, max_length=80)
    status: Literal["passed", "failed"]
    duration_seconds: int | None = Field(default=None, ge=0, le=60 * 60 * 24 * 31)
    source_reference: str = Field(min_length=1, max_length=1000)
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None

    @field_validator("evidence_type", "adapter", "environment", "source_reference")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @field_validator("commit_sha")
    @classmethod
    def normalize_commit_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not all(character in "0123456789abcdef" for character in normalized):
            raise ValueError("commit_sha must be hexadecimal")
        return normalized


class CertificationEvidenceOut(BaseModel):
    evidence_id: int
    evidence_key: str
    evidence_type: str
    adapter: str | None = None
    commit_sha: str
    environment: str
    status: str
    duration_seconds: int | None = None
    source_reference: str
    payload_hash: str
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: str
    reviewed_by_user_id: int | None = None
    reviewed_at: datetime | None = None
    review_reference: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    duplicate: bool = False


class EvidenceReviewRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=160)
    review_reference: str = Field(min_length=1, max_length=1000)

    @field_validator("acknowledgment", "review_reference")
    @classmethod
    def normalize_review_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class EvidenceReviewOut(BaseModel):
    evidence_id: int
    review_status: str
    reviewed_by_user_id: int
    reviewed_at: datetime
    review_reference: str
    qualifying_for_current_head: bool
    qualifying_reasons: list[str] = Field(default_factory=list)


class ReleaseAuthorizationCreate(BaseModel):
    scope: Literal["autonomous_pilot", "v2_release"]
    release_version: str = Field(min_length=1, max_length=80)
    commit_sha: str = Field(min_length=7, max_length=64)
    approval_reference: str = Field(min_length=1, max_length=255)
    acknowledgment: str = Field(min_length=1, max_length=240)
    expires_at: datetime | None = None

    @field_validator("release_version", "approval_reference", "acknowledgment")
    @classmethod
    def normalize_authorization_text(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("commit_sha")
    @classmethod
    def normalize_authorization_sha(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not all(character in "0123456789abcdef" for character in normalized):
            raise ValueError("commit_sha must be hexadecimal")
        return normalized


class ReleaseAuthorizationOut(BaseModel):
    authorization_id: int
    scope: str
    release_version: str
    commit_sha: str
    approval_reference: str
    status: str
    approved_by_user_id: int
    approved_at: datetime
    expires_at: datetime | None = None
    runtime_enablement_changed: bool = False


class AuthorizationRevokeRequest(BaseModel):
    acknowledgment: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("acknowledgment", "reason")
    @classmethod
    def normalize_revoke_text(cls, value: str) -> str:
        return " ".join(value.strip().split())


class CertificationManifestOut(BaseModel):
    version: str
    generated_at: datetime
    release_version: str
    candidate_revision: str
    candidate_revision_known: bool
    adapter: str | None = None
    tracks: dict[str, Any]
    runtime_controls: dict[str, Any]
    adapter_maturity: dict[str, Any]
    invariants: dict[str, bool]

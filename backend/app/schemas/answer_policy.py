from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.answer_policy import (
    AnswerPolicyMode,
    AnswerPolicyProvenance,
    AnswerPolicyScope,
)


class AnswerPolicyCreate(BaseModel):
    canonical_key: str = Field(min_length=2, max_length=120)
    mode: AnswerPolicyMode = AnswerPolicyMode.ask_each_time
    answer_value: Optional[str] = Field(default=None, max_length=4000)
    answer_label: Optional[str] = Field(default=None, max_length=1000)
    fallback_answers: List[str] = Field(default_factory=list, max_length=20)
    match_phrases: List[str] = Field(default_factory=list, max_length=25)
    scope: AnswerPolicyScope = AnswerPolicyScope.global_scope
    scope_value: str = Field(default="", max_length=255)
    allow_autofill: bool = False
    confirmed: bool = False
    is_active: bool = True
    provenance: AnswerPolicyProvenance = AnswerPolicyProvenance.user_provided
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    expires_at: Optional[datetime] = None


class AnswerPolicyUpdate(BaseModel):
    mode: Optional[AnswerPolicyMode] = None
    answer_value: Optional[str] = Field(default=None, max_length=4000)
    answer_label: Optional[str] = Field(default=None, max_length=1000)
    fallback_answers: Optional[List[str]] = Field(default=None, max_length=20)
    match_phrases: Optional[List[str]] = Field(default=None, max_length=25)
    scope: Optional[AnswerPolicyScope] = None
    scope_value: Optional[str] = Field(default=None, max_length=255)
    allow_autofill: Optional[bool] = None
    confirmed: Optional[bool] = None
    is_active: Optional[bool] = None
    provenance: Optional[AnswerPolicyProvenance] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[datetime] = None


class AnswerPolicyOut(BaseModel):
    id: int
    canonical_key: str
    category: str
    sensitivity: str
    mode: str
    answer_value: Optional[str]
    answer_label: Optional[str]
    fallback_answers: List[str]
    match_phrases: List[str]
    scope: str
    scope_value: str
    allow_autofill: bool
    is_active: bool
    confirmed_at: Optional[datetime]
    provenance: str
    confidence: float
    consent_metadata: Dict[str, Any]
    source_metadata: Dict[str, Any]
    expires_at: Optional[datetime]
    is_expired: bool
    encryption_valid: bool
    version: int
    created_at: datetime
    updated_at: Optional[datetime]


class AnswerPolicyCatalogItem(BaseModel):
    canonical_key: str
    label: str
    category: str
    sensitivity: str
    description: str
    patterns: List[str]
    setup_group: str
    suggested_answers: List[str]
    fallback_suggestions: List[str]
    default_mode: str


class AnswerPolicyBulkUpsert(BaseModel):
    items: List[AnswerPolicyCreate] = Field(min_length=1, max_length=75)


class AnswerPolicyBulkResult(BaseModel):
    policies: List[AnswerPolicyOut]
    created: int
    updated: int


class AnswerPolicyReadinessReport(BaseModel):
    country_code: str
    platform: str
    target_url: str
    company: str
    ready_for_unattended: bool
    completeness_score: float
    required_profile_fields: List[Dict[str, Any]]
    required_policies: List[Dict[str, Any]]
    blockers: List[Dict[str, Any]]
    conflicts: List[Dict[str, Any]]
    summary: Dict[str, int]
    guarantees: List[str]
    generated_at: datetime

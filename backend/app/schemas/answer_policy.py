from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.answer_policy import AnswerPolicyMode, AnswerPolicyScope


class AnswerPolicyCreate(BaseModel):
    canonical_key: str = Field(min_length=2, max_length=120)
    mode: AnswerPolicyMode = AnswerPolicyMode.ask_each_time
    answer_value: Optional[str] = Field(default=None, max_length=4000)
    answer_label: Optional[str] = Field(default=None, max_length=1000)
    match_phrases: List[str] = Field(default_factory=list, max_length=25)
    scope: AnswerPolicyScope = AnswerPolicyScope.global_scope
    scope_value: str = Field(default="", max_length=255)
    allow_autofill: bool = False
    confirmed: bool = False
    is_active: bool = True


class AnswerPolicyUpdate(BaseModel):
    mode: Optional[AnswerPolicyMode] = None
    answer_value: Optional[str] = Field(default=None, max_length=4000)
    answer_label: Optional[str] = Field(default=None, max_length=1000)
    match_phrases: Optional[List[str]] = Field(default=None, max_length=25)
    scope: Optional[AnswerPolicyScope] = None
    scope_value: Optional[str] = Field(default=None, max_length=255)
    allow_autofill: Optional[bool] = None
    confirmed: Optional[bool] = None
    is_active: Optional[bool] = None


class AnswerPolicyOut(BaseModel):
    id: int
    canonical_key: str
    category: str
    sensitivity: str
    mode: str
    answer_value: Optional[str]
    answer_label: Optional[str]
    match_phrases: List[str]
    scope: str
    scope_value: str
    allow_autofill: bool
    is_active: bool
    confirmed_at: Optional[datetime]
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

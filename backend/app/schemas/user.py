from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 200:
            raise ValueError("Full name must be 200 characters or fewer")
        return normalized


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    email_signature: Optional[str] = None
    profile_data: Optional[Dict[str, Any]] = None
    job_preferences: Optional[Dict[str, Any]] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    linkedin_url: Optional[str]
    github_url: Optional[str]
    portfolio_url: Optional[str]
    resume_filename: Optional[str]
    profile_data: Optional[Dict[str, Any]]
    job_preferences: Optional[Dict[str, Any]]
    email_signature: Optional[str]
    created_at: datetime


class UserProfile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: Optional[str]
    email: str
    phone: Optional[str]
    address: Optional[str]
    linkedin_url: Optional[str]
    github_url: Optional[str]
    portfolio_url: Optional[str]
    resume_filename: Optional[str]
    profile_data: Optional[Dict[str, Any]]
    job_preferences: Optional[Dict[str, Any]]


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class TokenData(BaseModel):
    user_id: Optional[int] = None

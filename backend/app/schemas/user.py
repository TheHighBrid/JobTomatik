from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from datetime import datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


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

    class Config:
        from_attributes = True


class UserProfile(BaseModel):
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

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class TokenData(BaseModel):
    user_id: Optional[int] = None

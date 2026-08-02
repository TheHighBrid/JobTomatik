from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobSource, JobStatus, JobType


class ATSTarget(BaseModel):
    provider: Literal["greenhouse", "lever", "ashby"]
    identifier: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    company: Optional[str] = Field(default=None, max_length=255)


class JobSearch(BaseModel):
    keywords: str = Field(min_length=1, max_length=500)
    location: Optional[str] = Field(default=None, max_length=255)
    salary_min: Optional[int] = Field(default=None, ge=0)
    salary_max: Optional[int] = Field(default=None, ge=0)
    job_type: Optional[JobType] = None
    sources: Optional[List[JobSource]] = None
    ats_targets: List[ATSTarget] = Field(default_factory=list, max_length=25)
    remote_only: Optional[bool] = False
    limit: int = Field(default=50, ge=1, le=100)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: Optional[str]
    title: str
    company: str
    location: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_currency: Optional[str]
    job_type: Optional[JobType]
    description: Optional[str]
    requirements: Optional[str]
    url: Optional[str]
    source: Optional[JobSource]
    status: JobStatus
    tags: Optional[List[str]]
    skills: Optional[List[str]]
    seniority: Optional[str]
    industry: Optional[str]
    relevance_score: Optional[float]
    created_at: datetime


class JobListOut(BaseModel):
    jobs: List[JobOut]
    total: int
    page: int
    per_page: int

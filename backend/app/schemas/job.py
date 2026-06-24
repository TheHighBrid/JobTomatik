from pydantic import BaseModel
from typing import Optional, List, Any, Dict
from datetime import datetime
from app.models.job import JobSource, JobType, JobStatus


class JobSearch(BaseModel):
    keywords: str
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    job_type: Optional[JobType] = None
    sources: Optional[List[JobSource]] = None
    remote_only: Optional[bool] = False
    limit: Optional[int] = 50


class JobOut(BaseModel):
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

    class Config:
        from_attributes = True


class JobListOut(BaseModel):
    jobs: List[JobOut]
    total: int
    page: int
    per_page: int

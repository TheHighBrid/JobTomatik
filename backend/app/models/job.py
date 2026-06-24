from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, Float, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum


class JobSource(str, enum.Enum):
    linkedin = "linkedin"
    indeed = "indeed"
    glassdoor = "glassdoor"
    manual = "manual"


class JobType(str, enum.Enum):
    full_time = "full_time"
    part_time = "part_time"
    contract = "contract"
    internship = "internship"
    remote = "remote"


class JobStatus(str, enum.Enum):
    new = "new"
    queued = "queued"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), index=True)
    title = Column(String(500), nullable=False)
    company = Column(String(255), nullable=False)
    location = Column(String(255))
    salary_min = Column(Integer)
    salary_max = Column(Integer)
    salary_currency = Column(String(10), default="USD")
    job_type = Column(Enum(JobType))
    description = Column(Text)
    requirements = Column(Text)
    url = Column(String(1000))
    source = Column(Enum(JobSource), default=JobSource.manual)
    status = Column(Enum(JobStatus), default=JobStatus.new)
    tags = Column(JSON, default=[])
    skills = Column(JSON, default=[])
    seniority = Column(String(100))
    industry = Column(String(255))
    relevance_score = Column(Float, default=0.0)
    raw_data = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    from sqlalchemy.orm import relationship
    applications = relationship("Application", back_populates="job")

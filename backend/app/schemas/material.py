from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EvidenceUnitCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=60)
    label: str = Field(min_length=2, max_length=255)
    statement: str = Field(min_length=2, max_length=5000)
    organization: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = Field(default=None, max_length=255)
    source_ref: Optional[str] = Field(default=None, max_length=1000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EvidenceUnitUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=2, max_length=255)
    statement: Optional[str] = Field(default=None, min_length=2, max_length=5000)
    organization: Optional[str] = Field(default=None, max_length=255)
    role: Optional[str] = Field(default=None, max_length=255)
    verification_status: Optional[str] = Field(default=None, max_length=40)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None
    provenance: Optional[Dict[str, Any]] = None


class EvidenceUnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    kind: str
    label: str
    statement: str
    organization: Optional[str]
    role: Optional[str]
    source_type: str
    source_ref: str
    source_hash: str
    verification_status: str
    confidence: float
    provenance: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]


class MaterialEvidenceLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    evidence_unit_id: int
    usage: str
    claim_indexes: List[int] = Field(default_factory=list)
    evidence_unit: Optional[EvidenceUnitOut] = None


class ApplicationMaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    application_id: int
    material_type: str
    version: int
    status: str
    content: str
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source_snapshot: Dict[str, Any] = Field(default_factory=dict)
    generator_version: str
    supersedes_material_id: Optional[int]
    evidence_links: List[MaterialEvidenceLinkOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime]


class EvidenceRebuildOut(BaseModel):
    created: int
    reused: int
    deactivated: int
    total_active: int
    sources: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class MaterialGenerationOut(BaseModel):
    material: ApplicationMaterialOut
    evidence_unit_count: int
    verified_claim_count: int
    warning_count: int

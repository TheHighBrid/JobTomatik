from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class EvidenceUnit(Base):
    __tablename__ = "evidence_units"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_ref",
            "source_hash",
            name="uq_evidence_unit_source_hash",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(60), nullable=False, index=True)
    label = Column(String(255), nullable=False, index=True)
    statement = Column(Text, nullable=False)
    organization = Column(String(255), index=True)
    role = Column(String(255), index=True)
    source_type = Column(String(60), nullable=False, index=True)
    source_ref = Column(String(1000), nullable=False, index=True)
    source_hash = Column(String(64), nullable=False, index=True)
    verification_status = Column(
        String(40),
        nullable=False,
        default="source_backed",
        index=True,
    )
    confidence = Column(Float, nullable=False, default=0.8)
    provenance = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    materials = relationship(
        "ApplicationMaterialEvidence",
        back_populates="evidence_unit",
        cascade="all, delete-orphan",
    )


class ApplicationMaterial(Base):
    __tablename__ = "application_materials"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "material_type",
            "version",
            name="uq_application_material_version",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    material_type = Column(String(50), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(40), nullable=False, default="draft", index=True)
    content = Column(Text, nullable=False)
    claims = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    source_snapshot = Column(JSON, nullable=False, default=dict)
    generator_version = Column(String(80), nullable=False, default="verified-material-v1")
    supersedes_material_id = Column(Integer, ForeignKey("application_materials.id"), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    application = relationship("Application", back_populates="materials")
    evidence_links = relationship(
        "ApplicationMaterialEvidence",
        back_populates="material",
        cascade="all, delete-orphan",
        order_by="ApplicationMaterialEvidence.id",
    )


class ApplicationMaterialEvidence(Base):
    __tablename__ = "application_material_evidence"
    __table_args__ = (
        UniqueConstraint(
            "material_id",
            "evidence_unit_id",
            name="uq_material_evidence_link",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    material_id = Column(Integer, ForeignKey("application_materials.id"), nullable=False, index=True)
    evidence_unit_id = Column(Integer, ForeignKey("evidence_units.id"), nullable=False, index=True)
    usage = Column(String(80), nullable=False, default="supporting_claim", index=True)
    claim_indexes = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    material = relationship("ApplicationMaterial", back_populates="evidence_links")
    evidence_unit = relationship("EvidenceUnit", back_populates="materials")

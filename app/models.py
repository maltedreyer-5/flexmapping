# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
SQLAlchemy models for FlexMapping.

Foreign keys carry explicit ondelete behaviour so that deleting an entity
cannot orphan the extractions that reference it.
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# Enums

class JobType(str, Enum):
    """Job types for background processing"""
    CRAWL = "crawl"
    EXTRACT = "extract"
    VALIDATE = "validate"
    NORMALIZE = "normalize"
    GENERATE = "generate"
    TRANSLATE = "translate"  # Translation jobs


class Role(str, Enum):
    """
    Access levels for the admin interface and the admin API.

    The boundary that matters in this application is not read versus write, but
    "corrects a single value" versus "changes how extraction works". An editor
    who could edit prompts would silently change every future extraction in
    every category, so prompts, categories and entity master data are reserved
    for ADMIN.
    """
    VIEWER = "viewer"    # read-only
    EDITOR = "editor"    # curate content: sources, extractions, review queue
    ADMIN = "admin"      # configuration, master data, destructive operations

    @property
    def rank(self) -> int:
        return {"viewer": 0, "editor": 1, "admin": 2}[self.value]

    def covers(self, required: "Role") -> bool:
        """True if this role includes the permissions of the required one."""
        return self.rank >= required.rank


class JobPriority:
    """
    Job priority levels (higher = more urgent).

    TRANSLATE sits below every extraction stage on purpose: a translation is
    only worth running once the German result it translates is final, so it
    must not compete with extract and validate work for LLM capacity.
    """
    CRAWL = 100
    EXTRACT_INDEPENDENT = 50
    VALIDATE = 45
    EXTRACT_DEPENDENT = 40
    NORMALIZE = 30
    TRANSLATE = 20
    GENERATE = 10


# Models

class Source(Base):
    """Gecrawlte Webseiten"""
    __tablename__ = "sources"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    url = Column(Text, unique=True, nullable=False, index=True)
    markdown_content = Column(Text)
    markdown_size = Column(Integer)
    pages_crawled = Column(Integer, default=1)
    crawled_at = Column(DateTime(timezone=True))
    status = Column(
        String(50),
        CheckConstraint("status IN ('pending', 'crawled', 'extracting', 'completed', 'failed')"),
        nullable=False,
        default='pending',
        index=True
    )
    error_message = Column(Text)
    category_id = Column(Integer, ForeignKey('categories.id'), index=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    category = relationship("Category", back_populates="sources")
    extractions = relationship("Extraction", back_populates="source", cascade="all, delete-orphan")
    steckbrief = relationship("Steckbrief", back_populates="source", uselist=False, cascade="all, delete-orphan")
    jobs = relationship("JobQueue", back_populates="source", cascade="all, delete-orphan")


class Prompt(Base):
    """Extract/Validate-Prompt-Paare"""
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    internal_name = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    display_name_en = Column(String(200))  # English display name, used by the English site
    extract_prompt = Column(Text, nullable=False)
    validate_prompt = Column(Text, nullable=False)
    field_type = Column(String(50), default='text')
    field_group = Column(String(50), default='base', index=True)
    entity_type = Column(String(50))  # 'university', 'location', None
    required_confidence = Column(Float, default=0.6, nullable=False)
    max_retries = Column(Integer, default=3, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    
    # Translation configuration
    translatable = Column(Boolean, default=True, nullable=False)  # Should this field be translated?
    translation_context = Column(Text)  # Context description handed to the translator
    
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    category_associations = relationship("CategoryPrompt", back_populates="prompt", cascade="all, delete-orphan")
    extractions = relationship("Extraction", back_populates="prompt", cascade="all, delete-orphan")
    dependencies = relationship("PromptDependency", back_populates="prompt", foreign_keys="PromptDependency.prompt_id", cascade="all, delete-orphan")
    dependent_prompts = relationship("PromptDependency", back_populates="depends_on_prompt", foreign_keys="PromptDependency.depends_on_prompt_id")


class PromptDependency(Base):
    """Prompt dependencies. One level only: a prompt may depend on prompts, but those may not depend further."""
    __tablename__ = "prompt_dependencies"

    id = Column(Integer, primary_key=True)
    prompt_id = Column(Integer, ForeignKey('prompts.id', ondelete='CASCADE'), nullable=False)
    depends_on_prompt_id = Column(Integer, ForeignKey('prompts.id', ondelete='CASCADE'), nullable=False)
    context_key = Column(String(100), nullable=False)  # e.g. "institution"
    is_required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('prompt_id', 'depends_on_prompt_id', name='unique_prompt_dependency'),
    )

    # Relationships
    prompt = relationship("Prompt", back_populates="dependencies", foreign_keys=[prompt_id])
    depends_on_prompt = relationship("Prompt", back_populates="dependent_prompts", foreign_keys=[depends_on_prompt_id])


class Category(Base):
    """Categories with their field group configuration"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    internal_name = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    display_name_en = Column(String(200))  # English display name, used by the English site
    steckbrief_template = Column(Text, nullable=False)
    field_groups = Column(JSONB, default={})  # {"base": ["project_name", ...], "team": [...]}
    active_groups = Column(ARRAY(String), default=[])  # Which groups are shown in the profile
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    # Relationships
    sources = relationship("Source", back_populates="category")
    prompt_associations = relationship("CategoryPrompt", back_populates="category", cascade="all, delete-orphan")


class CategoryPrompt(Base):
    """Mapping between categories and prompts"""
    __tablename__ = "category_prompts"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey('categories.id', ondelete='CASCADE'), nullable=False, index=True)
    prompt_id = Column(Integer, ForeignKey('prompts.id', ondelete='CASCADE'), nullable=False)
    display_order = Column(Integer, default=100, nullable=False)

    __table_args__ = (
        UniqueConstraint('category_id', 'prompt_id', name='unique_category_prompt'),
    )

    # Relationships
    category = relationship("Category", back_populates="prompt_associations")
    prompt = relationship("Prompt", back_populates="category_associations")


class Extraction(Base):
    """Results of a prompt run"""
    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True)
    source_id = Column(PGUUID(as_uuid=True), ForeignKey('sources.id', ondelete='CASCADE'), nullable=False, index=True)
    prompt_id = Column(Integer, ForeignKey('prompts.id', ondelete='CASCADE'), nullable=False, index=True)

    # Phase 1: Extract
    raw_result = Column(Text)
    raw_confidence = Column(Float)
    extract_duration_ms = Column(Integer)

    # Phase 2: Validate
    validated_result = Column(Text)
    validation_quality = Column(
        String(20),
        CheckConstraint("validation_quality IN ('HIGH', 'MEDIUM', 'LOW', 'INSUFFICIENT')")
    )
    validation_score = Column(Float)
    validation_notes = Column(Text)
    validate_duration_ms = Column(Integer)

    # Translation stage
    validated_result_en = Column(Text)  # English translation of validated_result
    translation_status = Column(
        String(20),
        CheckConstraint("translation_status IN ('pending', 'translated', 'skipped', 'failed')"),
        default='pending'
    )
    translated_at = Column(DateTime(timezone=True))

    # Final
    final_confidence = Column(Float, index=True)
    is_manual_edit = Column(Boolean, default=False, nullable=False, index=True)
    edited_by = Column(String(100))

    # Entity link. ondelete='SET NULL' so that deleting an entity leaves the
    # extraction intact, merely unlinked, instead of cascading it away.
    linked_entity_id = Column(Integer, ForeignKey('entities.id', ondelete='SET NULL'), index=True)
    entity_confidence = Column(Float)

    extracted_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('source_id', 'prompt_id', name='unique_source_prompt_extraction'),
    )

    # Relationships
    source = relationship("Source", back_populates="extractions")
    prompt = relationship("Prompt", back_populates="extractions")
    linked_entity = relationship("Entity", back_populates="extractions")


class JobQueue(Base):
    """Job queue. Redis holds the live queue; this table is the durable fallback."""
    __tablename__ = "job_queue"

    id = Column(Integer, primary_key=True)
    job_type = Column(
        String(20),
        CheckConstraint("job_type IN ('crawl', 'extract', 'validate', 'normalize', 'generate', 'translate')"),
        nullable=False
    )
    source_id = Column(PGUUID(as_uuid=True), ForeignKey('sources.id', ondelete='CASCADE'), index=True)
    prompt_id = Column(Integer, ForeignKey('prompts.id', ondelete='SET NULL'))
    payload = Column(JSONB, default={})
    priority = Column(Integer, default=100, nullable=False)
    status = Column(
        String(20),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')"),
        default='pending',
        nullable=False,
        index=True
    )

    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    last_error = Column(Text)

    scheduled_at = Column(DateTime(timezone=True), default=func.now(), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    # Relationships
    source = relationship("Source", back_populates="jobs")


class Entity(Base):
    """Hochschulen, Orte, etc."""
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True)
    entity_type = Column(
        String(50),
        CheckConstraint("entity_type IN ('university', 'location')"),
        nullable=False,
        index=True
    )
    canonical_name = Column(String(500), nullable=False, index=True)
    entity_metadata = Column(JSONB, default={})  # Named entity_metadata because 'metadata' is reserved by SQLAlchemy
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('entity_type', 'canonical_name', name='unique_entity_type_name'),
    )

    # Relationships
    variants = relationship("EntityVariant", back_populates="entity", cascade="all, delete-orphan")
    extractions = relationship("Extraction", back_populates="linked_entity")
    normalizations = relationship("EntityNormalizationQueue", back_populates="llm_suggestion_entity")


class EntityVariant(Base):
    """Entity variants: synonyms and abbreviations"""
    __tablename__ = "entity_variants"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey('entities.id', ondelete='CASCADE'), nullable=False, index=True)
    variant_name = Column(String(500), unique=True, nullable=False, index=True)
    is_auto_detected = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    # Relationships
    entity = relationship("Entity", back_populates="variants")


class EntityNormalizationQueue(Base):
    """Entity-Normalisierungs-Queue"""
    __tablename__ = "entity_normalization_queue"

    id = Column(Integer, primary_key=True)
    extraction_id = Column(Integer, ForeignKey('extractions.id', ondelete='CASCADE'), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)
    entity_type = Column(String(50), nullable=False)

    # ondelete='SET NULL' so that an entity can be deleted while review items
    # still point at it. The queue entry survives without its suggestion.
    llm_suggestion_id = Column(Integer, ForeignKey('entities.id', ondelete='SET NULL'))
    llm_confidence = Column(Float)

    status = Column(
        String(20),
        CheckConstraint("status IN ('pending', 'reviewed', 'ignored')"),
        default='pending',
        nullable=False,
        index=True
    )
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    # Relationships
    extraction = relationship("Extraction")
    llm_suggestion_entity = relationship("Entity", back_populates="normalizations")


class Steckbrief(Base):
    """Generierte Ausgaben"""
    __tablename__ = "steckbriefe"

    id = Column(Integer, primary_key=True)
    source_id = Column(PGUUID(as_uuid=True), ForeignKey('sources.id', ondelete='CASCADE'), unique=True, nullable=False)
    markdown_content = Column(Text)
    html_content = Column(Text)
    generated_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    published = Column(Boolean, default=False, nullable=False, index=True)
    published_at = Column(DateTime(timezone=True))

    # Relationships
    source = relationship("Source", back_populates="steckbrief")
    translations = relationship("SteckbriefTranslation", back_populates="steckbrief", cascade="all, delete-orphan")


class SteckbriefTranslation(Base):
    """Translations of generated profiles"""
    __tablename__ = "steckbrief_translations"

    id = Column(Integer, primary_key=True)
    steckbrief_id = Column(Integer, ForeignKey('steckbriefe.id', ondelete='CASCADE'), nullable=False, index=True)
    language = Column(String(5), nullable=False, index=True)  # 'en', 'fr', etc.
    markdown_content = Column(Text, nullable=False)
    
    # Hash of the German original, used to invalidate the cache
    source_hash = Column(String(64), nullable=False)
    
    translated_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('steckbrief_id', 'language', name='unique_steckbrief_language'),
    )

    # Relationships
    steckbrief = relationship("Steckbrief", back_populates="translations")


class CircuitBreakerState(Base):
    """Circuit breaker state, kept for monitoring only"""
    __tablename__ = "circuit_breaker_state"

    id = Column(Integer, primary_key=True)
    service_name = Column(String(100), unique=True, nullable=False)
    state = Column(
        String(20),
        CheckConstraint("state IN ('CLOSED', 'OPEN', 'HALF_OPEN')"),
        nullable=False
    )
    failure_count = Column(Integer, default=0, nullable=False)
    last_failure_at = Column(DateTime(timezone=True))
    opened_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

class User(Base):
    """
    Operator account for the admin interface and the admin API.

    Password hashes are produced by app.auth; this model deliberately stores
    only the encoded hash string, so the hashing parameters can change without
    a schema migration.

    External identity providers (Shibboleth, LDAP, OIDC) are out of scope for
    now. When they arrive, password_hash becomes nullable and an external
    subject identifier is added alongside it; the role column is unaffected.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(
        String(20),
        CheckConstraint("role IN ('viewer', 'editor', 'admin')"),
        nullable=False,
        default=Role.VIEWER.value,
    )
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    last_login_at = Column(DateTime(timezone=True))

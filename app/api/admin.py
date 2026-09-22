# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Admin REST API.

Full CRUD over sources, prompts, categories, entities and profiles, plus the
maintenance operations. Routes that change configuration or destroy data
require the admin role; the rest require editor.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import ConfigDict, BaseModel, Field, field_validator
from sqlalchemy import select, func, update as sql_update, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.auth import require_admin
from app.database import get_async_session
from app.models import (
    Source, Prompt, Category, Extraction, Entity, EntityVariant,
    EntityNormalizationQueue, Steckbrief, JobPriority, JobType
)
from app.repositories import (
    CategoryRepository,
    EntityRepository,
    ExtractionRepository,
    PromptRepository,
    SourceRepository,
    SteckbriefRepository,
)
from app.services.job_queue import get_job_queue
from app.services.static_site_generator import StaticSiteGenerator

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()


# ========================================
# PYDANTIC MODELS
# ========================================

class SourceCreate(BaseModel):
    """Create source request"""
    url: str = Field(..., description="URL to crawl")
    category_id: int = Field(..., description="Category ID")
    additional_urls: Optional[List[str]] = Field(default=None, description="Additional URLs for multi-page")
    rate_limit: Optional[float] = Field(default=1.0, description="Requests per second")
    
    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize URL"""
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        
        v = v.strip()
        
        # Add https:// if no protocol specified
        if not v.startswith('http://') and not v.startswith('https://'):
            v = 'https://' + v
        
        # Basic URL validation
        from urllib.parse import urlparse
        parsed = urlparse(v)
        if not parsed.netloc:
            raise ValueError("Invalid URL: missing domain")
        
        return v
    
    @field_validator('additional_urls')
    @classmethod
    def validate_additional_urls(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate and normalize additional URLs"""
        if not v:
            return v
        
        from urllib.parse import urlparse
        validated = []
        for url in v:
            if not url or not url.strip():
                continue
            url = url.strip()
            if not url.startswith('http://') and not url.startswith('https://'):
                url = 'https://' + url
            parsed = urlparse(url)
            if parsed.netloc:
                validated.append(url)
        return validated if validated else None


class SourceUpdate(BaseModel):
    """Update source request"""
    url: Optional[str] = None
    category_id: Optional[int] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


class SourceResponse(BaseModel):
    """Source response"""
    id: UUID
    url: str
    status: str
    markdown_size: Optional[int]
    pages_crawled: Optional[int]
    crawled_at: Optional[datetime]
    category_id: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PromptCreate(BaseModel):
    """Create prompt request"""
    internal_name: str = Field(..., max_length=100)
    display_name: str = Field(..., max_length=200)
    extract_prompt: str = Field(..., description="Phase 1: Extract prompt")
    validate_prompt: str = Field(..., description="Phase 2: Validate prompt")
    field_type: str = Field(default="text")
    field_group: str = Field(default="base")
    entity_type: Optional[str] = Field(default=None, description="university, location, or None")
    required_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    max_retries: int = Field(default=3, ge=1, le=10)
    is_active: bool = Field(default=True)


class PromptUpdate(BaseModel):
    """Update prompt request"""
    display_name: Optional[str] = Field(None, max_length=200)
    extract_prompt: Optional[str] = None
    validate_prompt: Optional[str] = None
    field_type: Optional[str] = None
    field_group: Optional[str] = None
    entity_type: Optional[str] = None
    required_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_retries: Optional[int] = Field(None, ge=1, le=10)
    is_active: Optional[bool] = None


class PromptResponse(BaseModel):
    """Prompt response"""
    id: int
    internal_name: str
    display_name: str
    extract_prompt: str
    validate_prompt: str
    field_type: str
    field_group: str
    entity_type: Optional[str]
    required_confidence: float
    max_retries: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PromptDependencyCreate(BaseModel):
    """Add dependency to prompt"""
    depends_on_prompt_id: int = Field(..., description="ID of prompt this depends on")
    context_key: str = Field(..., max_length=100, description="Variable name for context")
    is_required: bool = Field(default=True)


class CategoryCreate(BaseModel):
    """Create category request"""
    internal_name: str = Field(..., max_length=100, description="Internal identifier (lowercase, no spaces)")
    display_name: str = Field(..., max_length=200, description="Public display name")
    steckbrief_template: str = Field(..., description="Markdown template with placeholders")
    field_groups: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Field groups mapping: {'base': ['project_name', ...], 'team': [...]}"
    )
    active_groups: List[str] = Field(
        default_factory=list,
        description="Which field groups to display in Steckbrief"
    )
    is_active: bool = Field(default=True)


class CategoryUpdate(BaseModel):
    """Update category request"""
    display_name: Optional[str] = Field(None, max_length=200)
    steckbrief_template: Optional[str] = None
    field_groups: Optional[Dict[str, List[str]]] = None
    active_groups: Optional[List[str]] = None
    is_active: Optional[bool] = None


class CategoryResponse(BaseModel):
    """Category response"""
    id: int
    internal_name: str
    display_name: str
    steckbrief_template: str
    field_groups: Dict[str, List[str]]
    active_groups: List[str]
    is_active: bool
    created_at: datetime
    source_count: Optional[int] = None
    prompt_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CategoryPromptAssignment(BaseModel):
    """Assign prompt to category"""
    prompt_id: int = Field(..., description="Prompt ID to assign")
    display_order: int = Field(default=100, description="Display order in UI")


class ExtractionUpdate(BaseModel):
    """Update extraction (inline edit)"""
    validated_result: str = Field(..., description="New validated result")
    edited_by: Optional[str] = Field(default="admin")


class ExtractionResponse(BaseModel):
    """Extraction response"""
    id: int
    source_id: UUID
    prompt_id: int
    raw_result: Optional[str]
    raw_confidence: Optional[float]
    validated_result: Optional[str]
    validation_quality: Optional[str]
    validation_score: Optional[float]
    validation_notes: Optional[str]
    final_confidence: Optional[float]
    is_manual_edit: bool
    edited_by: Optional[str]
    linked_entity_id: Optional[int]
    extract_duration_ms: Optional[int]
    validate_duration_ms: Optional[int]
    extracted_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobQueueStatus(BaseModel):
    """Job queue status"""
    pending: int
    running: int
    completed: int
    failed: int
    total: int


class EntityCreate(BaseModel):
    """Create entity"""
    entity_type: str = Field(..., description="university or location")
    canonical_name: str = Field(..., max_length=500)
    metadata: Dict = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    """Update entity"""
    canonical_name: Optional[str] = Field(None, max_length=500)
    metadata: Optional[Dict] = None


class EntityVariantCreate(BaseModel):
    """Add entity variant"""
    variant_name: str = Field(..., max_length=500)
    is_auto_detected: bool = Field(default=False)


class SteckbriefUpdate(BaseModel):
    """Update steckbrief"""
    markdown_content: Optional[str] = None
    html_content: Optional[str] = None


class SteckbriefResponse(BaseModel):
    """Profile response"""
    id: int
    source_id: UUID
    markdown_content: str
    html_content: Optional[str]
    generated_at: datetime
    published: bool
    published_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ========================================
# CATEGORY MANAGEMENT ENDPOINTS
# ========================================

@router.post("/categories", response_model=CategoryResponse, dependencies=[Depends(require_admin)])
async def create_category(
    category_data: CategoryCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Create new category"""
    category_repo = CategoryRepository(Category, session)

    try:
        existing = await category_repo.get_by_internal_name(category_data.internal_name)
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Category with internal_name '{category_data.internal_name}' already exists"
            )

        category = Category(**category_data.model_dump())
        category = await category_repo.create(category)

        logger.info(
            "category_created",
            category_id=category.id,
            internal_name=category.internal_name
        )

        response = CategoryResponse.model_validate(category)
        response.source_count = 0
        response.prompt_count = 0

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_category_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(
    active_only: bool = Query(False, description="Only active categories"),
    include_counts: bool = Query(True, description="Include source and prompt counts"),
    session: AsyncSession = Depends(get_async_session)
):
    """List all categories"""
    category_repo = CategoryRepository(Category, session)
    source_repo = SourceRepository(Source, session)

    categories = await category_repo.list_all(active_only=active_only)

    result = []
    for category in categories:
        response = CategoryResponse.model_validate(category)

        if include_counts:
            response.source_count = await source_repo.count_by_category(category.id)

            from app.models import CategoryPrompt
            count_result = await session.execute(
                select(func.count()).select_from(CategoryPrompt).where(
                    CategoryPrompt.category_id == category.id
                )
            )
            response.prompt_count = count_result.scalar()

        result.append(response)

    return result


@router.get("/categories/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Get single category with details"""
    category_repo = CategoryRepository(Category, session)
    source_repo = SourceRepository(Source, session)

    category = await category_repo.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    response = CategoryResponse.model_validate(category)
    response.source_count = await source_repo.count_by_category(category.id)

    from app.models import CategoryPrompt
    count_result = await session.execute(
        select(func.count()).select_from(CategoryPrompt).where(
            CategoryPrompt.category_id == category.id
        )
    )
    response.prompt_count = count_result.scalar()

    return response


@router.put("/categories/{category_id}", response_model=CategoryResponse, dependencies=[Depends(require_admin)])
async def update_category(
    category_id: int,
    update_data: CategoryUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update category"""
    category_repo = CategoryRepository(Category, session)

    category = await category_repo.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(category, field, value)

        await session.commit()
        await session.refresh(category)

        logger.info(
            "category_updated",
            category_id=category_id,
            updated_fields=list(update_dict.keys())
        )

        response = CategoryResponse.model_validate(category)
        return response

    except Exception as e:
        logger.error("update_category_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/categories/{category_id}", dependencies=[Depends(require_admin)])
async def delete_category(
    category_id: int,
    force: bool = Query(False, description="Force delete even if sources exist"),
    session: AsyncSession = Depends(get_async_session)
):
    """Delete category (or deactivate if sources exist and force=False)"""
    category_repo = CategoryRepository(Category, session)
    source_repo = SourceRepository(Source, session)

    category = await category_repo.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    source_count = await source_repo.count_by_category(category_id)

    if source_count > 0 and not force:
        category.is_active = False
        await session.commit()

        logger.info(
            "category_deactivated",
            category_id=category_id,
            source_count=source_count
        )

        return {
            "message": "Category deactivated (has sources)",
            "category_id": category_id,
            "source_count": source_count,
            "action": "deactivated"
        }

    try:
        await category_repo.delete_obj(category)
        await session.commit()

        logger.info(
            "category_deleted",
            category_id=category_id,
            forced=force
        )

        return {
            "message": "Category deleted",
            "category_id": category_id,
            "action": "deleted"
        }

    except Exception as e:
        logger.error("delete_category_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/{category_id}/prompts", response_model=List[PromptResponse])
async def get_category_prompts(
    category_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Get all prompts assigned to category"""
    prompt_repo = PromptRepository(Prompt, session)
    category_repo = CategoryRepository(Category, session)

    category = await category_repo.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    prompts = await prompt_repo.get_by_category(category_id, active_only=False)

    return [PromptResponse.model_validate(p) for p in prompts]


@router.post("/categories/{category_id}/prompts", dependencies=[Depends(require_admin)])
async def assign_prompt_to_category(
    category_id: int,
    assignment: CategoryPromptAssignment,
    session: AsyncSession = Depends(get_async_session)
):
    """Assign prompt to category"""
    from app.models import CategoryPrompt

    category_repo = CategoryRepository(Category, session)
    prompt_repo = PromptRepository(Prompt, session)

    category = await category_repo.get(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    prompt = await prompt_repo.get(assignment.prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    try:
        result = await session.execute(
            select(CategoryPrompt).where(
                CategoryPrompt.category_id == category_id,
                CategoryPrompt.prompt_id == assignment.prompt_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=400,
                detail="Prompt already assigned to this category"
            )

        cat_prompt = CategoryPrompt(
            category_id=category_id,
            prompt_id=assignment.prompt_id,
            display_order=assignment.display_order
        )
        session.add(cat_prompt)
        await session.commit()

        logger.info(
            "prompt_assigned_to_category",
            category_id=category_id,
            prompt_id=assignment.prompt_id
        )

        return {
            "message": "Prompt assigned to category",
            "category_id": category_id,
            "prompt_id": assignment.prompt_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("assign_prompt_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/categories/{category_id}/prompts/{prompt_id}", dependencies=[Depends(require_admin)])
async def remove_prompt_from_category(
    category_id: int,
    prompt_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Remove prompt from category"""
    from app.models import CategoryPrompt
    from sqlalchemy import delete

    try:
        stmt = delete(CategoryPrompt).where(
            CategoryPrompt.category_id == category_id,
            CategoryPrompt.prompt_id == prompt_id
        )
        result = await session.execute(stmt)
        await session.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Assignment not found"
            )

        logger.info(
            "prompt_removed_from_category",
            category_id=category_id,
            prompt_id=prompt_id
        )

        return {
            "message": "Prompt removed from category",
            "category_id": category_id,
            "prompt_id": prompt_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("remove_prompt_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# SOURCE MANAGEMENT ENDPOINTS
# ========================================

@router.post("/sources", response_model=SourceResponse)
async def create_source(
    source_data: SourceCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Create new source and enqueue crawl job"""
    source_repo = SourceRepository(Source, session)
    job_queue = await get_job_queue()

    try:
        source = Source(
            url=source_data.url,
            category_id=source_data.category_id,
            status="pending"
        )
        source = await source_repo.create(source)

        # Build payload - only include non-None values for Redis serialization
        payload = {
            "url": source_data.url
        }

        if source_data.additional_urls is not None:
            payload["additional_urls"] = source_data.additional_urls

        if source_data.rate_limit is not None:
            payload["rate_limit"] = source_data.rate_limit
        else:
            payload["rate_limit"] = 1.0

        await job_queue.enqueue(
            job_type=JobType.CRAWL,
            source_id=str(source.id),  # Convert UUID to string for Redis serialization
            priority=JobPriority.CRAWL,
            payload=payload
        )

        logger.info(
            "source_created",
            source_id=str(source.id),
            url=source_data.url,
            category_id=source_data.category_id
        )

        return SourceResponse.model_validate(source)

    except Exception as e:
        logger.error("create_source_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources", response_model=List[SourceResponse])
async def list_sources(
    status: Optional[str] = Query(None, description="Filter by status"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session)
):
    """List sources with filtering"""
    source_repo = SourceRepository(Source, session)

    sources = await source_repo.get_by_status_and_category(
        status=status,
        category_id=category_id,
        skip=offset,
        limit=limit
    )

    return [SourceResponse.model_validate(s) for s in sources]


@router.get("/sources/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """Get single source"""
    source_repo = SourceRepository(Source, session)

    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    return SourceResponse.model_validate(source)


@router.put("/sources/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    update_data: SourceUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update source"""
    source_repo = SourceRepository(Source, session)

    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(source, field, value)

        await session.commit()
        await session.refresh(source)

        logger.info(
            "source_updated",
            source_id=str(source_id),
            updated_fields=list(update_dict.keys())
        )

        return SourceResponse.model_validate(source)

    except Exception as e:
        logger.error("update_source_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{source_id}", dependencies=[Depends(require_admin)])
async def delete_source(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Delete source (CASCADE to extractions, steckbrief, jobs)
    """
    source_repo = SourceRepository(Source, session)

    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    try:
        extraction_repo = ExtractionRepository(Extraction, session)
        extractions = await extraction_repo.get_by_source(source_id)
        extraction_count = len(extractions)

        await source_repo.delete_obj(source)
        await session.commit()

        logger.info(
            "source_deleted",
            source_id=str(source_id),
            url=source.url,
            extractions_deleted=extraction_count
        )

        return {
            "message": "Source deleted (including extractions, steckbrief, jobs)",
            "source_id": str(source_id),
            "extractions_deleted": extraction_count
        }

    except Exception as e:
        logger.error("delete_source_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/extractions", response_model=List[ExtractionResponse])
async def get_source_extractions(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """Get all extractions for a source"""
    extraction_repo = ExtractionRepository(Extraction, session)

    extractions = await extraction_repo.get_by_source(source_id)

    return [ExtractionResponse.model_validate(e) for e in extractions]


@router.get("/sources/{source_id}/markdown")
async def get_source_markdown(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """Get source markdown content"""
    source_repo = SourceRepository(Source, session)

    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if not source.markdown_content:
        raise HTTPException(status_code=404, detail="Markdown not yet generated")

    return {
        "source_id": str(source.id),
        "url": source.url,
        "markdown": source.markdown_content,
        "size": source.markdown_size,
        "pages_crawled": source.pages_crawled,
        "crawled_at": source.crawled_at
    }


@router.post("/sources/{source_id}/re-extract")
async def re_extract_source(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """Trigger re-extraction for a source"""
    source_repo = SourceRepository(Source, session)
    prompt_repo = PromptRepository(Prompt, session)
    job_queue = await get_job_queue()

    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if not source.markdown_content:
        raise HTTPException(status_code=400, detail="Source has no markdown yet")

    prompts = await prompt_repo.get_by_category(source.category_id)
    active_prompts = [p for p in prompts if p.is_active]

    if not active_prompts:
        raise HTTPException(status_code=400, detail="No active prompts for category")

    jobs_created = 0
    for prompt in active_prompts:
        await job_queue.enqueue(
            job_type=JobType.EXTRACT,
            source_id=str(source.id),  # Convert UUID to string for Redis serialization
            prompt_id=prompt.id,
            priority=JobPriority.EXTRACT_INDEPENDENT
        )
        jobs_created += 1

    # Move the source to 'extracting' so that it shows up as pending work
    source.status = 'extracting'
    await source_repo.update_obj(source)
    await session.commit()

    logger.info(
        "re_extraction_triggered",
        source_id=str(source_id),
        jobs_created=jobs_created,
        status_updated='extracting'
    )

    return {
        "source_id": str(source_id),
        "jobs_created": jobs_created,
        "message": "Re-extraction jobs enqueued",
        "status": "extracting"
    }


# ========================================
# PROMPT MANAGEMENT ENDPOINTS
# ========================================

@router.post("/prompts", response_model=PromptResponse, dependencies=[Depends(require_admin)])
async def create_prompt(
    prompt_data: PromptCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Create new prompt"""
    prompt_repo = PromptRepository(Prompt, session)

    try:
        prompt = Prompt(**prompt_data.model_dump())
        prompt = await prompt_repo.create(prompt)

        logger.info(
            "prompt_created",
            prompt_id=prompt.id,
            internal_name=prompt.internal_name
        )

        return PromptResponse.model_validate(prompt)

    except Exception as e:
        logger.error("create_prompt_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts", response_model=List[PromptResponse])
async def list_prompts(
    active_only: bool = Query(False, description="Only active prompts"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    session: AsyncSession = Depends(get_async_session)
):
    """List prompts"""
    prompt_repo = PromptRepository(Prompt, session)

    if category_id:
        prompts = await prompt_repo.get_by_category(category_id, active_only=active_only)
    else:
        prompts = await prompt_repo.list_all(active_only=active_only)

    return [PromptResponse.model_validate(p) for p in prompts]


@router.get("/prompts/{prompt_id}", response_model=PromptResponse)
async def get_prompt(
    prompt_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Get single prompt"""
    prompt_repo = PromptRepository(Prompt, session)

    prompt = await prompt_repo.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    return PromptResponse.model_validate(prompt)


@router.put("/prompts/{prompt_id}", response_model=PromptResponse, dependencies=[Depends(require_admin)])
async def update_prompt(
    prompt_id: int,
    update_data: PromptUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update prompt"""
    prompt_repo = PromptRepository(Prompt, session)

    prompt = await prompt_repo.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(prompt, field, value)

        await session.commit()
        await session.refresh(prompt)

        logger.info(
            "prompt_updated",
            prompt_id=prompt_id,
            updated_fields=list(update_dict.keys())
        )

        return PromptResponse.model_validate(prompt)

    except Exception as e:
        logger.error("update_prompt_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/prompts/{prompt_id}", dependencies=[Depends(require_admin)])
async def delete_prompt(
    prompt_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Delete prompt (NOT allowed if extractions exist)
    Dependencies are automatically removed
    """
    prompt_repo = PromptRepository(Prompt, session)
    extraction_repo = ExtractionRepository(Extraction, session)

    prompt = await prompt_repo.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    result = await session.execute(
        select(func.count()).select_from(Extraction).where(
            Extraction.prompt_id == prompt_id
        )
    )
    extraction_count = result.scalar()

    if extraction_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete prompt: {extraction_count} extractions exist. "
                   f"Consider deactivating the prompt instead (set is_active=false)."
        )

    try:
        await prompt_repo.delete_obj(prompt)
        await session.commit()

        logger.info(
            "prompt_deleted",
            prompt_id=prompt_id,
            internal_name=prompt.internal_name
        )

        return {
            "message": "Prompt deleted (including dependencies)",
            "prompt_id": prompt_id
        }

    except Exception as e:
        logger.error("delete_prompt_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/{prompt_id}/dependencies", dependencies=[Depends(require_admin)])
async def add_prompt_dependency(
    prompt_id: int,
    dependency: PromptDependencyCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Add dependency to prompt"""
    from app.models import PromptDependency

    prompt_repo = PromptRepository(Prompt, session)

    prompt = await prompt_repo.get(prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    depends_on = await prompt_repo.get(dependency.depends_on_prompt_id)
    if not depends_on:
        raise HTTPException(status_code=404, detail="Dependency prompt not found")

    dep = PromptDependency(
        prompt_id=prompt_id,
        depends_on_prompt_id=dependency.depends_on_prompt_id,
        context_key=dependency.context_key,
        is_required=dependency.is_required
    )
    session.add(dep)
    await session.commit()

    logger.info(
        "dependency_added",
        prompt_id=prompt_id,
        depends_on=dependency.depends_on_prompt_id,
        context_key=dependency.context_key
    )

    return {"message": "Dependency added"}


@router.delete("/prompts/{prompt_id}/dependencies/{dependency_id}", dependencies=[Depends(require_admin)])
async def remove_prompt_dependency(
    prompt_id: int,
    dependency_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Remove dependency from prompt"""
    from app.models import PromptDependency
    from sqlalchemy import delete

    try:
        stmt = delete(PromptDependency).where(
            PromptDependency.id == dependency_id,
            PromptDependency.prompt_id == prompt_id
        )
        result = await session.execute(stmt)
        await session.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Dependency not found"
            )

        logger.info(
            "dependency_removed",
            prompt_id=prompt_id,
            dependency_id=dependency_id
        )

        return {
            "message": "Dependency removed",
            "prompt_id": prompt_id,
            "dependency_id": dependency_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("remove_dependency_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# EXTRACTION MANAGEMENT ENDPOINTS
# ========================================

@router.put("/extractions/{extraction_id}", response_model=ExtractionResponse)
async def update_extraction(
    extraction_id: int,
    update_data: ExtractionUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update extraction (inline edit)"""
    extraction_repo = ExtractionRepository(Extraction, session)

    extraction = await extraction_repo.get(extraction_id)
    if not extraction:
        raise HTTPException(status_code=404, detail="Extraction not found")

    extraction.validated_result = update_data.validated_result
    extraction.is_manual_edit = True
    extraction.edited_by = update_data.edited_by
    extraction.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(extraction)

    logger.info(
        "extraction_updated",
        extraction_id=extraction_id,
        edited_by=update_data.edited_by
    )

    return ExtractionResponse.model_validate(extraction)


@router.get("/extractions/low-confidence", response_model=List[ExtractionResponse])
async def get_low_confidence_extractions(
    threshold: float = Query(0.7, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session)
):
    """Get extractions with low confidence (for review)"""
    extraction_repo = ExtractionRepository(Extraction, session)

    extractions = await extraction_repo.get_low_confidence(
        threshold=threshold,
        skip=0,
        limit=limit
    )

    return [ExtractionResponse.model_validate(e) for e in extractions]


# ========================================
# JOB QUEUE ENDPOINTS
# ========================================

@router.get("/jobs/queue", response_model=JobQueueStatus)
async def get_queue_status():
    """Get job queue status"""
    job_queue = await get_job_queue()

    try:
        pending = await job_queue.get_queue_size()
    except:
        pending = 0

    return JobQueueStatus(
        pending=pending,
        running=0,
        completed=0,
        failed=0,
        total=pending
    )


# ========================================
# ENTITY MANAGEMENT ENDPOINTS
# ========================================

@router.post("/entities", dependencies=[Depends(require_admin)])
async def create_entity(
    entity_data: EntityCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Create new entity"""
    entity_repo = EntityRepository(Entity, session)

    try:
        entity = Entity(
            entity_type=entity_data.entity_type,
            canonical_name=entity_data.canonical_name,
            entity_metadata=entity_data.metadata
        )
        entity = await entity_repo.create(entity)

        logger.info(
            "entity_created",
            entity_id=entity.id,
            entity_type=entity.entity_type,
            canonical_name=entity.canonical_name
        )

        return {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "metadata": entity.entity_metadata
        }

    except Exception as e:
        logger.error("create_entity_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities")
async def list_entities(
    entity_type: Optional[str] = Query(None, description="Filter by type"),
    session: AsyncSession = Depends(get_async_session)
):
    """List entities"""
    entity_repo = EntityRepository(Entity, session)

    if entity_type:
        entities = await entity_repo.get_by_type(entity_type)
    else:
        entities = await entity_repo.list_all()

    return [
        {
            "id": e.id,
            "entity_type": e.entity_type,
            "canonical_name": e.canonical_name,
            "metadata": e.entity_metadata,
            "variants": [v.variant_name for v in e.variants]
        }
        for e in entities
    ]


@router.put("/entities/{entity_id}", dependencies=[Depends(require_admin)])
async def update_entity(
    entity_id: int,
    update_data: EntityUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update entity"""
    entity_repo = EntityRepository(Entity, session)

    entity = await entity_repo.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)

        if 'metadata' in update_dict:
            entity.entity_metadata = update_dict.pop('metadata')

        for field, value in update_dict.items():
            setattr(entity, field, value)

        await session.commit()
        await session.refresh(entity)

        logger.info(
            "entity_updated",
            entity_id=entity_id,
            updated_fields=list(update_data.model_dump(exclude_unset=True).keys())
        )

        return {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "metadata": entity.entity_metadata
        }

    except Exception as e:
        logger.error("update_entity_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/entities/{entity_id}", dependencies=[Depends(require_admin)])
async def delete_entity(
    entity_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Delete entity (CASCADE to variants, NULL in extractions and normalization queue)
    """
    entity_repo = EntityRepository(Entity, session)

    entity = await entity_repo.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    try:
        variant_count = len(entity.variants)

        result = await session.execute(
            select(func.count()).select_from(Extraction).where(
                Extraction.linked_entity_id == entity_id
            )
        )
        extraction_count = result.scalar()

        result = await session.execute(
            select(func.count()).select_from(EntityNormalizationQueue).where(
                EntityNormalizationQueue.llm_suggestion_id == entity_id
            )
        )
        normalization_count = result.scalar()

        if normalization_count > 0:
            await session.execute(
                sql_update(EntityNormalizationQueue)
                .where(EntityNormalizationQueue.llm_suggestion_id == entity_id)
                .values(llm_suggestion_id=None, llm_confidence=None)
            )
            await session.flush()

        await entity_repo.delete_obj(entity)
        await session.commit()

        logger.info(
            "entity_deleted",
            entity_id=entity_id,
            canonical_name=entity.canonical_name,
            variants_deleted=variant_count,
            extractions_unlinked=extraction_count,
            normalizations_unlinked=normalization_count
        )

        return {
            "message": "Entity deleted",
            "entity_id": entity_id,
            "variants_deleted": variant_count,
            "extractions_unlinked": extraction_count,
            "normalizations_unlinked": normalization_count
        }

    except Exception as e:
        logger.error("delete_entity_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities/{entity_id}/variants", dependencies=[Depends(require_admin)])
async def add_entity_variant(
    entity_id: int,
    variant_data: EntityVariantCreate,
    session: AsyncSession = Depends(get_async_session)
):
    """Add variant to entity"""
    from sqlalchemy.exc import IntegrityError
    
    entity_repo = EntityRepository(Entity, session)

    entity = await entity_repo.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Does this variant already exist?
    existing = await session.execute(
        select(EntityVariant).where(
            EntityVariant.variant_name == variant_data.variant_name
        )
    )
    existing_variant = existing.scalar_one_or_none()
    
    if existing_variant:
        # Find the entity this variant belongs to
        existing_entity = await entity_repo.get(existing_variant.entity_id)
        existing_name = existing_entity.canonical_name if existing_entity else "Unbekannt"
        
        raise HTTPException(
            status_code=409,  # Conflict
            detail=f"Variante '{variant_data.variant_name}' existiert bereits für: {existing_name}"
        )

    try:
        await entity_repo.add_variant(
            entity_id=entity_id,
            variant_name=variant_data.variant_name,
            is_auto_detected=variant_data.is_auto_detected
        )
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Variante '{variant_data.variant_name}' existiert bereits"
        )

    logger.info(
        "entity_variant_added",
        entity_id=entity_id,
        variant_name=variant_data.variant_name
    )

    return {"message": "Variant added"}


@router.delete("/entities/{entity_id}/variants/{variant_id}", dependencies=[Depends(require_admin)])
async def delete_entity_variant(
    entity_id: int,
    variant_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Delete entity variant"""
    from sqlalchemy import delete

    try:
        entity_repo = EntityRepository(Entity, session)
        entity = await entity_repo.get(entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        stmt = delete(EntityVariant).where(
            EntityVariant.id == variant_id,
            EntityVariant.entity_id == entity_id
        )
        result = await session.execute(stmt)
        await session.commit()

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Variant not found"
            )

        logger.info(
            "entity_variant_deleted",
            entity_id=entity_id,
            variant_id=variant_id
        )

        return {
            "message": "Variant deleted",
            "entity_id": entity_id,
            "variant_id": variant_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_variant_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities/auto-link", dependencies=[Depends(require_admin)])
async def auto_link_entities(
    entity_type: str = Query("university", description="Entity type to link"),
    dry_run: bool = Query(False, description="Preview without making changes"),
    use_raw_result: bool = Query(True, description="Also check raw_result if validated_result is empty"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Link entities automatically, by exact match.

    Walks every unlinked extraction and matches it against the known entities
    and their variants.

    Args:
        entity_type: type of entity ('university' or 'location')
        dry_run: if True, nothing is written
        use_raw_result: also consider raw_result when validated_result is empty

    Returns:
        Statistics on what was found and linked
    """
    from sqlalchemy.orm import selectinload
    
    try:
        # 1. Load every entity together with its variants
        entity_result = await session.execute(
            select(Entity)
            .where(Entity.entity_type == entity_type)
            .options(selectinload(Entity.variants))
        )
        entities = list(entity_result.scalars().all())
        
        if not entities:
            return {
                "success": True,
                "message": f"Keine Entities vom Typ '{entity_type}' vorhanden",
                "stats": {
                    "entities_available": 0,
                    "extractions_checked": 0,
                    "linked": 0,
                    "already_linked": 0,
                    "no_match": 0
                },
                "debug": {
                    "hint": "Entities mit dem Skript create_german_universities.py anlegen"
                }
            }
        
        # 2. Build the lookup dictionary (lowercase name -> entity)
        lookup = {}
        for entity in entities:
            # Canonical name
            canonical_lower = entity.canonical_name.lower().strip()
            lookup[canonical_lower] = entity
            
            # Variants
            for variant in entity.variants:
                variant_lower = variant.variant_name.lower().strip()
                lookup[variant_lower] = entity
        
        logger.info(
            "entity_lookup_built",
            entity_type=entity_type,
            entities=len(entities),
            lookup_entries=len(lookup)
        )
        
        # 3. Find the prompts that carry an entity_type
        prompt_result = await session.execute(
            select(Prompt).where(Prompt.entity_type == entity_type)
        )
        entity_prompts = list(prompt_result.scalars().all())
        prompt_ids = [p.id for p in entity_prompts]
        
        if not prompt_ids:
            # Fallback: prompts whose name mentions an institution
            logger.warning("no_prompts_with_entity_type", entity_type=entity_type)
            
            fallback_result = await session.execute(
                select(Prompt).where(
                    or_(
                        Prompt.internal_name.ilike('%institution%'),
                        Prompt.internal_name.ilike('%hochschule%'),
                        Prompt.internal_name.ilike('%university%'),
                        Prompt.internal_name.ilike('%universitaet%'),
                    )
                )
            )
            entity_prompts = list(fallback_result.scalars().all())
            prompt_ids = [p.id for p in entity_prompts]
            
            logger.info(
                "using_fallback_prompts",
                prompts=[p.internal_name for p in entity_prompts]
            )
        
        if not prompt_ids:
            return {
                "success": True,
                "message": f"Keine Prompts für Entity-Typ '{entity_type}' gefunden",
                "stats": {
                    "entities_available": len(entities),
                    "variants_available": len(lookup) - len(entities),
                    "extractions_checked": 0,
                    "linked": 0
                },
                "debug": {
                    "hint": "Prompts müssen 'entity_type: university' in der YAML haben und Kategorien neu geladen werden",
                    "prompts_found": 0
                }
            }
        
        # 4. Load the extractions, with or without a validated_result
        extraction_query = select(Extraction).where(
            Extraction.prompt_id.in_(prompt_ids)
        ).options(
            selectinload(Extraction.prompt),
            selectinload(Extraction.source)
        )
        
        extraction_result = await session.execute(extraction_query)
        extractions = list(extraction_result.scalars().unique().all())
        
        logger.info(
            "extractions_loaded",
            count=len(extractions),
            prompt_ids=prompt_ids
        )
        
        # 5. Run the matching
        stats = {
            "entities_available": len(entities),
            "variants_available": len(lookup) - len(entities),
            "prompts_checked": len(prompt_ids),
            "extractions_checked": len(extractions),
            "linked": 0,
            "already_linked": 0,
            "no_match": 0,
            "empty_value": 0
        }
        
        linked_details = []
        no_match_details = []
        
        for ext in extractions:
            # Already linked?
            if ext.linked_entity_id:
                stats["already_linked"] += 1
                continue
            
            # Take the extracted text: validated_result, or raw_result as a fallback
            raw_text = ext.validated_result
            if not raw_text and use_raw_result:
                raw_text = ext.raw_result
            
            if not raw_text or not raw_text.strip():
                stats["empty_value"] += 1
                continue
            
            raw_text = raw_text.strip()
            normalized = raw_text.lower().strip()
            
            # Exact matching only. Fuzzy matching would link the wrong institution
            # often enough that every link would need reviewing anyway.
            matched_entity = lookup.get(normalized)
            
            if matched_entity:
                stats["linked"] += 1
                linked_details.append({
                    "extraction_id": ext.id,
                    "raw_text": raw_text[:100],
                    "matched_entity": matched_entity.canonical_name,
                    "entity_id": matched_entity.id
                })
                
                if not dry_run:
                    ext.linked_entity_id = matched_entity.id
                    ext.entity_confidence = 1.0  # Exakter Match
            else:
                stats["no_match"] += 1
                no_match_details.append({
                    "extraction_id": ext.id,
                    "raw_text": raw_text[:100],
                    "normalized": normalized[:100],
                    "source_id": str(ext.source_id) if ext.source_id else None
                })
        
        if not dry_run:
            await session.commit()
            logger.info(
                "entity_auto_link_completed",
                entity_type=entity_type,
                linked=stats["linked"],
                no_match=stats["no_match"]
            )
        
        return {
            "success": True,
            "dry_run": dry_run,
            "message": f"{'[DRY RUN] ' if dry_run else ''}{stats['linked']} Verknüpfungen {'gefunden' if dry_run else 'erstellt'}",
            "stats": stats,
            "linked": linked_details[:20],
            "no_match": no_match_details[:20] if len(no_match_details) <= 20 else no_match_details[:10] + [{"...": f"{len(no_match_details) - 10} weitere"}],
            "debug": {
                "prompts_used": [p.internal_name for p in entity_prompts],
                "sample_lookup_keys": list(lookup.keys())[:10]
            }
        }
        
    except Exception as e:
        logger.error("entity_auto_link_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/link-stats")
async def get_entity_link_stats(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Statistics on entity links.

    Returns:
        Counts of linked and unlinked extractions
    """
    try:
        # Extractions belonging to prompts with an entity_type
        total_result = await session.execute(
            select(func.count())
            .select_from(Extraction)
            .join(Prompt)
            .where(
                Prompt.entity_type.is_not(None),
                Extraction.validated_result.is_not(None)
            )
        )
        total = total_result.scalar() or 0
        
        # Of those, the linked ones
        linked_result = await session.execute(
            select(func.count())
            .select_from(Extraction)
            .join(Prompt)
            .where(
                Prompt.entity_type.is_not(None),
                Extraction.validated_result.is_not(None),
                Extraction.linked_entity_id.is_not(None)
            )
        )
        linked = linked_result.scalar() or 0
        
        # Entities pro Typ
        entity_stats_result = await session.execute(
            select(
                Entity.entity_type,
                func.count(Entity.id).label('count')
            )
            .group_by(Entity.entity_type)
        )
        entity_stats = {row[0]: row[1] for row in entity_stats_result.fetchall()}
        
        # Variants
        variant_count_result = await session.execute(
            select(func.count()).select_from(EntityVariant)
        )
        variant_count = variant_count_result.scalar() or 0
        
        return {
            "extractions": {
                "total_with_entity_type": total,
                "linked": linked,
                "unlinked": total - linked,
                "link_rate": f"{(linked/total*100):.1f}%" if total > 0 else "0%"
            },
            "entities": entity_stats,
            "variants": variant_count
        }
        
    except Exception as e:
        logger.error("entity_link_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/normalization-queue")
async def get_normalization_queue(
    status: str = Query("pending", description="pending, reviewed, or ignored"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session)
):
    """Get entity normalization review queue"""
    entity_repo = EntityRepository(Entity, session)

    queue_items = await entity_repo.get_normalization_queue(
        status=status,
        limit=limit
    )

    return [
        {
            "id": item.id,
            "extraction_id": item.extraction_id,
            "raw_text": item.raw_text,
            "entity_type": item.entity_type,
            "llm_suggestion": {
                "entity_id": item.llm_suggestion_id,
                "canonical_name": item.llm_suggestion_entity.canonical_name if item.llm_suggestion_entity else None,
                "confidence": item.llm_confidence
            } if item.llm_suggestion_id else None,
            "status": item.status,
            "created_at": item.created_at
        }
        for item in queue_items
    ]


@router.post("/entities/normalization-queue/{item_id}/review")
async def review_normalization(
    item_id: int,
    action: str = Query(..., description="confirm, reject, or ignore"),
    entity_id: Optional[int] = Query(None, description="Entity ID if confirming"),
    reviewed_by: str = Query("admin"),
    session: AsyncSession = Depends(get_async_session)
):
    """Review entity normalization"""
    extraction_repo = ExtractionRepository(Extraction, session)

    result = await session.execute(
        select(EntityNormalizationQueue).where(EntityNormalizationQueue.id == item_id)
    )
    queue_item = result.scalar_one_or_none()

    if not queue_item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if action == "confirm":
        if not entity_id:
            raise HTTPException(status_code=400, detail="entity_id required for confirm")

        extraction = await extraction_repo.get(queue_item.extraction_id)
        if extraction:
            extraction.linked_entity_id = entity_id
            extraction.entity_confidence = queue_item.llm_confidence or 1.0
            await session.commit()

        queue_item.status = "reviewed"
        queue_item.reviewed_by = reviewed_by
        queue_item.reviewed_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info(
            "normalization_confirmed",
            item_id=item_id,
            extraction_id=queue_item.extraction_id,
            entity_id=entity_id
        )

    elif action == "reject":
        queue_item.status = "ignored"
        queue_item.reviewed_by = reviewed_by
        queue_item.reviewed_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info("normalization_rejected", item_id=item_id)

    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    return {"message": f"Normalization {action}ed"}


# ========================================
# STECKBRIEF MANAGEMENT ENDPOINTS
# ========================================

@router.get("/steckbriefe")
async def list_steckbriefe(
    published_only: bool = Query(False, description="Only published steckbriefe"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session)
):
    """List steckbriefe"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    if published_only:
        steckbriefe = await steckbrief_repo.get_published(skip=offset, limit=limit)
    else:
        steckbriefe = await steckbrief_repo.get_all(skip=offset, limit=limit)

    return [
        {
            "id": s.id,
            "source_id": str(s.source_id),
            "published": s.published,
            "published_at": s.published_at,
            "generated_at": s.generated_at
        }
        for s in steckbriefe
    ]


@router.get("/steckbriefe/{steckbrief_id}", response_model=SteckbriefResponse)
async def get_steckbrief(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Get steckbrief by ID"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")

    return SteckbriefResponse.model_validate(steckbrief)


@router.put("/steckbriefe/{steckbrief_id}", response_model=SteckbriefResponse)
async def update_steckbrief(
    steckbrief_id: int,
    update_data: SteckbriefUpdate,
    session: AsyncSession = Depends(get_async_session)
):
    """Update steckbrief"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")

    try:
        update_dict = update_data.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(steckbrief, field, value)

        await session.commit()
        await session.refresh(steckbrief)

        logger.info(
            "steckbrief_updated",
            steckbrief_id=steckbrief_id,
            updated_fields=list(update_dict.keys())
        )

        return SteckbriefResponse.model_validate(steckbrief)

    except Exception as e:
        logger.error("update_steckbrief_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/steckbriefe/{steckbrief_id}", dependencies=[Depends(require_admin)])
async def delete_steckbrief(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Delete steckbrief"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")

    try:
        await steckbrief_repo.delete_obj(steckbrief)
        await session.commit()

        logger.info(
            "steckbrief_deleted",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return {
            "message": "Steckbrief deleted",
            "steckbrief_id": steckbrief_id
        }

    except Exception as e:
        logger.error("delete_steckbrief_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/steckbriefe/{steckbrief_id}/publish")
async def publish_steckbrief(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Publish steckbrief"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")

    try:
        await steckbrief_repo.publish(steckbrief_id)
        await session.commit()

        logger.info(
            "steckbrief_published",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return {
            "message": "Steckbrief published",
            "steckbrief_id": steckbrief_id,
            "published_at": datetime.now(timezone.utc)
        }

    except Exception as e:
        logger.error("publish_steckbrief_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/steckbriefe/{steckbrief_id}/unpublish")
async def unpublish_steckbrief(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Unpublish steckbrief"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")

    try:
        steckbrief.published = False
        steckbrief.published_at = None
        await session.commit()

        logger.info(
            "steckbrief_unpublished",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return {
            "message": "Steckbrief unpublished",
            "steckbrief_id": steckbrief_id
        }

    except Exception as e:
        logger.error("unpublish_steckbrief_error", error=str(e))
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint for regenerating a single profile

@router.post("/steckbriefe/publish-all")
async def publish_all_steckbriefe(
        session: AsyncSession = Depends(get_async_session)
):
    """Publish all steckbriefe at once"""
    from sqlalchemy import update as sql_update
    from datetime import datetime, timezone

    try:
        # Update all unpublished steckbriefe
        stmt = (
            sql_update(Steckbrief)
            .where(Steckbrief.published == False)
            .values(
                published=True,
                published_at=datetime.now(timezone.utc)
            )
        )

        result = await session.execute(stmt)
        await session.commit()

        count = result.rowcount

        logger.info(
            "bulk_publish_completed",
            steckbriefe_published=count
        )

        return {
            "message": f"Published {count} steckbriefe",
            "count": count
        }

    except Exception as e:
        logger.error("bulk_publish_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))



# ========================================
# STATIC SITE GENERATION ENDPOINTS
# ========================================

@router.post("/generate-site", dependencies=[Depends(require_admin)])
async def generate_static_site(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """Trigger static site generation (runs in background)"""

    async def _generate():
        try:
            generator = StaticSiteGenerator(session)
            stats = await generator.generate_full_site()
            logger.info("Static site generation completed", **stats)
        except Exception as e:
            logger.error("Static site generation failed", error=str(e), exc_info=True)

    background_tasks.add_task(_generate)

    return {
        "message": "Static site generation started",
        "status": "processing"
    }


@router.get("/generate-site/status")
async def get_generation_status(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """Get status of last site generation"""
    output_dir = Path(settings.public_site_dir)

    if not output_dir.exists():
        return {
            "status": "never_generated",
            "message": "Site wurde noch nie generiert"
        }

    index_file = output_dir / "index.html"
    if index_file.exists():
        last_modified = datetime.fromtimestamp(index_file.stat().st_mtime)
        html_files = len(list(output_dir.glob("**/*.html")))

        return {
            "status": "completed",
            "last_generated": last_modified.isoformat(),
            "html_files": html_files,
            "output_dir": str(output_dir)
        }

    return {
        "status": "unknown",
        "message": "Status konnte nicht ermittelt werden"
    }

# ============================================
# SEEDING ENDPOINTS
# ============================================

@router.post("/seed/run", dependencies=[Depends(require_admin)])
async def run_database_seed(
    force: bool = False,
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Run database seeding to create/update default categories and prompts.
    
    Args:
        force: If True, update existing entries. If False, skip existing.
    """
    # The YAML category files are the single source of truth for categories and
    # prompts. "force" decides whether existing rows are updated from the files
    # or left alone.
    from app.seed import load_categories_from_config

    stats = await load_categories_from_config(session, only_new=not force)
    
    return {
        "message": "Seeding completed",
        "force_update": force,
        "stats": stats
    }


@router.get("/seed/status")
async def get_seed_status(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """Get current status of seeded categories and prompts"""
    from sqlalchemy import func
    from app.models import Category, Prompt, CategoryPrompt
    
    # Count categories
    cat_result = await session.execute(
        select(func.count(Category.id))
    )
    cat_count = cat_result.scalar()
    
    # Count prompts
    prompt_result = await session.execute(
        select(func.count(Prompt.id))
    )
    prompt_count = prompt_result.scalar()
    
    # Count mappings
    mapping_result = await session.execute(
        select(func.count(CategoryPrompt.id))
    )
    mapping_count = mapping_result.scalar()
    
    # Get category details
    cats_result = await session.execute(
        select(Category.internal_name, Category.display_name, Category.is_active)
    )
    categories = [
        {"internal_name": r[0], "display_name": r[1], "is_active": r[2]}
        for r in cats_result.fetchall()
    ]
    
    return {
        "categories_count": cat_count,
        "prompts_count": prompt_count,
        "mappings_count": mapping_count,
        "categories": categories
    }


# ============================================
# CONFIG ENDPOINTS
# ============================================

@router.get("/config/specification")
async def get_config_specification():
    """Download the category YAML specification"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    
    spec_file = Path(__file__).parent.parent.parent / "docs" / "configuration.md"
    
    if not spec_file.exists():
        raise HTTPException(status_code=404, detail="Specification file not found")
    
    return FileResponse(
        spec_file,
        media_type="text/markdown",
        filename="configuration.md"
    )


@router.get("/config/export/{category_id}")
async def export_category_yaml(
    category_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Export a category as YAML file"""
    from fastapi.responses import Response
    from app.seed import export_category_to_yaml
    
    yaml_content = await export_category_to_yaml(session, category_id)
    
    if not yaml_content:
        raise HTTPException(status_code=404, detail="Category not found")
    
    # Get category name for filename
    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one()
    
    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": f'attachment; filename="{category.internal_name}.yaml"'
        }
    )


@router.get("/config/export-all")
async def export_all_categories_zip(
    session: AsyncSession = Depends(get_async_session)
):
    """Export all categories as ZIP file"""
    import io
    import zipfile
    from fastapi.responses import Response
    from app.seed import export_category_to_yaml
    
    # Get all categories
    result = await session.execute(select(Category))
    categories = result.scalars().all()
    
    if not categories:
        raise HTTPException(status_code=404, detail="No categories found")
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for cat in categories:
            yaml_content = await export_category_to_yaml(session, cat.id)
            if yaml_content:
                zip_file.writestr(f"{cat.internal_name}.yaml", yaml_content)
    
    zip_buffer.seek(0)
    
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="flexmapping_categories.zip"'
        }
    )


@router.post("/config/reload", dependencies=[Depends(require_admin)])
async def reload_categories_from_config(
    only_new: bool = True,
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Reload categories from YAML config files.
    
    Args:
        only_new: If True, only load new categories. If False, update existing ones too.
    """
    from app.seed import load_categories_from_config
    
    stats = await load_categories_from_config(session, only_new=only_new)
    
    return {
        "message": "Config reload completed",
        "only_new": only_new,
        "stats": stats
    }


# ============================================
# RETRY PENDING SOURCES
# ============================================

@router.post("/sources/retry-pending")
async def retry_pending_sources(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Re-queue all sources with status 'pending' for crawling.
    Useful when worker was down or jobs got stuck.
    
    Note: Status remains 'pending' - worker will update it after crawling.
    """
    from app.services.job_queue import JobType as JT
    
    # Find all pending sources
    result = await session.execute(
        select(Source).where(Source.status == 'pending')
    )
    pending_sources = result.scalars().all()
    
    if not pending_sources:
        return {
            "message": "No pending sources found",
            "queued": 0
        }
    
    job_queue = await get_job_queue()
    queued_count = 0
    errors = []
    
    for source in pending_sources:
        try:
            # Queue CRAWL job (pending = not yet crawled)
            await job_queue.enqueue(
                job_type=JT.CRAWL,
                source_id=str(source.id),
                payload={'url': source.url}
            )
            
            # Don't change status - 'pending' is valid, worker will update to 'crawled'
            queued_count += 1
            
            logger.debug(
                "pending_source_requeued",
                source_id=str(source.id),
                url=source.url
            )
            
        except Exception as e:
            logger.error(
                "retry_pending_source_failed",
                source_id=str(source.id),
                error=str(e)
            )
            errors.append({
                'source_id': str(source.id),
                'error': str(e)
            })
    
    # No commit needed - we didn't change any source status
    
    logger.info(
        "retry_pending_completed",
        total_pending=len(pending_sources),
        queued=queued_count,
        errors=len(errors)
    )
    
    return {
        "message": f"Re-queued {queued_count} sources for crawling",
        "queued": queued_count,
        "total_pending": len(pending_sources),
        "errors": errors if errors else None
    }


@router.post("/sources/retry-failed")
async def retry_failed_sources(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Re-queue all sources with status 'failed' for crawling/extraction.
    Sets status back to 'pending' and queues crawl job.
    """
    from app.services.job_queue import JobType as JT
    
    # Find all failed sources
    result = await session.execute(
        select(Source).where(Source.status == 'failed')
    )
    failed_sources = result.scalars().all()
    
    if not failed_sources:
        return {
            "message": "No failed sources found",
            "queued": 0
        }
    
    job_queue = await get_job_queue()
    queued_count = 0
    errors = []
    
    for source in failed_sources:
        try:
            # Queue crawl job (starts fresh)
            await job_queue.enqueue(
                job_type=JT.CRAWL,
                source_id=str(source.id),
                payload={'url': source.url}
            )
            
            # Reset status to 'pending' (allowed by check constraint)
            source.status = 'pending'
            source.error_message = None  # Clear previous error
            queued_count += 1
            
            logger.debug(
                "failed_source_requeued",
                source_id=str(source.id),
                url=source.url
            )
            
        except Exception as e:
            logger.error(
                "retry_failed_source_failed",
                source_id=str(source.id),
                error=str(e)
            )
            errors.append({
                'source_id': str(source.id),
                'error': str(e)
            })
    
    await session.commit()
    
    logger.info(
        "retry_failed_completed",
        total_failed=len(failed_sources),
        queued=queued_count,
        errors=len(errors)
    )
    
    return {
        "message": f"Re-queued {queued_count} failed sources for crawling",
        "queued": queued_count,
        "total_failed": len(failed_sources),
        "errors": errors if errors else None
    }


@router.post("/sources/cleanup-stuck")
async def cleanup_stuck_sources(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Clean up sources that are stuck in intermediate states.
    
    Checks for:
    - Sources in 'extracting' status for > 2 hours (extraction should be faster)
    
    Note: 'pending' sources are NOT cleaned up as they may legitimately be waiting in queue.
    Use retry-pending to re-queue them if needed.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import and_
    
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)
    
    cleaned = {
        'stuck_extracting': 0
    }
    
    # Sources stuck in 'extracting' for > 2 hours
    result = await session.execute(
        select(Source).where(
            and_(
                Source.status == 'extracting',
                Source.updated_at < two_hours_ago
            )
        )
    )
    stuck_extracting = result.scalars().all()
    
    for source in stuck_extracting:
        source.status = 'failed'
        source.error_message = 'Extraktion unvollständig nach 2+ Stunden - vermutlich Worker-Fehler'
        cleaned['stuck_extracting'] += 1
    
    await session.commit()
    
    total = sum(cleaned.values())
    
    if total > 0:
        logger.info(
            "cleanup_stuck_sources_completed",
            **cleaned,
            total=total
        )
    
    return {
        "message": f"Cleaned up {total} stuck sources",
        "details": cleaned
    }


@router.post("/sources/retry-extracting")
async def retry_extracting_sources(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Re-queue all sources with status 'extracting' for extraction.
    These have already been crawled, so we only need to create extraction jobs.
    """
    from app.services.job_queue import JobType as JT, JobPriority as JP
    
    # Find all extracting sources
    result = await session.execute(
        select(Source).where(Source.status == 'extracting')
    )
    extracting_sources = result.scalars().all()
    
    if not extracting_sources:
        return {
            "message": "No extracting sources found",
            "queued": 0
        }
    
    job_queue = await get_job_queue()
    prompt_repo = PromptRepository(Prompt, session)
    
    queued_count = 0
    sources_processed = 0
    errors = []
    
    for source in extracting_sources:
        try:
            # Get prompts for this category
            if not source.category_id:
                errors.append({
                    'source_id': str(source.id),
                    'error': 'No category assigned'
                })
                continue
            
            prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)
            
            if not prompts:
                errors.append({
                    'source_id': str(source.id),
                    'error': f'No active prompts for category {source.category_id}'
                })
                continue
            
            # Queue extraction job for each prompt
            for prompt in prompts:
                await job_queue.enqueue(
                    job_type=JT.EXTRACT,
                    source_id=str(source.id),
                    prompt_id=prompt.id,
                    priority=JP.EXTRACT_INDEPENDENT,
                    payload={}
                )
                queued_count += 1
            
            sources_processed += 1
            
            logger.debug(
                "extracting_source_requeued",
                source_id=str(source.id),
                prompts_queued=len(prompts)
            )
            
        except Exception as e:
            logger.error(
                "retry_extracting_source_failed",
                source_id=str(source.id),
                error=str(e)
            )
            errors.append({
                'source_id': str(source.id),
                'error': str(e)
            })
    
    # Don't change status - they're already 'extracting'
    
    logger.info(
        "retry_extracting_completed",
        total_extracting=len(extracting_sources),
        sources_processed=sources_processed,
        jobs_queued=queued_count,
        errors=len(errors)
    )
    
    return {
        "message": f"Re-queued {queued_count} extraction jobs for {sources_processed} sources",
        "sources_processed": sources_processed,
        "jobs_queued": queued_count,
        "total_extracting": len(extracting_sources),
        "errors": errors if errors else None
    }


# ========================================
# REGENERATE ALL STECKBRIEFE
# ========================================

@router.post("/steckbriefe/regenerate-all", dependencies=[Depends(require_admin)])
async def regenerate_all_steckbriefe(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Regenerate ALL steckbriefe from scratch.
    
    This will:
    1. Unpublish all steckbriefe (set published=False)
    2. Delete all existing steckbriefe
    3. Queue GENERATE jobs for all completed sources
    
    Use this after template/prompt changes to recreate all steckbriefe with new format.
    """
    from app.services.job_queue import JobType as JT, JobPriority as JP
    
    try:
        # Step 1: Count existing steckbriefe
        count_result = await session.execute(
            select(func.count(Steckbrief.id))
        )
        existing_count = count_result.scalar() or 0
        
        # Step 2: Delete all steckbriefe
        await session.execute(
            Steckbrief.__table__.delete()
        )
        
        logger.info(
            "steckbriefe_deleted_for_regeneration",
            deleted_count=existing_count
        )
        
        # Step 3: Find all completed sources
        result = await session.execute(
            select(Source).where(Source.status == 'completed')
        )
        completed_sources = result.scalars().all()
        
        if not completed_sources:
            await session.commit()
            return {
                "message": "No completed sources to regenerate steckbriefe for",
                "deleted": existing_count,
                "queued": 0
            }
        
        # Step 4: Queue GENERATE jobs for all completed sources
        job_queue = await get_job_queue()
        queued_count = 0
        errors = []
        
        for source in completed_sources:
            try:
                await job_queue.enqueue(
                    job_type=JT.GENERATE,
                    source_id=str(source.id),
                    priority=JP.GENERATE,
                    payload={}
                )
                queued_count += 1
            except Exception as e:
                errors.append({
                    'source_id': str(source.id),
                    'error': str(e)
                })
        
        await session.commit()
        
        logger.info(
            "steckbriefe_regeneration_started",
            deleted=existing_count,
            queued=queued_count,
            errors=len(errors)
        )
        
        return {
            "message": f"Deleted {existing_count} steckbriefe, queued {queued_count} for regeneration",
            "deleted": existing_count,
            "queued": queued_count,
            "total_completed_sources": len(completed_sources),
            "errors": errors if errors else None
        }
        
    except Exception as e:
        logger.error("regenerate_all_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# RE-EXTRACT ALL SOURCES
# ========================================

@router.post("/sources/re-extract-all")
async def re_extract_all_sources(
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Re-extract ALL completed sources with current prompts.
    
    This will:
    1. Delete all existing extractions for completed sources
    2. Delete all existing steckbriefe
    3. Set completed sources back to 'crawled' status
    4. Queue EXTRACT jobs for each source with all active prompts
    
    Use this after prompt changes to re-extract all data with new prompts.
    The worker will automatically generate new steckbriefe after extraction.
    """
    from app.services.job_queue import JobType as JT, JobPriority as JP
    from app.models import CategoryPrompt
    
    try:
        # Step 1: Find all completed sources (these have been fully processed)
        result = await session.execute(
            select(Source).where(Source.status.in_(['completed', 'extracting']))
        )
        sources_to_process = result.scalars().all()
        
        if not sources_to_process:
            return {
                "message": "No completed sources to re-extract",
                "sources": 0,
                "jobs_queued": 0
            }
        
        source_ids = [s.id for s in sources_to_process]
        
        # Step 2: Delete existing extractions for these sources
        extraction_delete = await session.execute(
            Extraction.__table__.delete().where(Extraction.source_id.in_(source_ids))
        )
        deleted_extractions = extraction_delete.rowcount
        
        # Step 3: Delete existing steckbriefe for these sources
        steckbrief_delete = await session.execute(
            Steckbrief.__table__.delete().where(Steckbrief.source_id.in_(source_ids))
        )
        deleted_steckbriefe = steckbrief_delete.rowcount
        
        # Step 4: Get all active prompts grouped by category via CategoryPrompt table
        prompt_result = await session.execute(
            select(CategoryPrompt.category_id, Prompt)
            .join(Prompt, CategoryPrompt.prompt_id == Prompt.id)
            .where(Prompt.is_active == True)
        )
        prompt_rows = prompt_result.fetchall()
        
        # Group prompts by category_id
        prompts_by_category = {}
        for category_id, prompt in prompt_rows:
            if category_id not in prompts_by_category:
                prompts_by_category[category_id] = []
            prompts_by_category[category_id].append(prompt)
        
        # Log what we found
        logger.info(
            "re_extract_all_prompts_loaded",
            categories_with_prompts=len(prompts_by_category),
            total_prompts=len(prompt_rows)
        )
        
        if not prompts_by_category:
            return {
                "message": "FEHLER: Keine Prompts gefunden! Bitte zuerst Kategorien mit 'Überschreiben' neu laden.",
                "sources": len(sources_to_process),
                "jobs_queued": 0,
                "error": "No prompts found - reload categories with 'Überschreiben' first"
            }
        
        # Step 5: Queue extraction jobs
        job_queue = await get_job_queue()
        jobs_queued = 0
        sources_processed = 0
        sources_without_prompts = 0
        errors = []
        
        for source in sources_to_process:
            try:
                # Get prompts for this source's category
                category_prompts = prompts_by_category.get(source.category_id, [])
                
                if not category_prompts:
                    sources_without_prompts += 1
                    errors.append({
                        'source_id': str(source.id),
                        'category_id': source.category_id,
                        'error': f'No active prompts for category {source.category_id}'
                    })
                    # Set status to failed so user knows something is wrong
                    source.status = 'failed'
                    source.error_message = 'Keine Prompts für diese Kategorie gefunden'
                    continue
                
                # Set status back to 'crawled' (ready for extraction)
                source.status = 'crawled'
                source.error_message = None
                
                # Queue extract job for each prompt
                for prompt in category_prompts:
                    await job_queue.enqueue(
                        job_type=JT.EXTRACT,
                        source_id=str(source.id),
                        prompt_id=prompt.id,
                        priority=JP.EXTRACT_INDEPENDENT,
                        payload={}
                    )
                    jobs_queued += 1
                
                sources_processed += 1
                
            except Exception as e:
                errors.append({
                    'source_id': str(source.id),
                    'error': str(e)
                })
        
        await session.commit()
        
        logger.info(
            "re_extract_all_started",
            sources_processed=sources_processed,
            sources_without_prompts=sources_without_prompts,
            jobs_queued=jobs_queued,
            deleted_extractions=deleted_extractions,
            deleted_steckbriefe=deleted_steckbriefe,
            errors=len(errors)
        )
        
        message = f"Re-extraction gestartet: {sources_processed} Sources, {jobs_queued} Jobs in Queue"
        if sources_without_prompts > 0:
            message += f" (WARNUNG: {sources_without_prompts} Sources ohne Prompts!)"
        
        return {
            "message": message,
            "sources_processed": sources_processed,
            "sources_without_prompts": sources_without_prompts,
            "jobs_queued": jobs_queued,
            "deleted_extractions": deleted_extractions,
            "deleted_steckbriefe": deleted_steckbriefe,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        logger.error("re_extract_all_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# RE-VALIDATE EXTRACTIONS
# ========================================

@router.post("/sources/revalidate-all")
async def revalidate_all_extractions(
    only_missing: bool = Query(True, description="Nur Extraktionen ohne validated_result"),
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Run the validation phase again for every extraction.

    Useful when the validation failed earlier, or when the validate prompts
    have since been improved.

    Args:
        only_missing: if True, validate only extractions without a
            validated_result

    Returns:
        Statistics on what was validated
    """
    from app.services.llm_client import get_llm_client
    from app.services.prompt_engine import PromptEngineService
    from sqlalchemy.orm import selectinload
    
    try:
        # Gather debug information first: how many extractions are there at all?
        total_count_result = await session.execute(select(func.count(Extraction.id)))
        total_extractions = total_count_result.scalar()
        
        # How many carry a raw_result?
        with_raw_result = await session.execute(
            select(func.count(Extraction.id)).where(
                Extraction.raw_result.is_not(None),
                Extraction.raw_result != ''
            )
        )
        raw_result_count = with_raw_result.scalar()
        
        # How many have no validated_result, either NULL or empty?
        without_validated_result = await session.execute(
            select(func.count(Extraction.id)).where(
                or_(
                    Extraction.validated_result.is_(None),
                    Extraction.validated_result == ''
                )
            )
        )
        missing_validation_count = without_validated_result.scalar()
        
        logger.info(
            "revalidation_debug",
            total_extractions=total_extractions,
            with_raw_result=raw_result_count,
            missing_validation=missing_validation_count
        )
        
        # 1. Load the extractions
        query = select(Extraction).options(
            selectinload(Extraction.prompt),
            selectinload(Extraction.source)
        )
        
        if only_missing:
            # Extractions without a validated_result but with a raw_result
            query = query.where(
                or_(
                    Extraction.validated_result.is_(None),
                    Extraction.validated_result == ''
                ),
                Extraction.raw_result.is_not(None),
                Extraction.raw_result != ''
            )
        else:
            # Everything with a raw_result that is neither NULL nor empty
            query = query.where(
                Extraction.raw_result.is_not(None),
                Extraction.raw_result != ''
            )
        
        result = await session.execute(query)
        extractions = list(result.scalars().all())
        
        if not extractions:
            return {
                "success": True,
                "message": "Keine Extraktionen zum Validieren gefunden",
                "stats": {
                    "total": 0,
                    "validated": 0,
                    "failed": 0
                },
                "debug": {
                    "total_extractions": total_extractions,
                    "with_raw_result": raw_result_count,
                    "missing_validation": missing_validation_count,
                    "hint": "Wenn with_raw_result=0: Extraktionen haben kein raw_result. Wenn missing_validation=0: Alle haben bereits validated_result."
                }
            }
        
        logger.info(
            "starting_revalidation",
            extraction_count=len(extractions),
            only_missing=only_missing
        )
        
        # 2. Set up the LLM client and the prompt engine
        llm_client = get_llm_client()
        prompt_engine = PromptEngineService(session, llm_client)
        
        stats = {
            "total": len(extractions),
            "validated": 0,
            "failed": 0,
            "skipped": 0
        }
        
        errors = []
        
        # 3. Validate each extraction
        for ext in extractions:
            if not ext.prompt or not ext.raw_result:
                stats["skipped"] += 1
                continue
            
            try:
                # Fill the validate prompt with the raw result
                validate_prompt_text = ext.prompt.validate_prompt.format(
                    raw_result=ext.raw_result
                )
                
                # Source Markdown, as context
                markdown = ext.source.markdown_content if ext.source else ""
                
                # Run the validation
                from app.services.prompt_engine import ValidateResult
                validate_result = await prompt_engine._validate_phase(
                    raw_result=ext.raw_result,
                    markdown=markdown,
                    prompt=validate_prompt_text
                )
                
                if validate_result.success and validate_result.result:
                    ext.validated_result = validate_result.result
                    ext.validation_quality = validate_result.quality
                    ext.validation_score = validate_result.validation_score
                    ext.validation_notes = validate_result.notes
                    ext.validate_duration_ms = validate_result.duration_ms
                    
                    # Recompute the final confidence
                    ext.final_confidence = min(
                        ext.raw_confidence or 0.0,
                        validate_result.validation_score or 0.0
                    )
                    
                    stats["validated"] += 1
                else:
                    stats["failed"] += 1
                    if len(errors) < 10:
                        errors.append({
                            "extraction_id": ext.id,
                            "error": validate_result.error or "Unknown error"
                        })
                        
            except Exception as e:
                stats["failed"] += 1
                if len(errors) < 10:
                    errors.append({
                        "extraction_id": ext.id,
                        "error": str(e)
                    })
        
        await session.commit()
        
        logger.info(
            "revalidation_completed",
            **stats
        )
        
        return {
            "success": True,
            "message": f"{stats['validated']} Extraktionen validiert, {stats['failed']} fehlgeschlagen",
            "stats": stats,
            "errors": errors if errors else None
        }
        
    except Exception as e:
        logger.error("revalidation_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/revalidate")
async def revalidate_source_extractions(
    source_id: str,
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """Run the validation phase again for every extraction of one source."""
    from uuid import UUID
    from app.services.llm_client import get_llm_client
    from app.services.prompt_engine import PromptEngineService
    from sqlalchemy.orm import selectinload
    
    try:
        source_uuid = UUID(source_id)
        
        # Load the extractions of this source
        result = await session.execute(
            select(Extraction)
            .where(
                Extraction.source_id == source_uuid,
                Extraction.raw_result.is_not(None)
            )
            .options(
                selectinload(Extraction.prompt),
                selectinload(Extraction.source)
            )
        )
        extractions = list(result.scalars().all())
        
        if not extractions:
            return {
                "success": True,
                "message": "Keine Extraktionen zum Validieren gefunden",
                "stats": {"total": 0, "validated": 0, "failed": 0}
            }
        
        # Set up the LLM client and the prompt engine
        llm_client = get_llm_client()
        prompt_engine = PromptEngineService(session, llm_client)
        
        stats = {"total": len(extractions), "validated": 0, "failed": 0}
        
        for ext in extractions:
            if not ext.prompt:
                continue
                
            try:
                validate_prompt_text = ext.prompt.validate_prompt.format(
                    raw_result=ext.raw_result
                )
                markdown = ext.source.markdown_content if ext.source else ""
                
                validate_result = await prompt_engine._validate_phase(
                    raw_result=ext.raw_result,
                    markdown=markdown,
                    prompt=validate_prompt_text
                )
                
                if validate_result.success and validate_result.result:
                    ext.validated_result = validate_result.result
                    ext.validation_quality = validate_result.quality
                    ext.validation_score = validate_result.validation_score
                    ext.validation_notes = validate_result.notes
                    ext.validate_duration_ms = validate_result.duration_ms
                    ext.final_confidence = min(
                        ext.raw_confidence or 0.0,
                        validate_result.validation_score or 0.0
                    )
                    stats["validated"] += 1
                else:
                    stats["failed"] += 1
                    
            except Exception as e:
                stats["failed"] += 1
        
        await session.commit()
        
        return {
            "success": True,
            "message": f"{stats['validated']} von {stats['total']} validiert",
            "stats": stats
        }
        
    except Exception as e:
        logger.error("revalidation_error", error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# CHANGE SOURCE CATEGORY
# ========================================

@router.post("/sources/{source_id}/change-category")
async def change_source_category(
    source_id: str,
    new_category_id: int,
    re_extract: bool = True,
    session: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """
    Change the category of a source and optionally re-extract with new prompts.
    
    Args:
        source_id: Source UUID
        new_category_id: New category ID
        re_extract: If True, delete extractions/steckbrief and queue new extraction
    
    Returns:
        Status and action taken
    """
    from app.services.job_queue import JobType as JT, JobPriority as JP
    from app.models import CategoryPrompt
    from uuid import UUID
    
    try:
        source_uuid = UUID(source_id)
        
        # Get source
        result = await session.execute(
            select(Source).where(Source.id == source_uuid)
        )
        source = result.scalar_one_or_none()
        
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        # Get new category
        cat_result = await session.execute(
            select(Category).where(Category.id == new_category_id)
        )
        new_category = cat_result.scalar_one_or_none()
        
        if not new_category:
            raise HTTPException(status_code=404, detail="Category not found")
        
        old_category_id = source.category_id
        
        # Update category
        source.category_id = new_category_id
        
        response = {
            "message": f"Kategorie geändert zu '{new_category.display_name}'",
            "source_id": source_id,
            "old_category_id": old_category_id,
            "new_category_id": new_category_id,
            "re_extracted": False
        }
        
        if re_extract and source.status in ['completed', 'crawled', 'extracting']:
            # Delete existing extractions
            ext_delete = await session.execute(
                Extraction.__table__.delete().where(Extraction.source_id == source_uuid)
            )
            
            # Delete existing steckbrief
            steck_delete = await session.execute(
                Steckbrief.__table__.delete().where(Steckbrief.source_id == source_uuid)
            )
            
            # Get prompts for new category
            prompt_result = await session.execute(
                select(Prompt)
                .join(CategoryPrompt, Prompt.id == CategoryPrompt.prompt_id)
                .where(CategoryPrompt.category_id == new_category_id)
                .where(Prompt.is_active == True)
            )
            prompts = prompt_result.scalars().all()
            
            if prompts:
                # Set status to crawled (ready for extraction)
                source.status = 'crawled'
                source.error_message = None
                
                # Queue extraction jobs
                job_queue = await get_job_queue()
                jobs_queued = 0
                
                for prompt in prompts:
                    await job_queue.enqueue(
                        job_type=JT.EXTRACT,
                        source_id=str(source_uuid),
                        prompt_id=prompt.id,
                        priority=JP.EXTRACT_INDEPENDENT,
                        payload={}
                    )
                    jobs_queued += 1
                
                response["re_extracted"] = True
                response["extractions_deleted"] = ext_delete.rowcount
                response["steckbrief_deleted"] = steck_delete.rowcount > 0
                response["jobs_queued"] = jobs_queued
                response["message"] = f"Kategorie geändert zu '{new_category.display_name}', {jobs_queued} Extraktions-Jobs in Queue"
            else:
                response["warning"] = f"Keine aktiven Prompts für Kategorie '{new_category.display_name}'"
        
        await session.commit()
        
        logger.info(
            "source_category_changed",
            source_id=source_id,
            old_category_id=old_category_id,
            new_category_id=new_category_id,
            re_extracted=response.get("re_extracted", False)
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("change_category_error", source_id=source_id, error=str(e), exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TRANSLATION ENDPOINTS
# ============================================================================

@router.get("/translations/status")
async def get_translation_status(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get translation status for all steckbriefe.
    Returns counts of translated, pending, and outdated translations.
    """
    from app.models import Steckbrief, SteckbriefTranslation
    import hashlib
    
    # Get all published steckbriefe
    result = await session.execute(
        select(Steckbrief).where(Steckbrief.published == True)
    )
    steckbriefe = result.scalars().all()
    
    # Get all translations
    trans_result = await session.execute(
        select(SteckbriefTranslation).where(SteckbriefTranslation.language == 'en')
    )
    translations = {t.steckbrief_id: t for t in trans_result.scalars().all()}
    
    stats = {
        "total": len(steckbriefe),
        "translated": 0,
        "pending": 0,
        "outdated": 0,
        "details": []
    }
    
    for steckbrief in steckbriefe:
        translation = translations.get(steckbrief.id)
        
        if not translation:
            stats["pending"] += 1
            status = "pending"
        else:
            # Check if source has changed
            current_hash = hashlib.sha256(
                (steckbrief.markdown_content or "").encode('utf-8')
            ).hexdigest()
            
            if translation.source_hash != current_hash:
                stats["outdated"] += 1
                status = "outdated"
            else:
                stats["translated"] += 1
                status = "translated"
        
        stats["details"].append({
            "steckbrief_id": steckbrief.id,
            "status": status,
            "translated_at": translation.translated_at.isoformat() if translation else None
        })
    
    return stats


@router.post("/translations/generate", dependencies=[Depends(require_admin)])
async def generate_translations(
    target_language: str = "en",
    force: bool = False,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Queue translation jobs for all steckbriefe that need translation.
    
    Args:
        target_language: Target language (default: 'en')
        force: If True, re-translate even if translation exists
    """
    from app.models import Steckbrief, SteckbriefTranslation, JobPriority as JP
    from app.services.job_queue import JobType as JT, get_job_queue
    import hashlib
    
    # Get all published steckbriefe
    result = await session.execute(
        select(Steckbrief).where(Steckbrief.published == True)
    )
    steckbriefe = result.scalars().all()
    
    if not steckbriefe:
        return {"message": "No published steckbriefe to translate", "jobs_queued": 0}
    
    # Get existing translations
    trans_result = await session.execute(
        select(SteckbriefTranslation).where(
            SteckbriefTranslation.language == target_language
        )
    )
    translations = {t.steckbrief_id: t for t in trans_result.scalars().all()}
    
    # Find steckbriefe that need translation
    to_translate = []
    
    for steckbrief in steckbriefe:
        translation = translations.get(steckbrief.id)
        
        needs_translation = False
        
        if force:
            needs_translation = True
        elif not translation:
            needs_translation = True
        else:
            # Check if source has changed
            current_hash = hashlib.sha256(
                (steckbrief.markdown_content or "").encode('utf-8')
            ).hexdigest()
            if translation.source_hash != current_hash:
                needs_translation = True
        
        if needs_translation:
            to_translate.append(steckbrief)
    
    if not to_translate:
        return {
            "message": "All steckbriefe already translated",
            "jobs_queued": 0,
            "total_steckbriefe": len(steckbriefe)
        }
    
    # Queue translation jobs
    job_queue = await get_job_queue()
    jobs_queued = 0
    
    for steckbrief in to_translate:
        await job_queue.enqueue(
            job_type=JT.TRANSLATE,
            source_id=str(steckbrief.source_id),
            priority=20,  # Lower priority than extraction
            payload={
                "steckbrief_id": steckbrief.id,
                "target_language": target_language
            }
        )
        jobs_queued += 1
    
    logger.info(
        "translation_jobs_queued",
        jobs_queued=jobs_queued,
        target_language=target_language,
        total_steckbriefe=len(steckbriefe)
    )
    
    return {
        "message": f"{jobs_queued} translation jobs queued",
        "jobs_queued": jobs_queued,
        "target_language": target_language,
        "total_steckbriefe": len(steckbriefe)
    }


@router.post("/translations/{steckbrief_id}")
async def translate_single_steckbrief(
    steckbrief_id: int,
    target_language: str = "en",
    session: AsyncSession = Depends(get_async_session)
):
    """
    Queue translation job for a single steckbrief.
    """
    from app.models import Steckbrief
    from app.services.job_queue import JobType as JT, get_job_queue
    
    # Check if steckbrief exists
    result = await session.execute(
        select(Steckbrief).where(Steckbrief.id == steckbrief_id)
    )
    steckbrief = result.scalar_one_or_none()
    
    if not steckbrief:
        raise HTTPException(status_code=404, detail="Steckbrief not found")
    
    if not steckbrief.markdown_content:
        raise HTTPException(status_code=400, detail="Steckbrief has no content to translate")
    
    # Queue translation job
    job_queue = await get_job_queue()
    
    await job_queue.enqueue(
        job_type=JT.TRANSLATE,
        source_id=str(steckbrief.source_id),
        priority=30,  # Higher priority for single translation
        payload={
            "steckbrief_id": steckbrief.id,
            "target_language": target_language
        }
    )
    
    logger.info(
        "single_translation_queued",
        steckbrief_id=steckbrief_id,
        target_language=target_language
    )
    
    return {
        "message": f"Translation job queued for steckbrief {steckbrief_id}",
        "steckbrief_id": steckbrief_id,
        "target_language": target_language
    }


@router.get("/translations/{steckbrief_id}")
async def get_steckbrief_translation(
    steckbrief_id: int,
    target_language: str = "en",
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get translation for a specific steckbrief.
    """
    from app.models import SteckbriefTranslation
    
    result = await session.execute(
        select(SteckbriefTranslation).where(
            SteckbriefTranslation.steckbrief_id == steckbrief_id,
            SteckbriefTranslation.language == target_language
        )
    )
    translation = result.scalar_one_or_none()
    
    if not translation:
        raise HTTPException(
            status_code=404, 
            detail=f"No {target_language} translation found for steckbrief {steckbrief_id}"
        )
    
    return {
        "steckbrief_id": steckbrief_id,
        "language": translation.language,
        "markdown_content": translation.markdown_content,
        "translated_at": translation.translated_at.isoformat(),
        "source_hash": translation.source_hash
    }


@router.post("/generate-english-site", dependencies=[Depends(require_admin)])
async def generate_english_site(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Trigger English static site generation.
    Generates English version of the website using translated steckbriefe.
    """
    from app.services.static_site_generator import StaticSiteGenerator
    
    try:
        generator = StaticSiteGenerator(session)
        stats = await generator.generate_english_site()
        
        logger.info("english_site_generated", stats=stats)
        
        return {
            "status": "success",
            "message": f"English site generated: {stats['steckbriefe']} steckbriefe, {stats['pages_generated']} pages",
            "stats": stats
        }
    except Exception as e:
        logger.error("english_site_generation_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# FACTORY RESET ENDPOINTS
# ============================================================

@router.post("/factory-reset", dependencies=[Depends(require_admin)])
async def factory_reset(
    request: Request,
    confirm: str = Query(..., description="Must be 'DELETE_ALL_DATA' to confirm"),
    reload_categories: bool = Query(True, description="Reload categories from YAML after reset"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    DANGER: Complete factory reset - deletes ALL data from database and Redis.
    
    This will:
    1. Delete all data from PostgreSQL (sources, steckbriefe, extractions, translations, jobs)
    2. Clear Redis cache and job queue
    3. Optionally reload categories from YAML files
    
    Requires confirmation parameter: confirm=DELETE_ALL_DATA
    """
    # Safety check
    if confirm != "DELETE_ALL_DATA":
        raise HTTPException(
            status_code=400, 
            detail="Safety check failed. Set confirm=DELETE_ALL_DATA to proceed."
        )
    
    # This operation is irreversible and there is no backup step in front of
    # it, so the account that triggered it is recorded explicitly.
    actor = getattr(getattr(request.state, "user", None), "username", "unknown")
    logger.warning("factory_reset_initiated", triggered_by=actor)
    
    results = {
        "postgres_cleared": False,
        "redis_cleared": False,
        "categories_reloaded": False,
        "errors": []
    }
    
    try:
        # 1. Clear PostgreSQL - Delete in correct order (foreign key constraints)
        from sqlalchemy import text
        
        # Table names taken from models.py
        # Order matters: dependent tables first, parent tables afterwards
        tables_to_clear = [
            "steckbrief_translations",  # FK to steckbriefe
            "steckbriefe",              # FK to sources
            "extractions",              # FK to sources, prompts
            "job_queue",                # Foreign key points at sources, not at jobs
            "entity_normalization_queue",
            "entity_variants",          # FK to entities
            "category_prompts",         # FK to categories, prompts
            "prompt_dependencies",      # FK to prompts
            "sources",                  # FK to categories, entities
            "prompts",                  # Independent
            "categories",               # Independent
            "entities",                 # Independent
            "circuit_breaker_state",    # Independent
        ]
        
        deleted_counts = {}
        
        # Truncate every table at once with CASCADE. Deleting row by row across
        # foreign keys is both slower and easy to get into a half-done state.
        try:
            # Truncate all tables in one statement
            tables_str = ", ".join(tables_to_clear)
            await session.execute(text(f"TRUNCATE TABLE {tables_str} CASCADE"))
            await session.commit()
            
            results["postgres_cleared"] = True
            deleted_counts["all_tables"] = "truncated"
            logger.info("postgres_cleared_via_truncate", tables=tables_to_clear)
            
        except Exception as truncate_error:
            logger.warning("truncate_failed_trying_individual", error=str(truncate_error))
            await session.rollback()
            
            # Fallback: delete them one at a time
            for table in tables_to_clear:
                try:
                    # A fresh transaction per table, so one failure does not abort the rest
                    result = await session.execute(text(f"DELETE FROM {table}"))
                    await session.commit()
                    deleted_counts[table] = result.rowcount
                    logger.info(f"Cleared table {table}", count=result.rowcount)
                except Exception as e:
                    await session.rollback()
                    error_msg = str(e)
                    if "does not exist" in error_msg.lower():
                        logger.debug(f"Table {table} does not exist, skipping")
                        deleted_counts[table] = "not_exists"
                    else:
                        logger.warning(f"Could not clear table {table}", error=error_msg)
                        results["errors"].append(f"Table {table}: {error_msg[:100]}")
            
            # Did we clear enough tables to call this a success?
            successful_clears = sum(1 for v in deleted_counts.values() if v not in ["not_exists", None])
            results["postgres_cleared"] = successful_clears >= 5  # Mindestens 5 Tabellen sollten funktionieren
        
        results["deleted_counts"] = deleted_counts
        
    except Exception as e:
        logger.error("postgres_clear_failed", error=str(e), exc_info=True)
        results["errors"].append(f"PostgreSQL: {str(e)[:200]}")
        try:
            await session.rollback()
        except:
            pass
    
    # 2. Clear Redis
    try:
        import redis.asyncio as redis
        from app.config import get_settings
        settings = get_settings()
        
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.flushdb()
        await redis_client.close()
        
        results["redis_cleared"] = True
        logger.info("redis_cleared")
        
    except Exception as e:
        logger.error("redis_clear_failed", error=str(e), exc_info=True)
        results["errors"].append(f"Redis: {str(e)[:100]}")
    
    # 3. Reload categories from YAML
    if reload_categories:
        try:
            from app.seed import load_categories_from_config
            from app.database import AsyncSessionLocal
            
            # A fresh session for the seeding: the previous one may be in a failed state
            async with AsyncSessionLocal() as new_session:
                stats = await load_categories_from_config(new_session, only_new=False)
                results["categories_reloaded"] = True
                results["category_stats"] = stats
                logger.info("categories_reloaded", stats=stats)
                
        except Exception as e:
            logger.error("category_reload_failed", error=str(e), exc_info=True)
            results["errors"].append(f"Category reload: {str(e)[:100]}")
    
    # Summary
    success = results["postgres_cleared"] and results["redis_cleared"]
    if reload_categories:
        success = success and results["categories_reloaded"]
    
    logger.info("factory_reset_completed", success=success, results=results)
    
    return {
        "status": "success" if success else "partial",
        "message": "Factory reset completed" if success else "Factory reset completed with errors",
        "results": results
    }


@router.post("/clear-redis")
async def clear_redis():
    """
    Clear Redis cache and job queue only (keeps PostgreSQL data).
    Useful for clearing stuck jobs or cache issues.
    """
    try:
        import redis.asyncio as redis
        from app.config import get_settings
        settings = get_settings()
        
        redis_client = redis.from_url(settings.redis_url)
        
        # Get stats before clearing
        keys_count = await redis_client.dbsize()
        
        await redis_client.flushdb()
        await redis_client.close()
        
        logger.info("redis_cleared", keys_deleted=keys_count)
        
        return {
            "status": "success",
            "message": f"Redis cleared: {keys_count} keys deleted"
        }
        
    except Exception as e:
        logger.error("redis_clear_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload-categories", dependencies=[Depends(require_admin)])
async def reload_categories(
    force_update: bool = Query(True, description="Overwrite existing categories and prompts"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Reload all categories and prompts from YAML configuration files.
    
    With force_update=True: Overwrites existing categories and prompts
    With force_update=False: Only adds new categories/prompts, keeps existing
    """
    try:
        from app.seed import load_categories_from_config
        
        stats = await load_categories_from_config(session, only_new=not force_update)
        
        logger.info("categories_reloaded", force_update=force_update, stats=stats)
        
        return {
            "status": "success",
            "message": f"Categories reloaded: {stats['categories_created']} created, {stats['categories_updated']} updated",
            "stats": stats
        }
        
    except Exception as e:
        logger.error("category_reload_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/system-status")
async def get_system_status(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get current system status: database counts, Redis status, etc.
    Useful before performing a factory reset.
    """
    from sqlalchemy import text
    
    status = {
        "database": {},
        "redis": {},
        "errors": []
    }
    
    # Database counts, queried per table so that one cascade error does not
        # take the whole statistics endpoint down
    tables = [
        "categories", "prompts", "sources", "extractions", 
        "steckbriefe", "steckbrief_translations", "job_queue", "entities"
    ]
    
    for table in tables:
        try:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            status["database"][table] = result.scalar()
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str.lower():
                status["database"][table] = "table_not_exists"
            else:
                status["database"][table] = f"error"
                status["errors"].append(f"{table}: {error_str[:50]}")
            # Roll back to leave the session usable
            try:
                await session.rollback()
            except:
                pass
    
    # Redis status
    try:
        import redis.asyncio as redis
        from app.config import get_settings
        settings = get_settings()
        
        redis_client = redis.from_url(settings.redis_url)
        status["redis"]["keys_count"] = await redis_client.dbsize()
        status["redis"]["connected"] = True
        await redis_client.close()
        
    except Exception as e:
        status["redis"]["connected"] = False
        status["redis"]["error"] = str(e)[:100]
    
    return status


# ============================================================================
# EXTRACTION-BASED TRANSLATION ENDPOINTS (NEW APPROACH)
# ============================================================================

@router.get("/extractions/translation-stats")
async def get_extraction_translation_stats(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get translation statistics for extractions.
    
    Returns counts by translation status.
    """
    from app.services.extraction_translation import ExtractionTranslationService
    from app.services.llm_client import get_llm_client
    
    llm_client = get_llm_client()
    translation_service = ExtractionTranslationService(llm_client, session)
    
    stats = await translation_service.get_translation_stats()
    
    return stats


@router.post("/extractions/translate")
async def translate_extractions(
    limit: int = Query(default=50, ge=1, le=500, description="Max extractions to translate"),
    force: bool = Query(default=False, description="Re-translate even if already translated"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Translate pending extractions to English.
    
    This is the NEW approach: translates individual extraction values,
    not entire steckbriefe. Much more robust and maintainable.
    
    Args:
        limit: Maximum number of extractions to translate in this batch
        force: If True, re-translate all (including already translated)
    
    Returns:
        Translation statistics
    """
    from app.services.extraction_translation import ExtractionTranslationService
    from app.services.llm_client import get_llm_client
    
    logger.info("Starting extraction translation", limit=limit, force=force)
    
    llm_client = get_llm_client()
    translation_service = ExtractionTranslationService(llm_client, session)
    
    stats = await translation_service.translate_all_pending(limit=limit, force=force)
    
    logger.info("Extraction translation completed", **stats)
    
    return {
        "message": f"Translated {stats['translated']} extractions",
        "stats": stats
    }


@router.post("/extractions/queue-translations")
async def queue_translation_jobs(
    force: bool = Query(default=False, description="Re-translate even if already translated"),
    generate_steckbrief: bool = Query(default=True, description="Generate EN steckbrief after translation"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Queue translation jobs for all sources with pending extractions.
    
    Creates one TRANSLATE job per source. Jobs appear in the job queue
    and can be monitored like other jobs (crawl, extract, validate).
    
    Args:
        force: If True, re-translate all sources
        generate_steckbrief: If True, also generate EN steckbrief after translation
    
    Returns:
        Number of jobs queued
    """
    from app.services.job_queue import get_job_queue, JobType, JobPriority
    from sqlalchemy import select, func, and_, or_
    from app.models import Source, Extraction, Steckbrief
    
    # Find sources that need translation
    if force:
        # All sources with steckbriefe
        query = select(Source.id).join(Steckbrief, Source.id == Steckbrief.source_id).distinct()
    else:
        # Sources with extractions that have validated_result but no validated_result_en
        query = (
            select(Source.id)
            .join(Extraction, Source.id == Extraction.source_id)
            .where(
                and_(
                    Extraction.validated_result.isnot(None),
                    Extraction.validated_result != '',
                    or_(
                        Extraction.validated_result_en.is_(None),
                        Extraction.validated_result_en == ''
                    )
                )
            )
            .distinct()
        )
    
    result = await session.execute(query)
    source_ids = [row[0] for row in result.fetchall()]
    
    if not source_ids:
        return {
            "message": "No sources need translation",
            "jobs_queued": 0
        }
    
    # Queue jobs
    job_queue = await get_job_queue()
    jobs_queued = 0
    
    for source_id in source_ids:
        await job_queue.enqueue(
            job_type=JobType.TRANSLATE,
            source_id=str(source_id),
            payload={
                'target_language': 'en',
                'force': force,
                'generate_steckbrief': generate_steckbrief
            },
            priority=JobPriority.TRANSLATE
        )
        jobs_queued += 1
        
        logger.info(
            "translation_job_queued",
            source_id=str(source_id)
        )
    
    return {
        "message": f"Queued {jobs_queued} translation jobs",
        "jobs_queued": jobs_queued,
        "source_ids": [str(sid) for sid in source_ids]
    }


@router.post("/extractions/translate-source/{source_id}")
async def translate_source_extractions(
    source_id: UUID,
    force: bool = Query(default=False, description="Re-translate even if already translated"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Translate all extractions for a specific source.
    
    Args:
        source_id: UUID of the source
        force: If True, re-translate all
    
    Returns:
        Translation statistics for this source
    """
    from app.services.extraction_translation import ExtractionTranslationService
    from app.services.llm_client import get_llm_client
    
    llm_client = get_llm_client()
    translation_service = ExtractionTranslationService(llm_client, session)
    
    stats = await translation_service.translate_source_extractions(
        source_id=str(source_id),
        force=force
    )
    
    return {
        "message": f"Translated {stats['translated']} extractions for source",
        "source_id": str(source_id),
        "stats": stats
    }


@router.post("/steckbriefe/generate-english", dependencies=[Depends(require_admin)])
async def generate_english_steckbriefe(
    limit: int = Query(default=50, ge=1, le=500, description="Max steckbriefe to generate"),
    session: AsyncSession = Depends(get_async_session)
):
    """
    Generate English steckbriefe from translated extractions.
    
    Uses the SteckbriefGenerator with language='en' to create
    English markdown using validated_result_en values.
    
    Prerequisites:
    - Extractions must be translated first (via /extractions/translate)
    
    Returns:
        Generation statistics
    """
    from app.services.steckbrief_generator import SteckbriefGenerator
    from app.models import Source, Steckbrief
    
    generator = SteckbriefGenerator(session)
    
    # Find sources with published steckbriefe
    result = await session.execute(
        select(Source)
        .join(Steckbrief, Source.id == Steckbrief.source_id)
        .where(Steckbrief.published == True)
        .limit(limit)
    )
    sources = result.scalars().all()
    
    stats = {
        'total': len(sources),
        'generated': 0,
        'failed': 0,
        'errors': []
    }
    
    for source in sources:
        try:
            # Generate English steckbrief
            steckbrief = await generator.generate(source.id, language='en')
            
            # Store English content in steckbrief_translations table for now
            # Alternatively these could become fields on the Steckbrief model
            from app.models import SteckbriefTranslation
            import hashlib
            
            existing = await session.execute(
                select(SteckbriefTranslation).where(
                    SteckbriefTranslation.steckbrief_id == steckbrief.id,
                    SteckbriefTranslation.language == 'en'
                )
            )
            translation = existing.scalar_one_or_none()
            
            source_hash = hashlib.sha256(
                (steckbrief.markdown_content or "").encode('utf-8')
            ).hexdigest()
            
            if translation:
                translation.markdown_content = steckbrief.markdown_content
                translation.source_hash = source_hash
                translation.translated_at = datetime.now(timezone.utc)
            else:
                translation = SteckbriefTranslation(
                    steckbrief_id=steckbrief.id,
                    language='en',
                    markdown_content=steckbrief.markdown_content,
                    source_hash=source_hash,
                    translated_at=datetime.now(timezone.utc)
                )
                session.add(translation)
            
            stats['generated'] += 1
            
        except Exception as e:
            stats['failed'] += 1
            stats['errors'].append(f"{source.id}: {str(e)[:100]}")
            logger.error(
                "Failed to generate English steckbrief",
                source_id=str(source.id),
                error=str(e)
            )
    
    await session.commit()
    
    logger.info("English steckbrief generation completed", **stats)
    
    return {
        "message": f"Generated {stats['generated']} English steckbriefe",
        "stats": stats
    }


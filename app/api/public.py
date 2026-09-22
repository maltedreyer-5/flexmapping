# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Public API Endpoints - Read-only access to published content
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ConfigDict, BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.database import get_async_session
from app.models import (
    Source, Extraction, Steckbrief, Category, Entity
)
from app.repositories import (
    CategoryRepository, ExtractionRepository,
    SourceRepository, SteckbriefRepository
)

logger = structlog.get_logger()
router = APIRouter()


# Pydantic Models

class CategoryResponse(BaseModel):
    """Category response"""
    id: int
    internal_name: str
    display_name: str
    source_count: int
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SteckbriefSummary(BaseModel):
    """Profile summary, for list views"""
    id: int
    source_id: UUID
    source_url: str
    title: str
    category: str
    institution: Optional[str]
    short_description: Optional[str]
    published_at: datetime


class SteckbriefDetail(BaseModel):
    """Full steckbrief detail"""
    id: int
    source_id: UUID
    source_url: str
    markdown_content: str
    html_content: Optional[str]
    generated_at: datetime
    published_at: datetime


class SearchIndexItem(BaseModel):
    """Item for client-side search index"""
    id: UUID
    title: str
    description: str
    category: str
    institution: str
    url: str
    relevance_text: str  # Combined text for search


class StatisticsResponse(BaseModel):
    """Public statistics"""
    total_sources: int
    sources_by_category: dict
    recent_additions: int  # Last 30 days


# Public Endpoints

@router.get("/categories", response_model=List[CategoryResponse])
async def list_categories(
    session: AsyncSession = Depends(get_async_session)
):
    """
    List all active categories
    """
    category_repo = CategoryRepository(Category, session)
    source_repo = SourceRepository(Source, session)

    categories = await category_repo.list_all(active_only=True)

    result = []
    for category in categories:
        count = await source_repo.count_by_category(category.id, status="completed")
        result.append({
            "id": category.id,
            "internal_name": category.internal_name,
            "display_name": category.display_name,
            "source_count": count,
            "is_active": category.is_active
        })

    return result


@router.get("/steckbriefe", response_model=List[SteckbriefSummary])
async def list_steckbriefe(
    category: Optional[str] = Query(None, description="Filter by category internal_name"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session)
):
    """
    List published steckbriefe
    """
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    source_repo = SourceRepository(Source, session)
    extraction_repo = ExtractionRepository(Extraction, session)
    category_repo = CategoryRepository(Category, session)

    # Get published steckbriefe
    steckbriefe = await steckbrief_repo.list_published(
        limit=limit,
        offset=offset
    )

    result = []
    for steckbrief in steckbriefe:
        # Get source
        source = await source_repo.get(steckbrief.source_id)
        if not source:
            continue

        # Get category
        category_obj = await category_repo.get(source.category_id)

        # Get key extractions for summary
        extractions = await extraction_repo.get_by_source(source.id)

        # Extract title, institution, description
        title = "Untitled"
        institution = None
        description = None

        for ext in extractions:
            if ext.prompt.internal_name == "project_name" or ext.prompt.internal_name == "service_name":
                title = ext.validated_result or title
            elif ext.prompt.internal_name == "institution":
                institution = ext.validated_result
            elif ext.prompt.internal_name == "description" or ext.prompt.internal_name == "short_description":
                description = ext.validated_result

        result.append(SteckbriefSummary(
            id=steckbrief.id,
            source_id=source.id,
            source_url=source.url,
            title=title,
            category=category_obj.display_name if category_obj else "Unknown",
            institution=institution,
            short_description=description[:200] if description else None,
            published_at=steckbrief.published_at
        ))

    return result


@router.get("/steckbriefe/{steckbrief_id}", response_model=SteckbriefDetail)
async def get_steckbrief(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get full steckbrief by ID
    """
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    source_repo = SourceRepository(Source, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)

    if not steckbrief or not steckbrief.published:
        raise HTTPException(status_code=404, detail="Steckbrief not found or not published")

    source = await source_repo.get(steckbrief.source_id)

    return SteckbriefDetail(
        id=steckbrief.id,
        source_id=steckbrief.source_id,
        source_url=source.url if source else "",
        markdown_content=steckbrief.markdown_content,
        html_content=steckbrief.html_content,
        generated_at=steckbrief.generated_at,
        published_at=steckbrief.published_at
    )


@router.get("/steckbriefe/by-source/{source_id}", response_model=SteckbriefDetail)
async def get_steckbrief_by_source(
    source_id: UUID,
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get steckbrief by source ID
    """
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    source_repo = SourceRepository(Source, session)

    steckbrief = await steckbrief_repo.get_by_source(source_id)

    if not steckbrief or not steckbrief.published:
        raise HTTPException(status_code=404, detail="Steckbrief not found or not published")

    source = await source_repo.get(source_id)

    return SteckbriefDetail(
        id=steckbrief.id,
        source_id=steckbrief.source_id,
        source_url=source.url if source else "",
        markdown_content=steckbrief.markdown_content,
        html_content=steckbrief.html_content,
        generated_at=steckbrief.generated_at,
        published_at=steckbrief.published_at
    )


@router.get("/search-index", response_model=List[SearchIndexItem])
async def get_search_index(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get search index for client-side search
    """
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    source_repo = SourceRepository(Source, session)
    extraction_repo = ExtractionRepository(Extraction, session)
    category_repo = CategoryRepository(Category, session)

    # Get all published steckbriefe
    steckbriefe = await steckbrief_repo.list_published(limit=1000)

    result = []
    for steckbrief in steckbriefe:
        # Get source
        source = await source_repo.get(steckbrief.source_id)
        if not source:
            continue

        # Get category
        category = await category_repo.get(source.category_id)

        # Get extractions
        extractions = await extraction_repo.get_by_source(source.id)

        # Build search-relevant text
        title = "Untitled"
        institution = ""
        description = ""

        for ext in extractions:
            if ext.validated_result and ext.final_confidence and ext.final_confidence >= ext.prompt.required_confidence:
                if ext.prompt.internal_name in ["project_name", "service_name"]:
                    title = ext.validated_result
                elif ext.prompt.internal_name == "institution":
                    institution = ext.validated_result
                elif ext.prompt.internal_name in ["description", "short_description"]:
                    description = ext.validated_result

        # Combined relevance text for search
        relevance_text = f"{title} {institution} {description} {category.display_name if category else ''}"

        result.append(SearchIndexItem(
            id=source.id,
            title=title,
            description=description[:300] if description else "",
            category=category.display_name if category else "Unknown",
            institution=institution,
            url=source.url,
            relevance_text=relevance_text
        ))

    return result


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get public statistics
    """
    source_repo = SourceRepository(Source, session)
    category_repo = CategoryRepository(Category, session)

    # Total completed sources
    total_sources = await source_repo.count_by_status("completed")

    # Sources by category
    categories = await category_repo.list_all(active_only=True)
    sources_by_category = {}

    for category in categories:
        count = await source_repo.count_by_category(category.id, status="completed")
        sources_by_category[category.display_name] = count

    # Recent additions (last 30 days)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
    recent_additions = await source_repo.count_since(cutoff_date, status="completed")

    return StatisticsResponse(
        total_sources=total_sources,
        sources_by_category=sources_by_category,
        recent_additions=recent_additions
    )


@router.get("/health")
async def public_health_check():
    """
    Public health check endpoint
    """
    return {
        "status": "healthy",
        "service": "FlexMapping Public API",
        "version": __version__
    }
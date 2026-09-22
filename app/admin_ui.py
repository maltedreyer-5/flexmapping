# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Admin UI router: server-rendered HTML pages driven by htmx.

SQLAlchemy objects are converted to plain dicts before they reach a template.
Rendering the ORM objects directly works until a template touches a
relationship that was not loaded, at which point the session is already
closed and the page fails halfway through rendering.
"""
import structlog
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, update as sql_update
from uuid import UUID
from datetime import datetime, timezone

from app.database import get_async_session
from app.models import (
    Source, Prompt, Category, Extraction, Entity,
    EntityNormalizationQueue, Steckbrief, SteckbriefTranslation
)
from app.repositories import (
    CategoryRepository, EntityRepository, ExtractionRepository,
    PromptRepository, SourceRepository, SteckbriefRepository
)
from app.services.job_queue import get_job_queue

logger = structlog.get_logger()
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ========================================
# CUSTOM JINJA2 FILTERS
# ========================================

def format_datetime(value, format='%Y-%m-%d %H:%M:%S'):
    """
    Format a datetime or an ISO string for display.

    Accepts both, because values reaching a template come from the ORM as
    datetime objects and from JSON payloads as strings, and None has to render
    as an empty cell rather than raise.
    """
    if value is None:
        return 'N/A'

    if isinstance(value, str):
        try:
            return value[:19].replace('T', ' ')
        except:
            return value

    if hasattr(value, 'strftime'):
        try:
            return value.strftime(format)
        except:
            return str(value)

    return str(value)


templates.env.filters['datetime'] = format_datetime


# ========================================
# HELPER FUNCTIONS FOR JSON SERIALIZATION
# ========================================

def to_dict(obj, *exclude_fields):
    """Convert SQLAlchemy object to dictionary for JSON serialization"""
    if obj is None:
        return None

    result = {}
    for column in obj.__table__.columns:
        if column.name not in exclude_fields:
            value = getattr(obj, column.name)

            if value is None:
                result[column.name] = None
            elif isinstance(value, (str, int, float, bool)):
                result[column.name] = value
            elif isinstance(value, (dict, list)):
                result[column.name] = value
            elif hasattr(value, 'isoformat'):
                result[column.name] = value.isoformat()
            else:
                result[column.name] = str(value)

    return result


def prepare_source_for_template(source):
    """Prepare source with nested category for template"""
    source_data = to_dict(source)
    if source.category:
        source_data['category'] = to_dict(source.category)
    return source_data


def prepare_extraction_for_template(extraction):
    """Prepare extraction with nested source and prompt for template"""
    ext_data = to_dict(extraction)
    if extraction.source:
        ext_data['source'] = to_dict(extraction.source)
        if extraction.source.category:
            ext_data['source']['category'] = to_dict(extraction.source.category)
    if extraction.prompt:
        ext_data['prompt'] = to_dict(extraction.prompt)
    return ext_data


def prepare_entity_for_template(entity):
    """Prepare entity with variants for template"""
    entity_data = to_dict(entity)
    entity_data['variants'] = [to_dict(v) for v in entity.variants]
    return entity_data


# ========================================
# ADMIN UI ROUTES
# ========================================

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    session: AsyncSession = Depends(get_async_session)
):
    """Admin dashboard: counts, queue state and profile statistics"""
    from app.models import SteckbriefTranslation, Category, Entity, EntityVariant
    import hashlib
    
    source_repo = SourceRepository(Source, session)
    extraction_repo = ExtractionRepository(Extraction, session)
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    job_queue = await get_job_queue()

    total_result = await session.execute(
        select(func.count()).select_from(Source)
    )
    total_sources = total_result.scalar()

    completed_sources = await source_repo.count_by_status("completed")
    pending_sources = await source_repo.count_by_status("pending")
    crawled_sources = await source_repo.count_by_status("crawled")
    extracting_sources = await source_repo.count_by_status("extracting")
    failed_sources = await source_repo.count_by_status("failed")

    low_confidence = await extraction_repo.get_low_confidence(threshold=0.7, limit=1)
    low_confidence_count = len(low_confidence)

    # === STECKBRIEF STATISTICS ===
    # Total Steckbriefe
    total_steckbriefe_result = await session.execute(
        select(func.count()).select_from(Steckbrief)
    )
    total_steckbriefe = total_steckbriefe_result.scalar() or 0
    
    # Published Steckbriefe
    published_count_result = await session.execute(
        select(func.count()).select_from(Steckbrief).where(Steckbrief.published == True)
    )
    published_steckbriefe_count = published_count_result.scalar() or 0
    
    # Unpublished Steckbriefe
    unpublished_steckbriefe = total_steckbriefe - published_steckbriefe_count
    
    # === TRANSLATION STATISTICS ===
    # Count every profile, not only the published ones, for the translation statistics
    all_steckbriefe_result = await session.execute(
        select(Steckbrief)
    )
    all_steckbriefe_for_trans = all_steckbriefe_result.scalars().all()
    
    trans_result = await session.execute(
        select(SteckbriefTranslation).where(SteckbriefTranslation.language == 'en')
    )
    translations = {t.steckbrief_id: t for t in trans_result.scalars().all()}
    
    translation_stats = {
        "total": len(all_steckbriefe_for_trans),
        "translated": 0,
        "pending": 0,
        "outdated": 0
    }
    
    for steckbrief in all_steckbriefe_for_trans:
        translation = translations.get(steckbrief.id)
        if not translation:
            translation_stats["pending"] += 1
        else:
            current_hash = hashlib.sha256(
                (steckbrief.markdown_content or "").encode('utf-8')
            ).hexdigest()
            if translation.source_hash != current_hash:
                translation_stats["outdated"] += 1
            else:
                translation_stats["translated"] += 1

    # === ENTITY STATISTICS ===
    # Total entities
    entity_count_result = await session.execute(
        select(func.count()).select_from(Entity)
    )
    total_entities = entity_count_result.scalar() or 0
    
    # Total variants
    variant_count_result = await session.execute(
        select(func.count()).select_from(EntityVariant)
    )
    total_variants = variant_count_result.scalar() or 0
    
    # Linked extractions
    linked_extractions_result = await session.execute(
        select(func.count()).select_from(Extraction).where(
            Extraction.linked_entity_id.is_not(None)
        )
    )
    linked_extractions = linked_extractions_result.scalar() or 0
    
    # Total extractions
    total_extractions_result = await session.execute(
        select(func.count()).select_from(Extraction)
    )
    total_extractions = total_extractions_result.scalar() or 0
    
    # === CATEGORY STATISTICS ===
    category_stats_result = await session.execute(
        select(
            Category.display_name,
            func.count(Source.id).label('source_count')
        )
        .join(Source, Source.category_id == Category.id, isouter=True)
        .group_by(Category.id, Category.display_name)
        .order_by(func.count(Source.id).desc())
    )
    category_stats = [
        {"name": row[0], "count": row[1]} 
        for row in category_stats_result.fetchall()
    ]
    
    # === QUALITY STATISTICS ===
    # Average confidence
    avg_confidence_result = await session.execute(
        select(func.avg(Extraction.final_confidence)).where(
            Extraction.final_confidence.is_not(None)
        )
    )
    avg_confidence = avg_confidence_result.scalar() or 0
    
    # Extractions with validation
    validated_extractions_result = await session.execute(
        select(func.count()).select_from(Extraction).where(
            Extraction.validated_result.is_not(None),
            Extraction.validated_result != ''
        )
    )
    validated_extractions = validated_extractions_result.scalar() or 0

    # Get active jobs (pending + running)
    try:
        active_jobs = await job_queue.get_all_active_jobs()
        pending_jobs = active_jobs['pending_count']
        running_jobs = active_jobs['running_count']
        job_list = active_jobs['running'] + active_jobs['pending']
    except Exception as e:
        logger.warning("Failed to get active jobs", error=str(e))
        pending_jobs = 0
        running_jobs = 0
        job_list = []

    context = {
        "request": request,
        "stats": {
            "total_sources": total_sources,
            "completed_sources": completed_sources,
            "pending_sources": pending_sources + crawled_sources + extracting_sources,
            "failed_sources": failed_sources,
            "low_confidence_count": low_confidence_count,
            "low_confidence": low_confidence_count,  # Alias used by the template
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
            "unpublished_steckbriefe": unpublished_steckbriefe,
            # New stats
            "total_steckbriefe": total_steckbriefe,
            "published_steckbriefe": published_steckbriefe_count,
            "total_extractions": total_extractions,
            "validated_extractions": validated_extractions,
            "linked_extractions": linked_extractions,
            "total_entities": total_entities,
            "total_variants": total_variants,
            "avg_confidence": round(avg_confidence * 100, 1) if avg_confidence else 0,
        },
        "translation_stats": translation_stats,
        "category_stats": category_stats,
        "entity_stats": {
            "total": total_entities,
            "variants": total_variants
        },
        "active_jobs": job_list[:20]  # Limit to 20 jobs for display
    }

    return templates.TemplateResponse("dashboard.html", context)


@router.post("/publish-all-steckbriefe")
async def publish_all_steckbriefe_ui(
    session: AsyncSession = Depends(get_async_session)
):
    """Publish all unpublished steckbriefe - UI endpoint"""
    try:
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
            "bulk_publish_completed_via_ui",
            steckbriefe_published=count
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"{count} Steckbriefe published",
                "count": count
            }
        )

    except Exception as e:
        logger.error("bulk_publish_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.get("/sources", response_class=HTMLResponse)
async def admin_sources(
    request: Request,
    status: str = None,
    category_id: int = None,
    session: AsyncSession = Depends(get_async_session)
):
    """Source Management Page"""
    source_repo = SourceRepository(Source, session)
    category_repo = CategoryRepository(Category, session)

    sources = await source_repo.list_sources(
        status=status,
        category_id=category_id,
        limit=50
    )

    categories = await category_repo.list_all(active_only=True)

    sources_data = [prepare_source_for_template(s) for s in sources]
    categories_data = [to_dict(c) for c in categories]

    context = {
        "request": request,
        "sources": sources_data,
        "categories": categories_data,
        "current_status": status,
        "current_category": category_id
    }

    return templates.TemplateResponse("sources.html", context)


@router.delete("/sources/{source_id}")
async def delete_source_ui(
    source_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    """Delete source - UI endpoint"""
    source_repo = SourceRepository(Source, session)
    extraction_repo = ExtractionRepository(Extraction, session)

    try:
        source = await source_repo.get(UUID(source_id))
        if not source:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Source nicht gefunden"}
            )

        extractions = await extraction_repo.get_by_source(UUID(source_id))
        extraction_count = len(extractions)

        await source_repo.delete_obj(source)
        await session.commit()

        logger.info(
            "source_deleted_via_ui",
            source_id=source_id,
            url=source.url,
            extractions_deleted=extraction_count
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Source gelöscht ({extraction_count} Extractions entfernt)",
                "source_id": source_id
            }
        )

    except Exception as e:
        logger.error("delete_source_ui_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.post("/sources/bulk-delete")
async def bulk_delete_sources(
    request: Request,
    session: AsyncSession = Depends(get_async_session)
):
    """Bulk delete sources - UI endpoint"""
    try:
        data = await request.json()
        source_ids = data.get("source_ids", [])

        if not source_ids:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Keine Source-IDs angegeben"}
            )

        source_repo = SourceRepository(Source, session)

        deleted_count = 0
        errors = []

        for source_id_str in source_ids:
            try:
                source_id = UUID(source_id_str)
                source = await source_repo.get(source_id)

                if source:
                    await source_repo.delete_obj(source)
                    deleted_count += 1
                else:
                    errors.append(f"Source {source_id_str} nicht gefunden")

            except Exception as e:
                errors.append(f"Fehler bei {source_id_str}: {str(e)}")
                logger.error("bulk_delete_single_error", source_id=source_id_str, error=str(e))

        await session.commit()

        logger.info(
            "bulk_delete_completed",
            deleted_count=deleted_count,
            total_requested=len(source_ids),
            errors_count=len(errors)
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "deleted_count": deleted_count,
                "total_requested": len(source_ids),
                "errors": errors
            }
        )

    except Exception as e:
        logger.error("bulk_delete_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.get("/sources/{source_id}/extractions", response_class=HTMLResponse)
async def source_extractions_page(
    request: Request,
    source_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    """Extractions page for a specific source"""
    extraction_repo = ExtractionRepository(Extraction, session)

    result = await session.execute(
        select(Source)
        .where(Source.id == UUID(source_id))
        .options(selectinload(Source.category))
    )
    source = result.scalar_one_or_none()

    if not source:
        return HTMLResponse(content="Source not found", status_code=404)

    extractions = await extraction_repo.get_by_source(UUID(source_id))

    extractions_sorted = sorted(
        extractions,
        key=lambda e: (e.prompt.field_group, e.prompt.internal_name)
    )

    source_data = prepare_source_for_template(source)
    extractions_data = [prepare_extraction_for_template(e) for e in extractions_sorted]

    context = {
        "request": request,
        "source": source_data,
        "extractions": extractions_data
    }

    return templates.TemplateResponse("extractions.html", context)


@router.get("/prompts", response_class=HTMLResponse)
async def admin_prompts(
    request: Request,
    category_id: int = None,
    session: AsyncSession = Depends(get_async_session)
):
    """Prompt Management Page"""
    prompt_repo = PromptRepository(Prompt, session)
    category_repo = CategoryRepository(Category, session)

    if category_id:
        prompts = await prompt_repo.get_by_category(category_id, active_only=False)
    else:
        prompts = await prompt_repo.list_all(active_only=False)

    categories = await category_repo.list_all(active_only=True)

    prompts_data = []
    for p in prompts:
        prompt_dict = {
            'id': p.id,
            'internal_name': p.internal_name,
            'display_name': p.display_name,
            'extract_prompt': p.extract_prompt,
            'validate_prompt': p.validate_prompt,
            'field_type': p.field_type,
            'field_group': p.field_group,
            'entity_type': p.entity_type,
            'required_confidence': float(p.required_confidence),
            'max_retries': p.max_retries,
            'is_active': p.is_active,
            'created_at': p.created_at.isoformat() if p.created_at else None,
            'updated_at': p.updated_at.isoformat() if p.updated_at else None
        }
        prompts_data.append(prompt_dict)

    categories_data = []
    for c in categories:
        cat_dict = {
            'id': c.id,
            'internal_name': c.internal_name,
            'display_name': c.display_name,
            'is_active': c.is_active
        }
        categories_data.append(cat_dict)

    logger.info(
        "admin_prompts_page",
        prompts_count=len(prompts_data),
        categories_count=len(categories_data),
        first_prompt=prompts_data[0] if prompts_data else None
    )

    context = {
        "request": request,
        "prompts": prompts_data,
        "categories": categories_data,
        "current_category": category_id
    }

    return templates.TemplateResponse("prompts.html", context)


@router.get("/categories/{category_id}/manage", response_class=HTMLResponse)
async def manage_category_prompts(
    request: Request,
    category_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Category Detail Page - Manage Prompt Assignments"""
    category_repo = CategoryRepository(Category, session)
    prompt_repo = PromptRepository(Prompt, session)
    source_repo = SourceRepository(Source, session)

    category = await category_repo.get(category_id)
    if not category:
        return HTMLResponse(content="Category not found", status_code=404)

    assigned_prompts = await prompt_repo.get_by_category(category_id, active_only=False)

    all_prompts = await prompt_repo.list_all(active_only=True)

    assigned_ids = {p.id for p in assigned_prompts}
    available_prompts = [p for p in all_prompts if p.id not in assigned_ids]

    source_count = await source_repo.count_by_category(category_id)

    category_data = to_dict(category)
    assigned_prompts_data = [to_dict(p) for p in assigned_prompts]
    available_prompts_data = [to_dict(p) for p in available_prompts]

    context = {
        "request": request,
        "category": category_data,
        "assigned_prompts": assigned_prompts_data,
        "available_prompts": available_prompts_data,
        "source_count": source_count
    }

    return templates.TemplateResponse("category_detail.html", context)


@router.get("/categories", response_class=HTMLResponse)
async def admin_categories(
    request: Request,
    session: AsyncSession = Depends(get_async_session)
):
    """Category Management Page"""
    category_repo = CategoryRepository(Category, session)
    source_repo = SourceRepository(Source, session)

    categories = await category_repo.list_all(active_only=False)

    categories_with_counts = []
    for category in categories:
        count = await source_repo.count_by_category(category.id)
        categories_with_counts.append({
            "category": to_dict(category),
            "source_count": count
        })

    context = {
        "request": request,
        "categories": categories_with_counts
    }

    return templates.TemplateResponse("categories.html", context)


@router.get("/entities", response_class=HTMLResponse)
async def admin_entities(
    request: Request,
    entity_type: str = None,
    session: AsyncSession = Depends(get_async_session)
):
    """Entity Management Page"""
    entity_repo = EntityRepository(Entity, session)

    if entity_type:
        entities = await entity_repo.get_by_type(entity_type)
    else:
        entities = await entity_repo.list_all()

    norm_queue = await entity_repo.get_normalization_queue(status="pending", limit=20)

    entities_data = [prepare_entity_for_template(e) for e in entities]

    norm_queue_data = []
    for q in norm_queue:
        q_dict = to_dict(q)
        if q.extraction:
            q_dict['extraction'] = to_dict(q.extraction)
            if q.extraction.source:
                q_dict['extraction']['source'] = to_dict(q.extraction.source)
        if q.llm_suggestion_entity:
            q_dict['llm_suggestion_entity'] = to_dict(q.llm_suggestion_entity)
        norm_queue_data.append(q_dict)

    context = {
        "request": request,
        "entities": entities_data,
        "norm_queue": norm_queue_data,
        "current_type": entity_type
    }

    return templates.TemplateResponse("entities.html", context)


@router.get("/review", response_class=HTMLResponse)
async def admin_review_queue(
    request: Request,
    session: AsyncSession = Depends(get_async_session)
):
    """Review queue page: extractions below their required confidence"""
    extraction_repo = ExtractionRepository(Extraction, session)
    entity_repo = EntityRepository(Entity, session)

    try:
        low_confidence = await extraction_repo.get_low_confidence(threshold=0.7, limit=50)

        entity_queue = await entity_repo.get_normalization_queue(status="pending", limit=50)

        low_confidence_data = [prepare_extraction_for_template(e) for e in low_confidence]

        entity_queue_data = []
        for q in entity_queue:
            q_dict = to_dict(q)

            if q.extraction:
                extraction_dict = to_dict(q.extraction)

                if q.extraction.source:
                    extraction_dict['source'] = to_dict(q.extraction.source)

                    if q.extraction.source.category:
                        extraction_dict['source']['category'] = to_dict(q.extraction.source.category)

                if q.extraction.prompt:
                    extraction_dict['prompt'] = to_dict(q.extraction.prompt)

                q_dict['extraction'] = extraction_dict

            if q.llm_suggestion_entity:
                entity_dict = to_dict(q.llm_suggestion_entity)
                entity_dict['variants'] = [
                    to_dict(v) for v in q.llm_suggestion_entity.variants
                ]
                q_dict['llm_suggestion_entity'] = entity_dict

            entity_queue_data.append(q_dict)

        context = {
            "request": request,
            "low_confidence": low_confidence_data,
            "entity_queue": entity_queue_data
        }

        return templates.TemplateResponse("review.html", context)

    except Exception as e:
        logger.error("review_queue_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# STECKBRIEF MANAGEMENT ROUTES
# ========================================

@router.get("/steckbriefe", response_class=HTMLResponse)
async def admin_steckbriefe(
    request: Request,
    status: str = None,
    category_id: int = None,
    session: AsyncSession = Depends(get_async_session)
):
    """Profile management page"""
    category_repo = CategoryRepository(Category, session)

    # Load steckbriefe with eager loading of source and category
    if status == 'published':
        query = (
            select(Steckbrief)
            .where(Steckbrief.published == True)
            .options(
                selectinload(Steckbrief.source).selectinload(Source.category)
            )
            .limit(100)
        )
    elif status == 'unpublished':
        query = (
            select(Steckbrief)
            .where(Steckbrief.published == False)
            .options(
                selectinload(Steckbrief.source).selectinload(Source.category)
            )
            .limit(100)
        )
    else:
        query = (
            select(Steckbrief)
            .options(
                selectinload(Steckbrief.source).selectinload(Source.category)
            )
            .limit(100)
        )

    result = await session.execute(query)
    steckbriefe = list(result.scalars().all())

    # Filter by category if specified
    if category_id:
        steckbriefe = [s for s in steckbriefe
                      if s.source.category_id == category_id]

    # Load categories for filter
    categories = await category_repo.list_all(active_only=True)

    # Calculate statistics - also with eager loading
    total_query = (
        select(Steckbrief)
        .options(selectinload(Steckbrief.source).selectinload(Source.category))
        .limit(1000)
    )
    total_result = await session.execute(total_query)
    all_steckbriefe = list(total_result.scalars().all())

    total_count = len(all_steckbriefe)
    published_count = sum(1 for s in all_steckbriefe if s.published)
    unpublished_count = total_count - published_count

    # Prepare data for template
    steckbriefe_data = []
    for s in steckbriefe:
        # Extract title from markdown
        title = "Untitled"
        institution = ""
        
        if s.markdown_content:
            import re
            lines = s.markdown_content.split('\n')
            
            # Extract title from first H1 line
            first_line = lines[0] if lines else ""
            if first_line.startswith('#'):
                title = first_line.lstrip('#').strip()
            
            # Extract institution from markdown
            for line in lines[:15]:
                if 'Institution' in line and ':' in line:
                    institution = line.split(':', 1)[-1].strip()
                    institution = re.sub(r'\*+', '', institution).strip()
                    if institution in ['Nicht angegeben', '-']:
                        institution = ""
                    break

        steckbrief_dict = to_dict(s)
        steckbrief_dict['title'] = title
        steckbrief_dict['institution'] = institution
        steckbrief_dict['source'] = prepare_source_for_template(s.source)
        steckbriefe_data.append(steckbrief_dict)

    categories_data = [to_dict(c) for c in categories]

    # Get active jobs for display (filter for translate jobs)
    try:
        job_queue = await get_job_queue()
        active_jobs_data = await job_queue.get_all_active_jobs()
        # Translation jobs only
        translate_jobs = [
            j for j in (active_jobs_data['running'] + active_jobs_data['pending'])
            if j.job_type == 'translate'
        ]
        translate_pending = len([j for j in translate_jobs if j.status == 'pending'])
        translate_running = len([j for j in translate_jobs if j.status == 'running'])
    except Exception as e:
        logger.warning("Failed to get active jobs for steckbriefe", error=str(e))
        translate_jobs = []
        translate_pending = 0
        translate_running = 0

    # Translation statistics
    trans_result = await session.execute(
        select(SteckbriefTranslation).where(SteckbriefTranslation.language == 'en')
    )
    translations = {t.steckbrief_id: t for t in trans_result.scalars().all()}
    
    translated_count = 0
    pending_translation_count = 0
    for s in all_steckbriefe:
        if s.id in translations:
            translated_count += 1
        else:
            pending_translation_count += 1

    context = {
        "request": request,
        "steckbriefe": steckbriefe_data,
        "categories": categories_data,
        "current_status": status,
        "current_category": category_id,
        "stats": {
            "total": total_count,
            "published": published_count,
            "unpublished": unpublished_count,
            "translated": translated_count,
            "pending_translation": pending_translation_count
        },
        "active_jobs": translate_jobs[:20],
        "job_stats": {
            "pending": translate_pending,
            "running": translate_running
        }
    }

    return templates.TemplateResponse("steckbriefe.html", context)


@router.get("/steckbriefe/{steckbrief_id}", response_class=HTMLResponse)
async def steckbrief_detail(
    request: Request,
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Profile detail page, with a preview"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)
    extraction_repo = ExtractionRepository(Extraction, session)

    steckbrief = await steckbrief_repo.get(steckbrief_id)
    if not steckbrief:
        return HTMLResponse(content="Steckbrief not found", status_code=404)

    # Load source with category
    result = await session.execute(
        select(Source)
        .where(Source.id == steckbrief.source_id)
        .options(selectinload(Source.category))
    )
    source = result.scalar_one_or_none()

    # Load extractions for metadata
    extractions = await extraction_repo.get_by_source(steckbrief.source_id)

    # Prepare data
    steckbrief_data = to_dict(steckbrief)
    steckbrief_data['source'] = prepare_source_for_template(source)

    extractions_data = [prepare_extraction_for_template(e) for e in extractions]

    context = {
        "request": request,
        "steckbrief": steckbrief_data,
        "extractions": extractions_data
    }

    return templates.TemplateResponse("steckbrief_detail.html", context)


@router.post("/steckbriefe/{steckbrief_id}/publish")
async def publish_steckbrief_ui(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Publish steckbrief - UI endpoint"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    try:
        steckbrief = await steckbrief_repo.get(steckbrief_id)
        if not steckbrief:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Steckbrief nicht gefunden"}
            )

        await steckbrief_repo.publish(steckbrief_id)
        await session.commit()

        logger.info(
            "steckbrief_published_via_ui",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Steckbrief veröffentlicht",
                "steckbrief_id": steckbrief_id
            }
        )

    except Exception as e:
        logger.error("publish_steckbrief_ui_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.post("/steckbriefe/{steckbrief_id}/unpublish")
async def unpublish_steckbrief_ui(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Unpublish steckbrief - UI endpoint"""
    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    try:
        steckbrief = await steckbrief_repo.get(steckbrief_id)
        if not steckbrief:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Steckbrief nicht gefunden"}
            )

        steckbrief.published = False
        steckbrief.published_at = None
        await session.commit()

        logger.info(
            "steckbrief_unpublished_via_ui",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Steckbrief zurückgezogen",
                "steckbrief_id": steckbrief_id
            }
        )

    except Exception as e:
        logger.error("unpublish_steckbrief_ui_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.post("/steckbriefe/{steckbrief_id}/regenerate")
async def regenerate_steckbrief_ui(
    steckbrief_id: int,
    session: AsyncSession = Depends(get_async_session)
):
    """Regenerate steckbrief - UI endpoint"""
    from app.services.steckbrief_generator import SteckbriefGenerator

    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    try:
        steckbrief = await steckbrief_repo.get(steckbrief_id)
        if not steckbrief:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": "Steckbrief nicht gefunden"}
            )

        # Regenerate
        generator = SteckbriefGenerator(session)
        updated = await generator.generate(steckbrief.source_id)
        await session.commit()

        logger.info(
            "steckbrief_regenerated_via_ui",
            steckbrief_id=steckbrief_id,
            source_id=str(steckbrief.source_id)
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Steckbrief neu generiert",
                "steckbrief_id": updated.id
            }
        )

    except Exception as e:
        logger.error("regenerate_steckbrief_ui_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@router.post("/steckbriefe/generate-all")
async def generate_all_steckbriefe(
    session: AsyncSession = Depends(get_async_session)
):
    """Generate profiles for every completed source that has none yet"""
    from app.services.steckbrief_generator import SteckbriefGenerator

    steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    try:
        # Get all completed sources with eager loading
        query = (
            select(Source)
            .where(Source.status == "completed")
            .options(selectinload(Source.category))
            .limit(1000)
        )
        result = await session.execute(query)
        completed_sources = list(result.scalars().all())

        generated_count = 0
        skipped_count = 0
        error_count = 0

        generator = SteckbriefGenerator(session)

        for source in completed_sources:
            try:
                # Check if steckbrief already exists
                existing = await steckbrief_repo.get_by_source(source.id)
                if existing:
                    skipped_count += 1
                    continue

                # Generate new steckbrief
                await generator.generate(source.id)
                generated_count += 1

                # Commit after each successful generation
                await session.commit()

            except Exception as e:
                logger.error(
                    "failed_to_generate_steckbrief",
                    source_id=str(source.id),
                    error=str(e)
                )
                error_count += 1
                await session.rollback()

        logger.info(
            "bulk_steckbrief_generation_completed",
            generated=generated_count,
            skipped=skipped_count,
            errors=error_count
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"{generated_count} Steckbriefe generiert",
                "generated": generated_count,
                "skipped": skipped_count,
                "errors": error_count
            }
        )

    except Exception as e:
        logger.error("bulk_generation_error", error=str(e), exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


# ========================================
# HTMX COMPONENTS (for partial updates)
# ========================================

@router.get("/components/source-card/{source_id}", response_class=HTMLResponse)
async def source_card_component(
    request: Request,
    source_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    """Render source card component (for htmx updates)"""
    source_repo = SourceRepository(Source, session)
    extraction_repo = ExtractionRepository(Extraction, session)

    source = await source_repo.get(UUID(source_id))
    if not source:
        return HTMLResponse(content="Source not found", status_code=404)

    extractions = await extraction_repo.get_by_source(source.id)

    source_data = prepare_source_for_template(source)
    extractions_data = [prepare_extraction_for_template(e) for e in extractions]

    context = {
        "request": request,
        "source": source_data,
        "extractions": extractions_data
    }

    return templates.TemplateResponse("components/source_card.html", context)


@router.get("/components/job-status", response_class=HTMLResponse)
async def job_status_component(
    request: Request
):
    """Render job status component (for live updates via htmx polling)"""
    job_queue = await get_job_queue()

    pending_jobs = await job_queue.get_queue_size()

    context = {
        "request": request,
        "pending_jobs": pending_jobs
    }

    return templates.TemplateResponse("components/job_status.html", context)

# ============================================
# CONFIG PAGE
# ============================================

@router.get("/config", response_class=HTMLResponse)
async def admin_config(
    request: Request,
    session: AsyncSession = Depends(get_async_session)
):
    """Config management page"""
    from sqlalchemy import func, select
    from app.models import Category, CategoryPrompt, Source
    
    # Get categories with counts
    result = await session.execute(
        select(
            Category,
            func.count(CategoryPrompt.id.distinct()).label('prompt_count'),
            func.count(Source.id.distinct()).label('source_count')
        )
        .outerjoin(CategoryPrompt, Category.id == CategoryPrompt.category_id)
        .outerjoin(Source, Category.id == Source.category_id)
        .group_by(Category.id)
        .order_by(Category.display_name)
    )
    rows = result.fetchall()
    
    categories = []
    for cat, prompt_count, source_count in rows:
        categories.append({
            'id': cat.id,
            'internal_name': cat.internal_name,
            'display_name': cat.display_name,
            'is_active': cat.is_active,
            'prompt_count': prompt_count or 0,
            'source_count': source_count or 0
        })
    
    return templates.TemplateResponse("config.html", {
        "request": request,
        "categories": categories
    })

# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Recovery endpoints for sources and jobs that are stuck mid-pipeline.

When the LLM backend or the worker pool fails partway through, sources can be
left in 'pending', 'crawled' or 'extracting' with no job in the queue to move
them on. These endpoints re-enqueue that work without touching results that
already exist.

All routes require the admin role: re-enqueueing costs LLM calls, and
clear-stuck-jobs discards queue entries.
"""
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_async_session
from app.models import Extraction, Source
from app.repositories import ExtractionRepository, SourceRepository
from app.services.job_queue import JobPriority, JobType, get_job_queue

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_admin)])


@router.post("/recovery/requeue-pending-sources")
async def requeue_pending_sources(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Requeue all sources that are stuck in 'pending' status.
    Creates new CRAWL jobs for them.
    """
    from sqlalchemy import select
    
    source_repo = SourceRepository(Source, session)
    job_queue = await get_job_queue()
    
    # Find every source with status 'pending'
    result = await session.execute(
        select(Source).where(Source.status == 'pending')
    )
    pending_sources = result.scalars().all()
    
    jobs_created = 0
    source_ids = []
    
    for source in pending_sources:
        await job_queue.enqueue(
            job_type=JobType.CRAWL,
            source_id=str(source.id),
            priority=JobPriority.CRAWL,
            payload={"url": source.url}
        )
        jobs_created += 1
        source_ids.append(str(source.id))
    
    logger.info(
        "requeue_pending_sources",
        sources_found=len(pending_sources),
        jobs_created=jobs_created
    )
    
    return {
        "message": f"Requeued {jobs_created} pending sources",
        "sources_requeued": jobs_created,
        "source_ids": source_ids[:20]  # First 20 ids, for information
    }


@router.post("/recovery/requeue-crawled-sources")
async def requeue_crawled_sources(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Requeue all sources that are stuck in 'crawled' status (extraction never started).
    Creates new EXTRACT jobs for them.
    """
    from sqlalchemy import select
    
    source_repo = SourceRepository(Source, session)
    prompt_repo = PromptRepository(Prompt, session)
    job_queue = await get_job_queue()
    
    # Find every source with status 'crawled'
    result = await session.execute(
        select(Source).where(Source.status == 'crawled')
    )
    crawled_sources = result.scalars().all()
    
    jobs_created = 0
    sources_processed = 0
    
    for source in crawled_sources:
        if not source.category_id or not source.markdown_content:
            continue
            
        # Fetch the active prompts of the category
        prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)
        
        for prompt in prompts:
            await job_queue.enqueue(
                job_type=JobType.EXTRACT,
                source_id=str(source.id),
                prompt_id=prompt.id,
                priority=JobPriority.EXTRACT_INDEPENDENT
            )
            jobs_created += 1
        
        # Move the status to 'extracting'
        source.status = 'extracting'
        sources_processed += 1
    
    await session.commit()
    
    logger.info(
        "requeue_crawled_sources",
        sources_found=len(crawled_sources),
        sources_processed=sources_processed,
        jobs_created=jobs_created
    )
    
    return {
        "message": f"Requeued {sources_processed} crawled sources with {jobs_created} extract jobs",
        "sources_processed": sources_processed,
        "jobs_created": jobs_created
    }


@router.post("/recovery/requeue-extracting-sources")
async def requeue_extracting_sources(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Requeue all sources stuck in 'extracting' status.
    Checks which extractions are missing and creates jobs for them.
    """
    from sqlalchemy import select
    
    source_repo = SourceRepository(Source, session)
    prompt_repo = PromptRepository(Prompt, session)
    extraction_repo = ExtractionRepository(Extraction, session)
    job_queue = await get_job_queue()
    
    # Find every source with status 'extracting'
    result = await session.execute(
        select(Source).where(Source.status == 'extracting')
    )
    extracting_sources = result.scalars().all()
    
    jobs_created = 0
    sources_completed = 0
    
    for source in extracting_sources:
        if not source.category_id or not source.markdown_content:
            continue
        
        # Fetch all active prompts of the category
        prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)
        prompt_ids = {p.id for p in prompts}
        
        # Fetch the extractions that already exist
        extractions = await extraction_repo.get_by_source(source.id)
        extracted_prompt_ids = {e.prompt_id for e in extractions}
        
        # Finde fehlende Prompts
        missing_prompt_ids = prompt_ids - extracted_prompt_ids
        
        if not missing_prompt_ids:
            # Every extraction is present, so mark the source as completed
            source.status = 'completed'
            sources_completed += 1
        else:
            # Create jobs for the prompts that are still missing
            for prompt_id in missing_prompt_ids:
                await job_queue.enqueue(
                    job_type=JobType.EXTRACT,
                    source_id=str(source.id),
                    prompt_id=prompt_id,
                    priority=JobPriority.EXTRACT_INDEPENDENT
                )
                jobs_created += 1
    
    await session.commit()
    
    logger.info(
        "requeue_extracting_sources",
        sources_found=len(extracting_sources),
        sources_completed=sources_completed,
        jobs_created=jobs_created
    )
    
    return {
        "message": f"Processed {len(extracting_sources)} extracting sources",
        "sources_completed": sources_completed,
        "jobs_created": jobs_created
    }


@router.post("/recovery/requeue-all-stuck")
async def requeue_all_stuck_sources(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Master recovery endpoint - requeues ALL stuck sources in one call.
    Handles: pending, crawled, extracting
    """
    results = {
        "pending": None,
        "crawled": None,
        "extracting": None
    }
    
    # Reuse the individual functions
    try:
        # Note: In real implementation, call the logic directly to avoid HTTP overhead
        # This is a simplified version
        
        from sqlalchemy import select
        job_queue = await get_job_queue()
        prompt_repo = PromptRepository(Prompt, session)
        extraction_repo = ExtractionRepository(Extraction, session)
        
        total_jobs = 0
        
        # 1. Pending sources -> CRAWL jobs
        pending_result = await session.execute(
            select(Source).where(Source.status == 'pending')
        )
        pending_sources = pending_result.scalars().all()
        
        for source in pending_sources:
            await job_queue.enqueue(
                job_type=JobType.CRAWL,
                source_id=str(source.id),
                priority=JobPriority.CRAWL,
                payload={"url": source.url}
            )
            total_jobs += 1
        
        results["pending"] = {"count": len(pending_sources), "jobs": len(pending_sources)}
        
        # 2. Crawled sources -> EXTRACT jobs
        crawled_result = await session.execute(
            select(Source).where(Source.status == 'crawled')
        )
        crawled_sources = crawled_result.scalars().all()
        crawled_jobs = 0
        
        for source in crawled_sources:
            if not source.category_id or not source.markdown_content:
                continue
            prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)
            for prompt in prompts:
                await job_queue.enqueue(
                    job_type=JobType.EXTRACT,
                    source_id=str(source.id),
                    prompt_id=prompt.id,
                    priority=JobPriority.EXTRACT_INDEPENDENT
                )
                crawled_jobs += 1
                total_jobs += 1
            source.status = 'extracting'
        
        results["crawled"] = {"count": len(crawled_sources), "jobs": crawled_jobs}
        
        # 3. Extracting sources -> Missing EXTRACT jobs
        extracting_result = await session.execute(
            select(Source).where(Source.status == 'extracting')
        )
        extracting_sources = extracting_result.scalars().all()
        extracting_jobs = 0
        completed = 0
        
        for source in extracting_sources:
            if not source.category_id or not source.markdown_content:
                continue
            
            prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)
            prompt_ids = {p.id for p in prompts}
            
            extractions = await extraction_repo.get_by_source(source.id)
            extracted_prompt_ids = {e.prompt_id for e in extractions}
            
            missing = prompt_ids - extracted_prompt_ids
            
            if not missing:
                source.status = 'completed'
                completed += 1
            else:
                for prompt_id in missing:
                    await job_queue.enqueue(
                        job_type=JobType.EXTRACT,
                        source_id=str(source.id),
                        prompt_id=prompt_id,
                        priority=JobPriority.EXTRACT_INDEPENDENT
                    )
                    extracting_jobs += 1
                    total_jobs += 1
        
        results["extracting"] = {
            "count": len(extracting_sources),
            "jobs": extracting_jobs,
            "auto_completed": completed
        }
        
        await session.commit()
        
        # Get queue size
        queue_size = await job_queue.get_queue_size()
        
        logger.info(
            "requeue_all_stuck_complete",
            total_jobs_created=total_jobs,
            queue_size=queue_size,
            results=results
        )
        
        return {
            "message": "Recovery complete",
            "total_jobs_created": total_jobs,
            "queue_size": queue_size,
            "details": results
        }
        
    except Exception as e:
        logger.error("requeue_all_stuck_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recovery/queue-status")
async def get_queue_status(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Get detailed queue and source status for debugging.
    """
    from sqlalchemy import select, func
    
    job_queue = await get_job_queue()
    
    # Queue size
    queue_size = await job_queue.get_queue_size()
    
    # Source counts by status
    status_counts = {}
    for status in ['pending', 'crawled', 'extracting', 'completed', 'failed']:
        result = await session.execute(
            select(func.count()).select_from(Source).where(Source.status == status)
        )
        status_counts[status] = result.scalar()
    
    # Pending jobs in queue
    pending_jobs = await job_queue.get_pending_jobs(limit=10)
    pending_jobs_info = [
        {
            "id": j.id,
            "type": j.job_type,
            "source_id": j.source_id,
            "status": j.status
        }
        for j in pending_jobs
    ]
    
    return {
        "queue_size": queue_size,
        "source_counts": status_counts,
        "sample_pending_jobs": pending_jobs_info
    }


@router.delete("/recovery/clear-stuck-jobs")
async def clear_stuck_jobs(
    session: AsyncSession = Depends(get_async_session)
):
    """
    Clear all job data from Redis (use with caution!).
    This removes all job:* keys and the job_queue.
    """
    job_queue = await get_job_queue()
    
    # Get all job keys
    job_keys = await job_queue.redis.keys("job:*")
    
    deleted_count = 0
    if job_keys:
        deleted_count = await job_queue.redis.delete(*job_keys)
    
    # Clear the queue
    await job_queue.redis.delete("job_queue")
    
    # Reset job ID counter
    await job_queue.redis.set("job_id_counter", 0)
    
    logger.warning(
        "cleared_stuck_jobs",
        deleted_job_keys=deleted_count
    )
    
    return {
        "message": "Cleared all job data from Redis",
        "deleted_job_keys": deleted_count,
        "queue_cleared": True,
        "job_counter_reset": True
    }

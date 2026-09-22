# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Worker pool. Takes jobs from the queue and runs them.

Prompts are loaded through get_with_dependencies(): a plain query would leave
the dependency relationship unloaded, and resolving it later happens outside
the session.
"""
import asyncio
import signal
from typing import Optional

import structlog

from app.config import get_settings
from app.database import get_db_session, wait_for_db
from app.repositories import (
    CategoryRepository, ExtractionRepository, PromptRepository,
    SourceRepository, SteckbriefRepository
)
from app.services.circuit_breaker import get_circuit_breaker
from app.services.crawler_service import CrawlerService
from app.services.entity_normalizer import EntityNormalizerService
from app.services.job_queue import Job, JobQueue, JobType, get_job_queue
from app.services.llm_client import LLMClient, get_llm_client
from app.services.prompt_engine import PromptEngineService
from app.services.retry_manager import RetryManager, get_retry_manager
from app.services.steckbrief_generator import SteckbriefGenerator
from app.models import Extraction, Source, Category, Prompt, JobPriority, Steckbrief, SteckbriefTranslation

logger = structlog.get_logger()
settings = get_settings()


class WorkerPool:
    """Runs several workers in parallel and hands them jobs"""

    def __init__(
        self,
        num_workers: Optional[int] = None,
        max_concurrent_llm: Optional[int] = None
    ):
        self.num_workers = num_workers or settings.num_workers
        self.max_concurrent_llm = max_concurrent_llm or settings.max_concurrent_llm
        self.llm_semaphore = asyncio.Semaphore(self.max_concurrent_llm)
        self.workers = []
        self.running = False
        
        # Rate-Limiting
        self.llm_request_delay = settings.llm_request_delay
        self.requests_per_minute = settings.llm_requests_per_minute
        self._last_llm_request_time = 0.0
        self._request_lock = asyncio.Lock()
        
        # Token bucket for the pool-wide rate limit
        self._token_bucket = float(self.requests_per_minute) if self.requests_per_minute > 0 else float('inf')
        self._last_token_refill = 0.0  # Set on the first request

        # Services
        self.queue: Optional[JobQueue] = None
        self.llm_client: Optional[LLMClient] = None
        self.crawler: Optional[CrawlerService] = None
        self.retry_manager: Optional[RetryManager] = None

        logger.info(
            "worker_pool_initialized",
            num_workers=self.num_workers,
            max_concurrent_llm=self.max_concurrent_llm,
            llm_request_delay=self.llm_request_delay,
            requests_per_minute=self.requests_per_minute
        )

    async def start(self):
        """Start all workers"""
        self.running = True

        # Wait for database
        logger.info("Waiting for database...")
        if not await wait_for_db():
            logger.error("Database not available, cannot start workers")
            return

        # Initialize services
        try:
            self.queue = await get_job_queue()
            self.llm_client = get_llm_client()
            self.crawler = CrawlerService()
            self.retry_manager = get_retry_manager()

            logger.info("Services initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize services", error=str(e), exc_info=True)
            raise

        # Start workers
        self.workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self.num_workers)
        ]

        logger.info("worker_pool_started", num_workers=self.num_workers)

    async def stop(self):
        """Stop all workers"""
        self.running = False

        # Cancel all workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)

        # Close services
        if self.queue:
            await self.queue.close()
        if self.llm_client:
            await self.llm_client.close()

        logger.info("worker_pool_stopped")

    async def _apply_rate_limit(self):
        """
        Apply the rate limit for LLM requests.

        Two mechanisms combine:
        1. A minimum delay between requests (llm_request_delay)
        2. A token bucket for the requests_per_minute limit
        """
        import time
        
        async with self._request_lock:
            current_time = time.time()
            
            # Initialise the token bucket on the first request
            if self._last_token_refill == 0.0:
                self._last_token_refill = current_time
            
            # 1. Minimum delay between requests
            if self.llm_request_delay > 0 and self._last_llm_request_time > 0:
                time_since_last = current_time - self._last_llm_request_time
                if time_since_last < self.llm_request_delay:
                    wait_time = self.llm_request_delay - time_since_last
                    logger.debug(
                        "rate_limit_delay",
                        wait_seconds=round(wait_time, 2)
                    )
                    await asyncio.sleep(wait_time)
                    current_time = time.time()
            
            # 2. Token bucket for requests_per_minute
            if self.requests_per_minute > 0:
                # Refill tokens according to the time that has passed
                time_since_refill = current_time - self._last_token_refill
                tokens_to_add = (time_since_refill / 60.0) * self.requests_per_minute
                self._token_bucket = min(
                    float(self.requests_per_minute),
                    self._token_bucket + tokens_to_add
                )
                self._last_token_refill = current_time
                
                # Wait while no token is available
                if self._token_bucket < 1:
                    wait_time = (1 - self._token_bucket) * (60.0 / self.requests_per_minute)
                    logger.info(
                        "rate_limit_bucket_wait",
                        wait_seconds=round(wait_time, 2),
                        tokens_available=round(self._token_bucket, 2)
                    )
                    await asyncio.sleep(wait_time)
                    self._token_bucket = 1.0
                
                # Token verbrauchen
                self._token_bucket -= 1
            
            self._last_llm_request_time = time.time()

    async def _worker(self, worker_id: int):
        """Worker loop: take a job from the queue and process it"""
        logger.info("worker_started", worker_id=worker_id)

        while self.running:
            try:
                # Take a job from the queue (blocking, with timeout)
                job = await self.queue.get_next_job(timeout=5)

                if not job:
                    # No job available, keep waiting
                    continue

                logger.info(
                    "worker_processing_job",
                    worker_id=worker_id,
                    job_id=job.id,
                    job_type=job.job_type,
                    source_id=job.source_id
                )

                # Job-Status: running
                await self.queue.mark_running(job.id)

                # Semaphore limiting concurrent LLM calls
                if job.job_type in ['extract', 'validate', 'normalize', 'translate']:
                    async with self.llm_semaphore:
                        # Rate limit: wait between LLM requests
                        await self._apply_rate_limit()
                        success, error = await self._process_job(job)
                else:
                    success, error = await self._process_job(job)

                # Job outcome: completed or failed
                if success:
                    await self.queue.mark_completed(job.id)
                    logger.info(
                        "worker_job_completed",
                        worker_id=worker_id,
                        job_id=job.id
                    )
                else:
                    await self.queue.mark_failed(job.id, error or "Unknown error")
                    logger.error(
                        "worker_job_failed",
                        worker_id=worker_id,
                        job_id=job.id,
                        error=error
                    )

            except asyncio.CancelledError:
                logger.info("worker_cancelled", worker_id=worker_id)
                break
            except Exception as e:
                logger.error(
                    "worker_exception",
                    worker_id=worker_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                await asyncio.sleep(5)  # Back off after a failure

        logger.info("worker_stopped", worker_id=worker_id)

    async def _process_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """
        Process one job.

        Returns:
            (success, error_message)
        """
        try:
            if job.job_type == JobType.CRAWL.value:
                return await self._process_crawl_job(job)

            elif job.job_type == JobType.EXTRACT.value:
                return await self._process_extract_job(job)

            elif job.job_type == JobType.VALIDATE.value:
                return await self._process_validate_job(job)

            elif job.job_type == JobType.NORMALIZE.value:
                return await self._process_normalize_job(job)

            elif job.job_type == JobType.GENERATE.value:
                return await self._process_generate_job(job)

            elif job.job_type == JobType.TRANSLATE.value:
                return await self._process_translate_job(job)

            else:
                return False, f"Unknown job type: {job.job_type}"

        except Exception as e:
            logger.error(
                "job_processing_exception",
                job_id=job.id,
                job_type=job.job_type,
                error=str(e),
                exc_info=True
            )
            return False, str(e)

    async def _process_crawl_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process a CRAWL job and queue the extraction that follows it"""
        from uuid import UUID

        source_id = UUID(job.source_id)

        async with get_db_session() as session:
            source_repo = SourceRepository(Source, session)
            prompt_repo = PromptRepository(Prompt, session)

            # Get source
            source = await source_repo.get(source_id)
            if not source:
                return False, f"Source {source_id} not found"

            # Log and validate the URL taken from the database
            url_from_db = source.url
            logger.info(
                "crawl_job_starting",
                source_id=str(source_id),
                url=url_from_db[:200] if url_from_db else "None",
                url_repr=repr(url_from_db)[:250] if url_from_db else "None"
            )
            
            if not url_from_db or not url_from_db.strip():
                error_msg = f"Source {source_id} has empty URL"
                await source_repo.update_status(source_id, 'failed', error_msg)
                return False, error_msg

            # Crawl URL
            additional_urls = job.payload.get('additional_urls', [])
            result = await self.crawler.crawl_url(
                url_from_db.strip(),  # Strip surrounding whitespace
                additional_urls=additional_urls
            )

            if not result.success:
                await source_repo.update_status(
                    source_id,
                    'failed',
                    result.error
                )
                return False, result.error

            # Update source
            source.markdown_content = result.markdown
            source.markdown_size = result.size
            source.pages_crawled = result.pages_crawled
            source.crawled_at = result.timestamp
            source.status = 'crawled'
            await source_repo.update_obj(source)

            await session.commit()

            logger.info(
                "crawl_completed",
                source_id=str(source_id),
                pages=result.pages_crawled,
                size=result.size
            )

            # Queue extraction automatically once the crawl succeeded
            if source.category_id:
                prompts = await prompt_repo.get_by_category(source.category_id, active_only=True)

                if prompts:
                    logger.info(
                        "triggering_auto_extraction",
                        source_id=str(source_id),
                        prompt_count=len(prompts)
                    )

                    # Create extract jobs for all prompts
                    jobs_created = 0
                    for prompt in prompts:
                        await self.queue.enqueue(
                            job_type=JobType.EXTRACT,
                            source_id=str(source_id),
                            prompt_id=prompt.id,
                            priority=JobPriority.EXTRACT_INDEPENDENT,
                            payload={}
                        )
                        jobs_created += 1

                    # Update source status
                    source.status = 'extracting'
                    await source_repo.update_obj(source)
                    await session.commit()

                    logger.info(
                        "auto_extraction_triggered",
                        source_id=str(source_id),
                        jobs_created=jobs_created
                    )
                else:
                    logger.warning(
                        "no_active_prompts_for_category",
                        source_id=str(source_id),
                        category_id=source.category_id
                    )
            else:
                logger.warning(
                    "source_has_no_category",
                    source_id=str(source_id)
                )

            return True, None

    async def _process_extract_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process an EXTRACT job"""
        from uuid import UUID

        source_id = UUID(job.source_id)
        prompt_id = job.prompt_id

        if not prompt_id:
            return False, "No prompt_id in extract job"

        async with get_db_session() as session:
            source_repo = SourceRepository(Source, session)
            prompt_repo = PromptRepository(Prompt, session)
            extraction_repo = ExtractionRepository(Extraction, session)

            # Get source and prompt
            source = await source_repo.get(source_id)
            if not source:
                return False, f"Source {source_id} not found"

            if not source.markdown_content:
                return False, f"Source {source_id} has no markdown content"

            # get_with_dependencies() eager-loads the dependency relationship
            prompt = await prompt_repo.get_with_dependencies(prompt_id)
            if not prompt:
                return False, f"Prompt {prompt_id} not found"

            logger.info(
                "starting_extraction",
                source_id=str(source_id),
                prompt_id=prompt_id,
                prompt_name=prompt.internal_name
            )

            # Initialize PromptEngine
            prompt_engine = PromptEngineService(session, self.llm_client)

            try:
                # Run extraction (extract + validate)
                extraction = await prompt_engine.process_prompt(
                    source_id=source_id,
                    prompt=prompt,
                    markdown_content=source.markdown_content
                )

                await session.commit()

                logger.info(
                    "extraction_completed",
                    source_id=str(source_id),
                    prompt_id=prompt_id,
                    extraction_id=extraction.id,
                    confidence=extraction.final_confidence
                )

                # Check if all extractions for this source are done
                await self._check_source_completion(source_id, session)

                return True, None

            except Exception as e:
                logger.error(
                    "extraction_failed",
                    source_id=str(source_id),
                    prompt_id=prompt_id,
                    error=str(e),
                    exc_info=True
                )
                return False, str(e)

    async def _check_source_completion(self, source_id, session):
        """Check if all extractions for source are complete and update status"""
        from uuid import UUID

        source_repo = SourceRepository(Source, session)
        prompt_repo = PromptRepository(Prompt, session)
        extraction_repo = ExtractionRepository(Extraction, session)

        source = await source_repo.get(source_id)
        if not source or not source.category_id:
            return

        # Get expected prompts for category
        expected_prompts = await prompt_repo.get_by_category(
            source.category_id,
            active_only=True
        )
        expected_count = len(expected_prompts)

        # Get actual extractions
        extractions = await extraction_repo.get_by_source(source_id)
        actual_count = len(extractions)

        logger.info(
            "checking_source_completion",
            source_id=str(source_id),
            expected=expected_count,
            actual=actual_count
        )

        # If all extractions are done, mark source as completed
        if actual_count >= expected_count and expected_count > 0:
            source.status = 'completed'
            await source_repo.update_obj(source)
            await session.commit()

            logger.info(
                "source_extraction_completed",
                source_id=str(source_id),
                extractions=actual_count
            )

    async def _process_validate_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process VALIDATE job"""
        # Validation is now part of extract job
        return True, None

    async def _process_normalize_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process NORMALIZE job"""
        from uuid import UUID

        source_id = UUID(job.source_id)

        async with get_db_session() as session:
            extraction_repo = ExtractionRepository(Extraction, session)

            # Get extractions that need normalization
            extractions = await extraction_repo.get_for_entity_normalization(
                job.payload.get('entity_type', 'university')
            )

            # Process each extraction
            # (Simplified - in full implementation would process specific extraction)

            await session.commit()

            return True, None

    async def _process_generate_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process a GENERATE job, producing the profile"""
        from uuid import UUID

        source_id = UUID(job.source_id)

        async with get_db_session() as session:
            generator = SteckbriefGenerator(session)

            # Generate the profile
            steckbrief = await generator.generate(source_id)

            await session.commit()

            logger.info(
                "steckbrief_generated",
                source_id=str(source_id),
                steckbrief_id=steckbrief.id
            )

            return True, None

    async def _process_translate_job(self, job: Job) -> tuple[bool, Optional[str]]:
        """Process TRANSLATE job - NEW: Extraction-level translation per Source"""
        from uuid import UUID
        from app.services.extraction_translation import ExtractionTranslationService
        from app.services.steckbrief_generator import SteckbriefGenerator

        source_id = UUID(job.source_id)
        target_language = job.payload.get('target_language', 'en')

        async with get_db_session() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            # Get source with category
            result = await session.execute(
                select(Source)
                .options(selectinload(Source.category))
                .where(Source.id == source_id)
            )
            source = result.scalar_one_or_none()

            if not source:
                return False, f"Source {source_id} not found"

            category_name = source.category.display_name if source.category else "AI initiative"

            logger.info(
                "starting_extraction_translation",
                source_id=str(source_id),
                target_language=target_language,
                category=category_name
            )

            # The German profile has to exist first: the English one is built from it
            generator = SteckbriefGenerator(session)
            
            # Check whether the German profile exists
            de_steckbrief = await generator.steckbrief_repo.get_by_source(source_id)
            if not de_steckbrief:
                logger.info(
                    "generating_de_steckbrief_first",
                    source_id=str(source_id)
                )
                try:
                    de_steckbrief = await generator.generate(source_id, language='de')
                    await session.commit()
                    logger.info(
                        "de_steckbrief_generated",
                        source_id=str(source_id),
                        steckbrief_id=de_steckbrief.id
                    )
                except Exception as de_error:
                    logger.error(
                        "de_steckbrief_generation_failed",
                        source_id=str(source_id),
                        error=str(de_error)
                    )
                    return False, f"Cannot generate DE Steckbrief: {str(de_error)}"

            # Initialize ExtractionTranslationService
            translation_service = ExtractionTranslationService(self.llm_client, session)

            try:
                # Translate all extractions for this source
                stats = await translation_service.translate_source_extractions(
                    source_id=str(source_id),
                    force=job.payload.get('force', False)
                )

                await session.commit()

                logger.info(
                    "extraction_translation_completed",
                    source_id=str(source_id),
                    translated=stats.get('translated', 0),
                    skipped=stats.get('skipped', 0),
                    failed=stats.get('failed', 0)
                )

                # Generate EN steckbrief if requested
                # Generate even when translated=0, as long as translations already exist
                if job.payload.get('generate_steckbrief', True):
                    # Are there any translated extractions at all?
                    from app.models import Extraction, Prompt
                    trans_check = await session.execute(
                        select(Extraction)
                        .join(Prompt)
                        .where(
                            Extraction.source_id == source_id,
                            Extraction.validated_result_en.isnot(None),
                            Extraction.validated_result_en != '',
                            Prompt.translatable == True
                        )
                        .limit(1)
                    )
                    has_translations = trans_check.scalar_one_or_none() is not None
                    
                    if has_translations:
                        try:
                            logger.info(
                                "generating_steckbrief",
                                source_id=str(source_id),
                                language='en'
                            )
                            en_steckbrief = await generator.generate(source_id, language='en')
                            await session.commit()
                            logger.info(
                                "en_steckbrief_generated",
                                source_id=str(source_id),
                                steckbrief_id=en_steckbrief.id if en_steckbrief else None
                            )
                        except Exception as gen_error:
                            logger.warning(
                                "en_steckbrief_generation_failed",
                                source_id=str(source_id),
                                error=str(gen_error)
                            )
                    else:
                        logger.info(
                            "skipping_en_steckbrief_no_translations",
                            source_id=str(source_id)
                        )

                return True, None

            except Exception as e:
                logger.error(
                    "extraction_translation_failed",
                    source_id=str(source_id),
                    error=str(e),
                    exc_info=True
                )
                return False, str(e)


async def run_worker_pool():
    """Main entry point for worker process"""
    # Setup structured logging
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    )

    logger.info("starting_worker_pool")

    pool = WorkerPool()

    # Graceful shutdown handler
    shutdown_event = asyncio.Event()

    def signal_handler(signum, frame):
        logger.info("shutdown_signal_received", signal=signum)
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await pool.start()

        # Keep running until shutdown signal
        await shutdown_event.wait()

    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    except Exception as e:
        logger.error("worker_pool_error", error=str(e), exc_info=True)
    finally:
        await pool.stop()


if __name__ == "__main__":
    asyncio.run(run_worker_pool())
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Redis-backed job queue with priorities.

A job carries its own status history (started, completed, failed, last error)
so that a stuck job can be diagnosed from the queue alone, without joining
against the database.
"""
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


# JobType and JobPriority are defined once, in app.models, next to the
# database CheckConstraint that has to list the same values. They used to be
# duplicated here and had already drifted apart: this copy knew TRANSLATE and
# the other did not.
from app.models import JobPriority, JobType  # noqa: E402  (kept next to its users)


@dataclass
class Job:
    """A queued job, carrying its own status history"""
    id: int
    job_type: str
    source_id: Optional[str] = None
    prompt_id: Optional[int] = None
    priority: int = 100
    payload: dict = None
    status: str = 'pending'
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = None

    # Status fields, so that a job carries its own history
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    last_error: Optional[str] = None
    
    def __post_init__(self):
        if self.payload is None:
            self.payload = {}
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc).isoformat()
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Job':
        """Create Job from dict"""
        # Handle bytes from Redis
        cleaned = {}
        for k, v in data.items():
            key = k.decode('utf-8') if isinstance(k, bytes) else k
            if isinstance(v, bytes):
                try:
                    value = v.decode('utf-8')
                    # Try to parse JSON payload
                    if key == 'payload':
                        value = json.loads(value)
                    # Convert numeric strings
                    elif key in ['id', 'prompt_id', 'priority', 'attempts', 'max_attempts']:
                        value = int(value) if value else None
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    value = str(v)
            else:
                value = v
            cleaned[key] = value
        
        return cls(**cleaned)
    
    def to_dict(self) -> dict:
        """Convert to dict for Redis storage - filters out None values"""
        data = asdict(self)

        # JSON encode payload
        if isinstance(data['payload'], dict):
            data['payload'] = json.dumps(data['payload'])

        # Remove None values - Redis can't serialize None
        filtered_data = {k: v for k, v in data.items() if v is not None}

        return filtered_data


class JobQueue:
    """Redis-backed job queue with priorities"""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self.redis = redis_client
        self._job_id_counter = 0
        logger.info("job_queue_initialized")

    async def connect(self):
        """Connect to Redis"""
        if self.redis is None:
            self.redis = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=False  # We handle decoding ourselves
            )
            logger.info("redis_connected", url=settings.redis_url)

    async def close(self):
        """Close Redis connection"""
        if self.redis:
            await self.redis.close()
            logger.info("redis_closed")

    async def _next_id(self) -> int:
        """Generate next job ID"""
        return await self.redis.incr("job_id_counter")

    async def enqueue(
        self,
        job_type: JobType,
        source_id: Optional[str] = None,  # Changed to str - already converted in admin.py
        prompt_id: Optional[int] = None,
        priority: Optional[int] = None,
        payload: Optional[dict] = None,
        max_attempts: int = 3
    ) -> int:
        """
        Add a job to the queue.

        Args:
            job_type: JobType enum
            source_id: optional source UUID as a string
            prompt_id: optional prompt id
            priority: priority (higher runs first), defaults per job_type
            payload: optional additional data
            max_attempts: maximum retry attempts

        Returns:
            Job id
        """
        # Default priority based on job type
        if priority is None:
            priority_map = {
                JobType.CRAWL: JobPriority.CRAWL,
                JobType.EXTRACT: JobPriority.EXTRACT_INDEPENDENT,
                JobType.VALIDATE: JobPriority.VALIDATE,
                JobType.NORMALIZE: JobPriority.NORMALIZE,
                JobType.TRANSLATE: JobPriority.TRANSLATE,
                JobType.GENERATE: JobPriority.GENERATE,
            }
            # A job type missing from the map would silently fall back to the
            # crawl priority, which is the highest one. Fail loudly instead.
            if job_type not in priority_map:
                raise ValueError(f"No default priority defined for job type {job_type!r}")
            priority = priority_map[job_type]

        job = Job(
            id=await self._next_id(),
            job_type=job_type.value,
            source_id=source_id,  # Already a string or None
            prompt_id=prompt_id,
            priority=priority,
            payload=payload or {},
            status='pending',
            attempts=0,
            max_attempts=max_attempts
        )

        # Store the job. to_dict() filters out None values, which Redis cannot hold.
        job_dict = job.to_dict()

        await self.redis.hset(
            f"job:{job.id}",
            mapping=job_dict
        )

        # Put into the priority queue. Scores are negated so that a higher priority sorts first.
        await self.redis.zadd(
            "job_queue",
            {str(job.id): -priority}
        )

        logger.info(
            "job_enqueued",
            job_id=job.id,
            job_type=job.job_type,
            source_id=job.source_id,
            priority=priority
        )

        return job.id

    async def get_next_job(self, timeout: int = 5) -> Optional[Job]:
        """
        Take the next job, highest priority first.

        Args:
            timeout: timeout in seconds for the blocking pop

        Returns:
            Job, or None
        """
        # Atomic pop from the sorted set (BZPOPMIN)
        result = await self.redis.bzpopmin("job_queue", timeout=timeout)

        if not result:
            return None

        _, job_id_bytes, _ = result
        job_id = int(job_id_bytes)

        # Load the job details
        job_data = await self.redis.hgetall(f"job:{job_id}")

        if not job_data:
            logger.error("job_data_missing", job_id=job_id)
            return None

        job = Job.from_dict(job_data)

        logger.debug("job_dequeued", job_id=job.id, job_type=job.job_type)

        return job

    async def mark_running(self, job_id: int) -> None:
        """Mark a job as running"""
        await self.redis.hset(
            f"job:{job_id}",
            mapping={
                'status': 'running',
                'started_at': datetime.now(timezone.utc).isoformat()
            }
        )

        logger.debug("job_marked_running", job_id=job_id)

    async def mark_completed(self, job_id: int) -> None:
        """Mark a job as completed"""
        await self.redis.hset(
            f"job:{job_id}",
            mapping={
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }
        )

        logger.info("job_completed", job_id=job_id)

    async def mark_failed(self, job_id: int, error: str) -> None:
        """Mark a job as failed"""
        job_data = await self.redis.hgetall(f"job:{job_id}")
        job = Job.from_dict(job_data)

        attempts = job.attempts + 1
        max_attempts = job.max_attempts

        if attempts < max_attempts:
            # Retry: back into the queue
            await self.redis.hset(
                f"job:{job_id}",
                mapping={
                    'attempts': attempts,
                    'last_error': error,
                    'status': 'pending'
                }
            )

            # Back into the queue at a lower priority
            await self.redis.zadd(
                "job_queue",
                {str(job_id): -(job.priority - 10)}  # Leicht niedrigere Priority
            )

            logger.warning(
                "job_retry",
                job_id=job_id,
                attempt=attempts,
                max_attempts=max_attempts,
                error=error
            )
        else:
            # Final failure
            await self.redis.hset(
                f"job:{job_id}",
                mapping={
                    'status': 'failed',
                    'last_error': error,
                    'failed_at': datetime.now(timezone.utc).isoformat(),
                    'attempts': attempts
                }
            )

            logger.error(
                "job_failed_permanently",
                job_id=job_id,
                attempts=attempts,
                error=error
            )

    async def get_job(self, job_id: int) -> Optional[Job]:
        """Get job by ID"""
        job_data = await self.redis.hgetall(f"job:{job_id}")
        if not job_data:
            return None
        return Job.from_dict(job_data)

    async def get_queue_size(self) -> int:
        """Get number of pending jobs"""
        return await self.redis.zcard("job_queue")

    async def get_running_jobs(self) -> list[Job]:
        """Get list of currently running jobs"""
        # Scan all job:* keys and filter by status=running
        running_jobs = []
        cursor = 0
        
        while True:
            cursor, keys = await self.redis.scan(cursor, match="job:*", count=100)
            
            for key in keys:
                try:
                    job_data = await self.redis.hgetall(key)
                    if job_data and job_data.get('status') == 'running':
                        job = Job.from_dict(job_data)
                        running_jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse job", key=key, error=str(e))
            
            if cursor == 0:
                break
        
        return running_jobs

    async def get_all_active_jobs(self) -> dict:
        """Get all pending and running jobs with counts"""
        pending = await self.get_pending_jobs(limit=50)
        running = await self.get_running_jobs()
        
        return {
            'pending': pending,
            'running': running,
            'pending_count': await self.get_queue_size(),
            'running_count': len(running)
        }

    async def get_pending_jobs(self, limit: int = 100) -> list[Job]:
        """Get list of pending jobs"""
        # Get job IDs from sorted set
        job_ids = await self.redis.zrange("job_queue", 0, limit - 1)

        jobs = []
        for job_id_bytes in job_ids:
            job_id = int(job_id_bytes)
            job = await self.get_job(job_id)
            if job:
                jobs.append(job)

        return jobs


# Singleton instance
_job_queue: Optional[JobQueue] = None


async def get_job_queue() -> JobQueue:
    """Get or create singleton JobQueue"""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
        await _job_queue.connect()
    return _job_queue
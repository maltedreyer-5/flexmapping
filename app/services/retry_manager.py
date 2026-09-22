# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Retry manager with exponential backoff.

Backoff is capped and jittered: without a cap a long retry chain blocks a
worker for minutes, and without jitter all workers retry in lockstep and hit
the recovering backend at the same moment.
"""
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Set, Tuple, Type

import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@dataclass
class RetryResult:
    """Outcome of a retry sequence"""
    success: bool
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    total_duration_ms: int = 0


class RetryManagerError(Exception):
    """Raised for invalid retry manager input"""
    pass


class RetryManager:
    """
    Runs a callable with exponential backoff and jitter.

    Features:
    - Exponential backoff
    - Jitter (randomised delays)
    - Maximum backoff, so a retry chain cannot block a worker indefinitely
    - Selective exception handling

    Example:
        retry_manager = RetryManager()
        result = await retry_manager.execute(
            func=my_async_function,
            args=(arg1, arg2),
            max_attempts=3
        )
    """

    # Exceptions that must NOT be retried
    NON_RETRYABLE_EXCEPTIONS: Set[Type[Exception]] = {
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    }

    def __init__(
        self,
        default_max_attempts: Optional[int] = None,
        backoff_base: Optional[float] = None,
        max_backoff: float = 60.0,  # Wait at most 60 seconds, so a retry chain cannot block a worker
        jitter: bool = True  # Jitter is on by default
    ):
        """
        Args:
            default_max_attempts: default number of attempts
            backoff_base: base of the exponential backoff (2.0 = 2s, 4s, 8s...)
            max_backoff: longest wait in seconds
            jitter: whether to randomise the delays
        """
        self.default_max_attempts = default_max_attempts or settings.retry_max_attempts
        self.backoff_base = backoff_base or settings.retry_backoff_base
        self.max_backoff = max_backoff
        self.jitter = jitter

        # Validation
        if self.default_max_attempts < 1:
            raise RetryManagerError("default_max_attempts must be >= 1")

        if self.backoff_base < 1.0:
            raise RetryManagerError("backoff_base must be >= 1.0")

        if self.max_backoff < 1.0:
            raise RetryManagerError("max_backoff must be >= 1.0")

        logger.info(
            "retry_manager_initialized",
            default_max_attempts=self.default_max_attempts,
            backoff_base=self.backoff_base,
            max_backoff=self.max_backoff,
            jitter=self.jitter
        )

    async def execute(
        self,
        func: Callable[..., Awaitable[Any]],  # Type hint kept explicit for the optional argument
        args: Tuple = (),
        kwargs: Optional[dict] = None,
        max_attempts: Optional[int] = None,
        job_id: Optional[str] = None,
        retry_on_exceptions: Optional[Set[Type[Exception]]] = None
    ) -> RetryResult:
        """
        Run a function, retrying on failure.

        Args:
            func: async function to execute
            args: positional arguments
            kwargs: keyword arguments
            max_attempts: maximum attempts (default: from configuration)
            job_id: optional job id, for logging
            retry_on_exceptions: exceptions to retry (default: all but NON_RETRYABLE)

        Returns:
            RetryResult carrying success or failure information

        Raises:
            RetryManagerError: on invalid input
        """
        # Input-Validierung
        if not callable(func):
            raise RetryManagerError("func must be callable")

        kwargs = kwargs or {}
        max_attempts = max_attempts or self.default_max_attempts

        if max_attempts < 1:
            raise RetryManagerError("max_attempts must be >= 1")

        start_time = time.time()
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(
                    "retry_attempt",
                    job_id=job_id,
                    attempt=attempt,
                    max_attempts=max_attempts
                )

                # Run the function
                result = await func(*args, **kwargs)

                # Does the result carry a success attribute?
                if hasattr(result, 'success'):
                    if result.success:
                        # Erfolg!
                        duration_ms = int((time.time() - start_time) * 1000)

                        logger.info(
                            "retry_success",
                            job_id=job_id,
                            attempt=attempt,
                            max_attempts=max_attempts,
                            duration_ms=duration_ms
                        )

                        return RetryResult(
                            success=True,
                            result=result,
                            attempts=attempt,
                            total_duration_ms=duration_ms
                        )
                    else:
                        # Result reports success=False
                        last_error = getattr(result, 'error', 'Unknown error')

                        if attempt < max_attempts:
                            backoff = self.calculate_backoff(attempt)
                            logger.warning(
                                "retry_result_failed",
                                job_id=job_id,
                                attempt=attempt,
                                max_attempts=max_attempts,
                                error=last_error,
                                backoff_seconds=backoff
                            )
                            await asyncio.sleep(backoff)
                        continue

                # No success attribute to inspect, so treat it as a success
                duration_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    "retry_success_no_check",
                    job_id=job_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    duration_ms=duration_ms
                )

                return RetryResult(
                    success=True,
                    result=result,
                    attempts=attempt,
                    total_duration_ms=duration_ms
                )

            except Exception as e:
                # Is this exception worth retrying?
                if not self._should_retry_exception(e, retry_on_exceptions):
                    logger.error(
                        "non_retryable_exception",
                        job_id=job_id,
                        attempt=attempt,
                        error=str(e),
                        error_type=type(e).__name__
                    )
                    # Sofort abbrechen ohne weitere Versuche
                    duration_ms = int((time.time() - start_time) * 1000)
                    return RetryResult(
                        success=False,
                        error=f"Non-retryable error: {str(e)}",
                        attempts=attempt,
                        total_duration_ms=duration_ms
                    )

                last_error = str(e)

                if attempt < max_attempts:
                    backoff = self.calculate_backoff(attempt)
                    logger.warning(
                        "retry_exception",
                        job_id=job_id,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        error=str(e),
                        error_type=type(e).__name__,
                        backoff_seconds=backoff
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "retry_exhausted",
                        job_id=job_id,
                        attempts=attempt,
                        max_attempts=max_attempts,
                        error=str(e),
                        error_type=type(e).__name__
                    )

        # Every attempt failed
        duration_ms = int((time.time() - start_time) * 1000)

        return RetryResult(
            success=False,
            error=last_error,
            attempts=max_attempts,
            total_duration_ms=duration_ms
        )

    def _should_retry_exception(
        self,
        exception: Exception,
        retry_on_exceptions: Optional[Set[Type[Exception]]] = None
    ) -> bool:
        """
        Decide whether an exception is worth retrying.

        Args:
            exception: the exception that occurred
            retry_on_exceptions: optional whitelist of retryable exceptions

        Returns:
            True to retry, False to give up immediately
        """
        exc_type = type(exception)

        # A whitelist was given, so retry only those
        if retry_on_exceptions is not None:
            return exc_type in retry_on_exceptions

        # Default: everything except NON_RETRYABLE_EXCEPTIONS
        return exc_type not in self.NON_RETRYABLE_EXCEPTIONS

    def calculate_backoff(self, attempt: int) -> float:
        """
        Compute the backoff delay, capped and jittered.

        Args:
            attempt: attempt number, counting from 1

        Returns:
            Seconds to wait
        """
        if attempt < 1:
            return 0.0

        # Exponentieller Backoff
        base_backoff = self.backoff_base ** (attempt - 1)

        # Cap at max_backoff
        base_backoff = min(base_backoff, self.max_backoff)

        # Add jitter (plus or minus 25 percent)
        if self.jitter:
            jitter_factor = random.uniform(0.75, 1.25)
            backoff = base_backoff * jitter_factor
        else:
            backoff = base_backoff

        return round(backoff, 2)


# Singleton instance
_retry_manager: Optional[RetryManager] = None


def get_retry_manager() -> RetryManager:
    """
    Get or create singleton RetryManager

    Returns:
        RetryManager instance
    """
    global _retry_manager
    if _retry_manager is None:
        _retry_manager = RetryManager()
        logger.debug("singleton_retry_manager_created")
    return _retry_manager
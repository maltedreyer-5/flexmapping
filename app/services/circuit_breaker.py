# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Circuit breaker for the LLM backend and other external services.

Locking is explicit throughout: several workers share one breaker instance,
and an unsynchronised failure count lets the breaker stay closed while the
backend is already down.
"""
import threading
import time
from enum import Enum
from typing import Optional

import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


class CircuitState(Enum):
    """Circuit Breaker States"""
    CLOSED = "CLOSED"        # Normal operation, all requests allowed
    OPEN = "OPEN"            # Paused, no requests pass
    HALF_OPEN = "HALF_OPEN"  # Probing, a single request is let through


class CircuitBreakerOpenError(Exception):
    """Raised while the circuit is open"""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation, safe to share between parallel workers.

    Protects the system from repeated failures by pausing requests to a
    service that is already failing, instead of queueing more work behind it.
    """

    def __init__(
        self,
        service_name: str,
        failure_threshold: Optional[int] = None,
        timeout_seconds: Optional[int] = None
    ):
        """
        Args:
            service_name: name of the service (for example "llm", "crawler")
            failure_threshold: number of failures before the circuit opens
            timeout_seconds: how long to stay open before probing again
        """
        self.service_name = service_name
        self.failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self.timeout = timeout_seconds or settings.circuit_breaker_timeout

        # Lock: workers share one breaker instance
        self._lock = threading.RLock()

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.opened_time: Optional[float] = None

        # Whether a probe request is currently in flight
        self._test_request_in_flight = False

        logger.info(
            "circuit_breaker_initialized",
            service=service_name,
            failure_threshold=self.failure_threshold,
            timeout=self.timeout
        )

    def can_execute(self) -> bool:
        """
        Check whether a request may proceed.

        Returns:
            True if the request may be executed

        Raises:
            CircuitBreakerOpenError if the circuit is open
        """
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            elif self.state == CircuitState.OPEN:
                # opened_time may be None if the breaker never opened
                if self.opened_time is None:
                    logger.error(
                        "circuit_breaker_invalid_state",
                        service=self.service_name,
                        state="OPEN",
                        opened_time=None
                    )
                    # Recover: Reset to CLOSED
                    self.state = CircuitState.CLOSED
                    return True

                # Has the timeout elapsed?
                elapsed = time.time() - self.opened_time
                if elapsed > self.timeout:
                    logger.info(
                        "circuit_breaker_half_open",
                        service=self.service_name,
                        timeout_seconds=self.timeout
                    )
                    self.state = CircuitState.HALF_OPEN
                    self._test_request_in_flight = False
                    return True

                # Timeout has not elapsed yet
                time_remaining = self.timeout - elapsed
                logger.warning(
                    "circuit_breaker_request_blocked",
                    service=self.service_name,
                    state="OPEN",
                    time_remaining=int(time_remaining)
                )
                raise CircuitBreakerOpenError(
                    f"Circuit breaker for {self.service_name} is OPEN. "
                    f"Try again in {int(time_remaining)} seconds."
                )

            elif self.state == CircuitState.HALF_OPEN:
                # Exactly one probe request at a time. Letting several through
                # would hammer a backend that has only just come back.
                if self._test_request_in_flight:
                    logger.warning(
                        "circuit_breaker_test_in_progress",
                        service=self.service_name
                    )
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker for {self.service_name} is testing. "
                        f"Test request already in flight."
                    )

                # Allow this request as test
                self._test_request_in_flight = True
                logger.info(
                    "circuit_breaker_test_request_allowed",
                    service=self.service_name
                )
                return True

    def record_success(self):
        """Record a successful call and advance the state accordingly"""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info(
                    "circuit_breaker_test_success",
                    service=self.service_name,
                    previous_failures=self.failure_count
                )
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.last_failure_time = None
                self.opened_time = None
                self._test_request_in_flight = False

            elif self.state == CircuitState.CLOSED:
                # Reset the failure count on success
                if self.failure_count > 0:
                    logger.debug(
                        "circuit_breaker_success_after_failures",
                        service=self.service_name,
                        previous_failures=self.failure_count
                    )
                self.failure_count = 0
                self.last_failure_time = None

    def record_failure(self):
        """Record a failed call and advance the state accordingly"""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                logger.warning(
                    "circuit_breaker_test_failed",
                    service=self.service_name,
                    failure_count=self.failure_count
                )
                self.state = CircuitState.OPEN
                self.opened_time = time.time()
                self._test_request_in_flight = False

            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    logger.error(
                        "circuit_breaker_threshold_reached",
                        service=self.service_name,
                        failure_count=self.failure_count,
                        threshold=self.failure_threshold
                    )
                    self.state = CircuitState.OPEN
                    self.opened_time = time.time()
                else:
                    logger.warning(
                        "circuit_breaker_failure_recorded",
                        service=self.service_name,
                        failure_count=self.failure_count,
                        threshold=self.failure_threshold
                    )

    def get_state(self) -> dict:
        """
        Read the current state, for monitoring.

        Returns:
            Dict with state information
        """
        with self._lock:
            return {
                "service": self.service_name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "last_failure_time": self.last_failure_time,
                "opened_time": self.opened_time,
                "timeout": self.timeout,
                "test_in_flight": self._test_request_in_flight
            }

    def reset(self):
        """Reset the breaker by hand, from the admin interface"""
        with self._lock:
            logger.info(
                "circuit_breaker_manual_reset",
                service=self.service_name,
                previous_state=self.state.value,
                failure_count=self.failure_count
            )
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_failure_time = None
            self.opened_time = None
            self._test_request_in_flight = False


# One singleton instance per service
# Lock, so that two workers cannot create two breakers for one service
_circuit_breakers: dict[str, CircuitBreaker] = {}
_creation_lock = threading.Lock()


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    """
    Get or create the circuit breaker for a service.

    Args:
        service_name: name of the service (for example "llm", "crawler")

    Returns:
        CircuitBreaker instance
    """
    # Fast path: Check without lock
    if service_name in _circuit_breakers:
        return _circuit_breakers[service_name]

    # Slow path: Create with lock
    with _creation_lock:
        # Double-check after acquiring lock
        if service_name not in _circuit_breakers:
            _circuit_breakers[service_name] = CircuitBreaker(service_name)
        return _circuit_breakers[service_name]
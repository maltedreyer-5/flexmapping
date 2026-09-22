# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Services Package

All business logic services of FlexMapping.

Note: Imports are commented out to avoid loading all services at once.
Import directly where needed for better performance and explicit dependencies.

Example:
    from app.services.crawler_service import CrawlerService
    from app.services.llm_client import get_llm_client
"""

# Optional: Export singleton getters for convenient access
# These are lightweight and commonly used across the application
#
# from .llm_client import get_llm_client
# from .circuit_breaker import get_circuit_breaker
# from .retry_manager import get_retry_manager
# from .job_queue import get_job_queue

# Service Classes - Import directly to avoid loading all services
# from .crawler_service import CrawlerService
# from .llm_client import LLMClient
# from .prompt_engine import PromptEngineService
# from .entity_normalizer import EntityNormalizerService
# from .steckbrief_generator import SteckbriefGenerator
# from .static_site_generator import StaticSiteGenerator
# from .job_queue import JobQueue, JobType, JobPriority
# from .circuit_breaker import CircuitBreaker, CircuitState
# from .retry_manager import RetryManager

# Leave empty to avoid:
# 1. Circular import issues
# 2. Loading unnecessary services at startup
# 3. Hidden dependencies between modules
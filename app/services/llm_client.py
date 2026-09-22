# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Client for the LLM backend, speaking the OpenAI-compatible chat completions
API.

Responses are parsed defensively: a self-hosted backend may return a truncated
choice, an empty message or a payload without logprobs, and each of those has
to produce a clear error rather than an attribute lookup on None.
"""
import time
from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@dataclass
class LLMResponse:
    """Response vom LLM"""
    text: str
    confidence: Optional[float] = None
    model: str = ""
    usage: dict = None
    duration_ms: int = 0


class LLMClientError(Exception):
    """Raised for LLM client errors"""
    pass


class LLMClient:
    """OpenAI-compatible client for the LLM backend"""

    # Validierungsgrenzen
    MAX_CONTEXT_LENGTH = 200000  # ~50k tokens
    MAX_PROMPT_LENGTH = 10000
    MIN_TEMPERATURE = 0.0
    MAX_TEMPERATURE = 2.0

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None
    ):
        self.base_url = base_url or settings.llm_base_url
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout = timeout or settings.llm_timeout

        # Validate base_url
        if not self.base_url or not self.base_url.startswith('http'):
            raise LLMClientError(f"Invalid base_url: {self.base_url}")

        # Remove trailing slashes
        self.base_url = self.base_url.rstrip('/')

        # Create async HTTP client with proper timeouts
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(
                timeout=self.timeout,
                connect=10.0,  # Connection timeout
                read=self.timeout,  # Read timeout
                write=10.0,  # Write timeout
                pool=5.0  # Pool timeout
            )
        )

        logger.info(
            "llm_client_initialized",
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout
        )

    async def complete(
        self,
        prompt: str,
        context: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: str = "Du bist ein präziser Informations-Extraktor."
    ) -> LLMResponse:
        """
        Send a completion request to the LLM.

        Args:
            prompt: the task or instruction
            context: the text to work on (for example crawled Markdown)
            temperature: sampling temperature (default: 0.1)
            max_tokens: maximum response tokens (default: 500)
            system_prompt: system instruction

        Returns:
            LLMResponse with text and metadata

        Raises:
            LLMClientError: on validation or API errors
        """
        # Input-Validierung
        if not prompt or not prompt.strip():
            raise LLMClientError("Prompt cannot be empty")

        if len(prompt) > self.MAX_PROMPT_LENGTH:
            logger.warning(
                "prompt_too_long",
                length=len(prompt),
                max_length=self.MAX_PROMPT_LENGTH
            )
            prompt = prompt[:self.MAX_PROMPT_LENGTH]

        if context and len(context) > self.MAX_CONTEXT_LENGTH:
            logger.warning(
                "context_too_long",
                length=len(context),
                max_length=self.MAX_CONTEXT_LENGTH
            )
            context = context[:self.MAX_CONTEXT_LENGTH]

        # Defaults
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

        # Validate temperature
        if not (self.MIN_TEMPERATURE <= temperature <= self.MAX_TEMPERATURE):
            logger.warning(
                "invalid_temperature",
                temperature=temperature,
                clamping_to_range=f"{self.MIN_TEMPERATURE}-{self.MAX_TEMPERATURE}"
            )
            temperature = max(self.MIN_TEMPERATURE, min(self.MAX_TEMPERATURE, temperature))

        # Konstruiere Messages
        messages = [
            {"role": "system", "content": system_prompt}
        ]

        if context and context.strip():
            messages.append({
                "role": "user",
                "content": f"Kontext:\n{context}\n\nAufgabe:\n{prompt}"
            })
        else:
            messages.append({
                "role": "user",
                "content": prompt
            })

        start_time = time.time()

        try:
            response = await self.client.post(
                "/chat/completions",  # Base URL already has /v1
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )

            duration_ms = int((time.time() - start_time) * 1000)

            response.raise_for_status()
            data = response.json()

            # Parse the response defensively; a self-hosted backend may omit fields
            result = self._parse_response(data, duration_ms)

            logger.info(
                "llm_request_success",
                duration_ms=duration_ms,
                model=result.model,
                usage=result.usage,
                prompt_length=len(prompt),
                context_length=len(context),
                confidence=result.confidence
            )

            return result

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)

            # Try to parse error message
            error_detail = "Unknown error"
            try:
                error_data = e.response.json()
                error_detail = error_data.get('error', {}).get('message', str(e))
            except:
                error_detail = str(e)

            logger.error(
                "llm_request_http_error",
                status_code=e.response.status_code,
                error=error_detail,
                duration_ms=duration_ms
            )
            raise LLMClientError(
                f"LLM API returned {e.response.status_code}: {error_detail}"
            )

        except httpx.TimeoutException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "llm_request_timeout",
                error=str(e),
                duration_ms=duration_ms,
                timeout=self.timeout
            )
            raise LLMClientError(f"LLM request timed out after {self.timeout}s")

        except httpx.RequestError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "llm_request_error",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )
            raise LLMClientError(f"LLM request failed: {e}")

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "llm_request_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
                exc_info=True
            )
            raise LLMClientError(f"Unexpected LLM error: {e}")

    def _parse_response(self, data: dict, duration_ms: int) -> LLMResponse:
        """
        Parse an LLM API response.

        Args:
            data: response JSON
            duration_ms: request duration

        Returns:
            LLMResponse

        Raises:
            LLMClientError: on an invalid response format
        """
        try:
            # Validate structure
            if 'choices' not in data:
                raise LLMClientError("Response missing 'choices' field")

            choices = data['choices']
            if not choices or len(choices) == 0:
                raise LLMClientError("Response has empty 'choices' list")

            first_choice = choices[0]

            if 'message' not in first_choice:
                raise LLMClientError("Choice missing 'message' field")

            message = first_choice['message']

            if 'content' not in message:
                raise LLMClientError("Message missing 'content' field")

            content = message['content']

            if content is None:
                logger.warning("llm_returned_null_content")
                content = ""

            text = content.strip() if isinstance(content, str) else str(content)

            # Derive the confidence from logprobs, or from finish_reason
            confidence = self._calculate_confidence(first_choice, data)

            return LLMResponse(
                text=text,
                confidence=confidence,
                model=data.get('model', self.model),
                usage=data.get('usage', {}),
                duration_ms=duration_ms
            )

        except LLMClientError:
            raise
        except Exception as e:
            logger.error(
                "response_parsing_error",
                error=str(e),
                response_preview=str(data)[:200],
                exc_info=True
            )
            raise LLMClientError(f"Failed to parse LLM response: {e}")

    def _calculate_confidence(self, choice: dict, full_response: dict) -> float:
        """
        Derive a confidence score from the LLM response.

        Several signals are combined, because a self-hosted backend may supply
        none of them:
        - finish_reason (stop is good, length means the answer was cut off)
        - logprobs, where the backend returns them
        - otherwise a heuristic based on the response length

        Args:
            choice: first choice from the response
            full_response: the complete response dict

        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = 0.7  # Default medium confidence

        # 1. Check finish_reason
        finish_reason = choice.get('finish_reason', 'stop')

        if finish_reason == 'stop':
            # Normal completion
            confidence = 0.8
        elif finish_reason == 'length':
            # Response cut off by max_tokens
            confidence = 0.6
            logger.debug("response_cut_off_by_length")
        elif finish_reason == 'content_filter':
            # Content filtered
            confidence = 0.3
            logger.warning("response_filtered")
        else:
            # Unknown finish reason
            confidence = 0.5
            logger.debug("unknown_finish_reason", reason=finish_reason)

        # 2. Check logprobs if available (better confidence estimation)
        if 'logprobs' in choice and choice['logprobs']:
            try:
                logprobs = choice['logprobs']
                # Average log probability
                if 'token_logprobs' in logprobs and logprobs['token_logprobs']:
                    avg_logprob = sum(logprobs['token_logprobs']) / len(logprobs['token_logprobs'])
                    # Convert log prob to confidence (rough approximation)
                    # logprob range typically -10 to 0
                    confidence = max(0.5, min(1.0, (avg_logprob + 10) / 10))
                    logger.debug("confidence_from_logprobs", confidence=confidence)
            except Exception as e:
                logger.debug("failed_to_parse_logprobs", error=str(e))

        # 3. Heuristic: Very short responses might be uncertain
        content = choice.get('message', {}).get('content', '')
        if content and len(content.strip()) < 5:
            confidence = min(confidence, 0.5)
            logger.debug("very_short_response", length=len(content))

        return round(confidence, 2)

    async def close(self):
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()
            logger.debug("llm_client_closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Singleton instance with proper async initialization
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """
    Get or create singleton LLM client

    Note: This creates the client synchronously.
    For async initialization, use get_llm_client_async()

    Returns:
        LLMClient instance
    """
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
        logger.debug("singleton_llm_client_created")
    return _llm_client


async def get_llm_client_async() -> LLMClient:
    """
    Async version of get_llm_client (for future use)

    Currently identical to sync version, but allows for
    async initialization if needed.

    Returns:
        LLMClient instance
    """
    return get_llm_client()


async def close_llm_client():
    """Close singleton LLM client (cleanup)"""
    global _llm_client
    if _llm_client is not None:
        await _llm_client.close()
        _llm_client = None
        logger.info("singleton_llm_client_closed")
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Prompt engine: runs the two-phase extraction and resolves prompt dependencies.

Prompts are executed in waves rather than one by one. A prompt that depends on
another needs that value as context, so the engine groups prompts by
dependency level and runs each level in parallel.
"""
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Prompt, PromptDependency, Extraction
from app.services.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from app.services.llm_client import LLMClient, LLMResponse
from app.services.retry_manager import RetryManager, get_retry_manager

logger = structlog.get_logger()


@dataclass
class ExtractResult:
    """Result of the extract phase"""
    success: bool
    raw_result: Optional[str] = None
    raw_confidence: Optional[float] = None
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class ValidateResult:
    """Result of the validate phase"""
    success: bool
    result: Optional[str] = None
    quality: Optional[str] = None
    validation_score: Optional[float] = None
    notes: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class ExtractionResult:
    """Final extraction result"""
    raw_result: Optional[str]
    raw_confidence: Optional[float]
    validated_result: Optional[str]
    validation_quality: Optional[str]
    validation_score: Optional[float]
    validation_notes: Optional[str]
    final_confidence: float
    extract_duration_ms: int = 0
    validate_duration_ms: int = 0
    error: Optional[str] = None


class DependencyResolver:
    """Resolves dependencies between prompts"""

    def resolve_order(self, prompts: List[Prompt]) -> List[List[Prompt]]:
        """
        Sort prompts into execution waves according to their dependencies.

        Returns: a list of lists, each inner list being one wave
        """
        # Build the dependency graph
        graph = {p.id: p for p in prompts}
        dependencies = {p.id: self._get_dependencies(p) for p in prompts}

        # Compute the execution waves
        waves = []
        remaining = set(graph.keys())

        while remaining:
            # Find prompts whose dependencies are all satisfied
            wave = []
            for prompt_id in remaining:
                deps = dependencies[prompt_id]
                if not deps or all(d not in remaining for d in deps):
                    wave.append(graph[prompt_id])

            if not wave:
                # Cyclic dependency
                logger.error(
                    "cyclic_dependency_detected",
                    remaining_prompts=[graph[pid].internal_name for pid in remaining]
                )
                # Fallback: put everything that is left into one wave
                wave = [graph[pid] for pid in remaining]

            waves.append(wave)
            remaining -= {p.id for p in wave}

        logger.info(
            "dependency_resolution_complete",
            num_waves=len(waves),
            wave_sizes=[len(w) for w in waves]
        )

        return waves

    def _get_dependencies(self, prompt: Prompt) -> Set[int]:
        """Extrahiere Dependency-IDs"""
        return {dep.depends_on_prompt_id for dep in prompt.dependencies}


class PromptEngineService:
    """Orchestrates the two-phase extraction, honouring dependencies"""

    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMClient
    ):
        """
        Args:
            session: AsyncSession for database access
            llm_client: LLM client
        """
        self.session = session
        self.llm = llm_client
        self.retry_manager = get_retry_manager()
        self.circuit_breaker = get_circuit_breaker("llm")
        self.dependency_resolver = DependencyResolver()

    async def process_prompt(
        self,
        source_id: UUID,
        prompt: Prompt,
        markdown_content: str
    ) -> Extraction:
        """
        Process a single prompt for one source and store the result.

        Args:
            source_id: source UUID
            prompt: the prompt object
            markdown_content: the crawled Markdown of the source

        Returns:
            The Extraction object, already persisted
        """
        logger.info(
            "processing_prompt",
            source_id=str(source_id),
            prompt_id=prompt.id,
            prompt_name=prompt.internal_name
        )

        # Load the dependency context, if there is one
        context = await self._load_dependencies_context(source_id, prompt)

        # Run extract, then validate
        result = await self.extract_and_validate(
            markdown=markdown_content,
            prompt=prompt,
            source_id=source_id,
            context=context
        )

        # Erstelle Extraction-Objekt
        extraction = Extraction(
            source_id=source_id,
            prompt_id=prompt.id,
            raw_result=result.raw_result,
            raw_confidence=result.raw_confidence,
            extract_duration_ms=result.extract_duration_ms,
            validated_result=result.validated_result,
            validation_quality=result.validation_quality,
            validation_score=result.validation_score,
            validation_notes=result.validation_notes,
            validate_duration_ms=result.validate_duration_ms,
            final_confidence=result.final_confidence
        )

        # Store in the database
        self.session.add(extraction)
        await self.session.flush()
        await self.session.refresh(extraction)

        logger.info(
            "extraction_created",
            source_id=str(source_id),
            prompt_id=prompt.id,
            extraction_id=extraction.id,
            final_confidence=extraction.final_confidence
        )

        return extraction

    async def _load_dependencies_context(
        self,
        source_id: UUID,
        prompt: Prompt
    ) -> Dict[str, str]:
        """
        Load the dependency context for a single prompt.

        Args:
            source_id: source UUID
            prompt: prompt carrying dependencies

        Returns:
            Dict of context values taken from extractions that already exist
        """
        from sqlalchemy import select

        context = {}

        if not prompt.dependencies:
            return context

        # Load every extraction that already exists for this source
        result = await self.session.execute(
            select(Extraction)
            .where(Extraction.source_id == source_id)
        )
        existing_extractions = result.scalars().all()

        # Build a map: prompt_id -> validated_result
        extraction_map = {
            ext.prompt_id: ext.validated_result
            for ext in existing_extractions
            if ext.validated_result
        }

        # Collect the values the dependencies ask for
        for dep in prompt.dependencies:
            dep_value = extraction_map.get(dep.depends_on_prompt_id)

            if dep_value:
                context[dep.context_key] = dep_value
                logger.debug(
                    "dependency_loaded",
                    prompt=prompt.internal_name,
                    dependency=dep.context_key,
                    value_preview=dep_value[:50] if len(dep_value) > 50 else dep_value
                )
            elif dep.is_required:
                logger.warning(
                    "required_dependency_missing",
                    prompt=prompt.internal_name,
                    dependency_prompt_id=dep.depends_on_prompt_id,
                    dependency_key=dep.context_key
                )

        return context

    async def process_source(
        self,
        source_id: UUID,
        markdown: str,
        prompts: List[Prompt]
    ) -> Dict[str, ExtractionResult]:
        """
        Process every prompt of one source, resolving dependencies.

        Args:
            source_id: source UUID
            markdown: the crawled Markdown of the source
            prompts: list of prompts

        Returns:
            Dict: {prompt_internal_name: ExtractionResult}
        """
        logger.info(
            "processing_source_start",
            source_id=str(source_id),
            num_prompts=len(prompts)
        )

        # Order the prompts by their dependencies
        sorted_prompts = self.dependency_resolver.resolve_order(prompts)

        # Collect extractions, to serve as dependency context
        extractions: Dict[str, str] = {}
        results: Dict[str, ExtractionResult] = {}

        # Process the prompts in waves, one dependency level at a time
        for wave_num, wave in enumerate(sorted_prompts, 1):
            logger.info(
                "processing_wave",
                wave_num=wave_num,
                num_prompts=len(wave),
                prompt_names=[p.internal_name for p in wave]
            )

            # Every prompt in this wave runs in parallel
            import asyncio
            tasks = []
            for prompt in wave:
                # Load the context coming from the dependencies
                context = self._build_context(prompt, extractions)

                task = self.extract_and_validate(
                    markdown, prompt, source_id, context
                )
                tasks.append((prompt, task))

            # Run one wave in parallel
            wave_results = await asyncio.gather(
                *[task for _, task in tasks],
                return_exceptions=True
            )

            # Keep the results, they feed the next wave
            for (prompt, _), result in zip(tasks, wave_results):
                if isinstance(result, Exception):
                    logger.error(
                        "prompt_execution_exception",
                        prompt=prompt.internal_name,
                        error=str(result)
                    )
                    results[prompt.internal_name] = ExtractionResult(
                        raw_result=None,
                        raw_confidence=None,
                        validated_result=None,
                        validation_quality=None,
                        validation_score=None,
                        validation_notes=None,
                        final_confidence=0.0,
                        error=str(result)
                    )
                else:
                    results[prompt.internal_name] = result
                    # Store validated_result so that dependent prompts can read it
                    if result.validated_result:
                        extractions[prompt.internal_name] = result.validated_result

        logger.info(
            "processing_source_complete",
            source_id=str(source_id),
            num_results=len(results),
            successful=[k for k, v in results.items() if v.validated_result]
        )

        return results

    def _build_context(
        self,
        prompt: Prompt,
        extractions: Dict[str, str]
    ) -> Dict[str, str]:
        """
        Build the context dict from the prompt dependencies.

        Args:
            prompt: prompt carrying dependencies
            extractions: values extracted so far

        Returns:
            Dict of context values
        """
        context = {}

        for dep in prompt.dependencies:
            # Read the value produced by the prompt this one depends on
            dep_value = extractions.get(dep.context_key)

            if dep_value:
                context[dep.context_key] = dep_value
            elif dep.is_required:
                # Required Dependency fehlt
                logger.warning(
                    "required_dependency_missing",
                    prompt=prompt.internal_name,
                    dependency=dep.context_key
                )

        if context:
            logger.debug(
                "context_built",
                prompt=prompt.internal_name,
                context_keys=list(context.keys())
            )

        return context

    async def extract_and_validate(
        self,
        markdown: str,
        prompt: Prompt,
        source_id: UUID,
        context: Optional[Dict[str, str]] = None
    ) -> ExtractionResult:
        """
        Two-phase extraction, with optional context.

        Args:
            markdown: source Markdown
            prompt: the prompt object
            source_id: source UUID, for logging
            context: optional dependency context

        Returns:
            ExtractionResult
        """
        context = context or {}

        # Phase 1: extract, with context
        extract_prompt_text = self._inject_context(
            prompt.extract_prompt,
            context
        )

        extract_result = await self.retry_manager.execute(
            func=self._extract_phase,
            args=(markdown, extract_prompt_text),
            max_attempts=prompt.max_retries,
            job_id=f"extract_{source_id}_{prompt.id}"
        )

        if not extract_result.success or not extract_result.result:
            return ExtractionResult(
                raw_result=None,
                raw_confidence=None,
                validated_result=None,
                validation_quality="INSUFFICIENT",
                validation_score=0.0,
                validation_notes=extract_result.error,
                final_confidence=0.0,
                extract_duration_ms=extract_result.total_duration_ms,
                error=extract_result.error
            )

        extract_data: ExtractResult = extract_result.result

        # Give up if the raw result came back empty
        if not extract_data.raw_result:
            return ExtractionResult(
                raw_result=None,
                raw_confidence=extract_data.raw_confidence,
                validated_result=None,
                validation_quality="INSUFFICIENT",
                validation_score=0.0,
                validation_notes="Extract phase returned empty result",
                final_confidence=0.0,
                extract_duration_ms=extract_data.duration_ms,
                error="Empty extraction result"
            )

        # Phase 2: validate, with context
        try:
            validate_prompt_text = self._inject_context(
                prompt.validate_prompt.format(
                    raw_result=extract_data.raw_result
                ),
                context
            )
        except (KeyError, ValueError) as e:
            logger.error(
                "validate_prompt_format_error",
                error=str(e),
                prompt_id=prompt.id
            )
            return ExtractionResult(
                raw_result=extract_data.raw_result,
                raw_confidence=extract_data.raw_confidence,
                validated_result=None,
                validation_quality="INSUFFICIENT",
                validation_score=0.0,
                validation_notes=f"Prompt format error: {str(e)}",
                final_confidence=0.0,
                extract_duration_ms=extract_data.duration_ms,
                error=str(e)
            )

        validate_result = await self.retry_manager.execute(
            func=self._validate_phase,
            args=(extract_data.raw_result, markdown, validate_prompt_text),
            max_attempts=prompt.max_retries,
            job_id=f"validate_{source_id}_{prompt.id}"
        )

        if not validate_result.success or not validate_result.result:
            return ExtractionResult(
                raw_result=extract_data.raw_result,
                raw_confidence=extract_data.raw_confidence,
                validated_result=None,
                validation_quality="INSUFFICIENT",
                validation_score=0.0,
                validation_notes=validate_result.error,
                final_confidence=0.0,
                extract_duration_ms=extract_data.duration_ms,
                validate_duration_ms=validate_result.total_duration_ms,
                error=validate_result.error
            )

        validate_data: ValidateResult = validate_result.result

        # Final Confidence
        final_confidence = min(
            extract_data.raw_confidence or 0.0,
            validate_data.validation_score or 0.0
        )

        return ExtractionResult(
            raw_result=extract_data.raw_result,
            raw_confidence=extract_data.raw_confidence,
            validated_result=validate_data.result,
            validation_quality=validate_data.quality,
            validation_score=validate_data.validation_score,
            validation_notes=validate_data.notes,
            final_confidence=final_confidence,
            extract_duration_ms=extract_data.duration_ms,
            validate_duration_ms=validate_data.duration_ms
        )

    def _inject_context(self, prompt_text: str, context: Dict[str, str]) -> str:
        """
        Substitute placeholders in the prompt with context values.

        Args:
            prompt_text: prompt text with placeholders such as {institution}
            context: dict of context values

        Returns:
            The prompt text with placeholders filled in
        """
        result = prompt_text
        for key, value in context.items():
            placeholder = f"{{{key}}}"
            result = result.replace(placeholder, value)
        return result

    async def _extract_phase(
        self,
        markdown: str,
        prompt: str
    ) -> ExtractResult:
        """Phase 1: Extraktion"""

        # Circuit Breaker Check
        try:
            self.circuit_breaker.can_execute()
        except CircuitBreakerOpenError as e:
            return ExtractResult(
                success=False,
                error=str(e)
            )

        start = time.time()

        try:
            response: LLMResponse = await self.llm.complete(
                prompt=prompt,
                context=markdown,
                temperature=0.1,
                max_tokens=500
            )

            duration_ms = int((time.time() - start) * 1000)

            # Success
            self.circuit_breaker.record_success()

            return ExtractResult(
                success=True,
                raw_result=response.text,
                raw_confidence=response.confidence,
                duration_ms=duration_ms
            )

        except Exception as e:
            self.circuit_breaker.record_failure()
            duration_ms = int((time.time() - start) * 1000)

            logger.error(
                "extract_phase_error",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )

            return ExtractResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )

    async def _validate_phase(
        self,
        raw_result: str,
        markdown: str,
        prompt: str
    ) -> ValidateResult:
        """Phase 2: Validierung"""

        try:
            self.circuit_breaker.can_execute()
        except CircuitBreakerOpenError as e:
            return ValidateResult(
                success=False,
                error=str(e)
            )

        start = time.time()

        try:
            response: LLMResponse = await self.llm.complete(
                prompt=prompt,
                context=markdown,
                temperature=0.1,
                max_tokens=500
            )

            duration_ms = int((time.time() - start) * 1000)

            # Parse strukturierte Antwort
            parsed = self._parse_validation_response(response.text)

            self.circuit_breaker.record_success()

            return ValidateResult(
                success=True,
                result=parsed['result'],
                quality=parsed['quality'],
                validation_score=parsed['score'],
                notes=parsed['notes'],
                duration_ms=duration_ms
            )

        except Exception as e:
            self.circuit_breaker.record_failure()
            duration_ms = int((time.time() - start) * 1000)

            logger.error(
                "validate_phase_error",
                error=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms
            )

            return ValidateResult(
                success=False,
                error=str(e),
                duration_ms=duration_ms
            )

    def _parse_validation_response(self, response: str) -> dict:
        """
        Parse the structured validation response:
            QUALITY: HIGH
            SCORE: 0.92
            NOTES: -
            RESULT: Example value

        RESULT may also span several lines:
            RESULT:
            - Item 1
            - Item 2

        The multi-line form matters: list-valued fields are common, and
        reading only the first line silently truncates them to one item.
        """
        if not response:
            logger.warning("validation_response_empty")
            return {
                'quality': 'MEDIUM',
                'score': 0.5,
                'notes': 'Empty validation response',
                'result': ''
            }

        lines = response.strip().split('\n')
        parsed = {}
        result_lines = []
        in_result_section = False

        for line in lines:
            # Are we inside the RESULT section?
            stripped = line.strip()
            
            # A new key on this line?
            if ':' in line and not line.strip().startswith('-'):
                key_part = line.split(':', 1)[0].strip().lower()
                # Is it one of the keys we know?
                if key_part in ('quality', 'score', 'notes', 'result'):
                    if in_result_section and result_lines:
                        # Speichere gesammelte RESULT-Zeilen
                        parsed['result'] = '\n'.join(result_lines).strip()
                    
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = value.strip()
                    
                    if key == 'result':
                        in_result_section = True
                        result_lines = []
                        if value:  # Value sits on the same line as the key
                            result_lines.append(value)
                    else:
                        in_result_section = False
                        parsed[key] = value
                elif in_result_section:
                    # Line belongs to RESULT (for example "- Item: Description")
                    result_lines.append(stripped)
            elif in_result_section and stripped:
                # Continuation of RESULT, such as further list items
                result_lines.append(stripped)
        
        # Store the trailing RESULT lines
        if in_result_section and result_lines:
            parsed['result'] = '\n'.join(result_lines).strip()

        # Parse score with fallback
        score_str = parsed.get('score', '0.6')
        try:
            score = float(score_str)
            # Clamp into the range 0 to 1
            score = max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            logger.warning(
                "validation_score_parse_error",
                score_str=score_str
            )
            score = 0.5

        return {
            'quality': parsed.get('quality', 'MEDIUM').upper(),
            'score': score,
            'notes': parsed.get('notes', ''),
            'result': parsed.get('result', '')
        }
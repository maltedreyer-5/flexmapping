# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Entity normalization: maps extracted names onto canonical entities.

An exact match against canonical names and variants is tried first, because it
costs nothing; only the remainder goes to the LLM. Above the auto-link
threshold the link is created, in the middle band a review item is produced,
and below it the suggestion is discarded.
"""
from dataclasses import dataclass
from typing import List, Optional

import re
from difflib import SequenceMatcher

import structlog

from app.models import Entity
from app.services.llm_client import LLMClient

logger = structlog.get_logger()


@dataclass
class NormalizationResult:
    """Outcome of an entity normalization"""
    entity_id: Optional[int]
    canonical_name: Optional[str]
    confidence: float
    action: str  # 'auto_link', 'review_queue', 'ignore'
    needs_review: bool


class EntityNormalizerError(Exception):
    """Raised for entity normalization errors"""
    pass


class EntityNormalizerService:
    """LLM-basierte Entity-Normalisierung"""

    # Valide Entity-Typen
    VALID_ENTITY_TYPES = {'university', 'location'}

    # Confidence-Thresholds
    AUTO_LINK_THRESHOLD = 0.9
    REVIEW_THRESHOLD = 0.6

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        logger.info("entity_normalizer_initialized")

    async def normalize(
        self,
        text: str,
        entity_type: str,
        known_entities: List[Entity],
        context: Optional[str] = None
    ) -> NormalizationResult:
        """
        Normalize extracted text to a canonical entity.

        Args:
            text: the extracted text (for example "TU Berlin")
            entity_type: type ('university', 'location')
            known_entities: list of known entities
            context: optional context from the crawled Markdown

        Returns:
            NormalizationResult carrying a recommendation

        Raises:
            EntityNormalizerError: on invalid input
        """
        # Input-Validierung
        if not text or not text.strip():
            logger.warning("normalize_called_with_empty_text")
            raise EntityNormalizerError("Text cannot be empty")

        text = text.strip()

        if entity_type not in self.VALID_ENTITY_TYPES:
            logger.error(
                "invalid_entity_type",
                entity_type=entity_type,
                valid_types=list(self.VALID_ENTITY_TYPES)
            )
            raise EntityNormalizerError(
                f"Invalid entity_type: {entity_type}. "
                f"Must be one of: {self.VALID_ENTITY_TYPES}"
            )

        if not known_entities:
            logger.warning(
                "no_known_entities",
                text=text,
                entity_type=entity_type
            )
            # No known entities at all, so go straight to the review queue
            return NormalizationResult(
                entity_id=None,
                canonical_name=text,
                confidence=0.0,
                action='review_queue',
                needs_review=True
            )

        logger.info(
            "normalizing_entity",
            text=text,
            entity_type=entity_type,
            num_known=len(known_entities)
        )

        # Try exact matching first: it is cheaper than an LLM call
        exact_match = self._find_exact_match(text, known_entities)
        if exact_match:
            logger.info(
                "exact_match_found",
                text=text,
                canonical_name=exact_match.canonical_name,
                entity_id=exact_match.id
            )
            return NormalizationResult(
                entity_id=exact_match.id,
                canonical_name=exact_match.canonical_name,
                confidence=1.0,
                action='auto_link',
                needs_review=False
            )

        # LLM-basierte Normalisierung
        try:
            return await self._llm_normalize(
                text, entity_type, known_entities, context
            )
        except Exception as e:
            logger.error(
                "normalization_error",
                text=text,
                error=str(e),
                exc_info=True
            )
            # On failure, put the item into the review queue
            return NormalizationResult(
                entity_id=None,
                canonical_name=text,
                confidence=0.0,
                action='review_queue',
                needs_review=True
            )

    def _find_exact_match(
        self,
        text: str,
        known_entities: List[Entity]
    ) -> Optional[Entity]:
        """
        Look for an exact match, against canonical names and variants alike.

        Args:
            text: text to look up
            known_entities: list of known entities

        Returns:
            The entity on an exact match, otherwise None
        """
        text_lower = text.lower().strip()

        for entity in known_entities:
            # Check canonical name
            if entity.canonical_name and entity.canonical_name.lower().strip() == text_lower:
                return entity

            # Check the variants as well as the canonical name
            if entity.variants:
                for variant in entity.variants:
                    if variant.variant_name and variant.variant_name.lower().strip() == text_lower:
                        logger.debug(
                            "matched_via_variant",
                            text=text,
                            canonical_name=entity.canonical_name,
                            variant=variant.variant_name
                        )
                        return entity

        return None

    async def _llm_normalize(
        self,
        text: str,
        entity_type: str,
        known_entities: List[Entity],
        context: Optional[str]
    ) -> NormalizationResult:
        """
        LLM-based normalization, used when there is no exact match.

        Args:
            text: text to normalize
            entity_type: entity type
            known_entities: known entities
            context: optional context

        Returns:
            NormalizationResult
        """
        # LLM prompt carrying the known entities
        norm_prompt = self._build_normalization_prompt(
            text, entity_type, known_entities, context
        )

        # LLM fragen
        response = await self.llm.complete(
            prompt=norm_prompt,
            context="",
            temperature=0.1,
            max_tokens=200
        )

        # Parse Response
        parsed = self._parse_normalization_response(response.text)

        logger.info(
            "llm_normalization_complete",
            text=text,
            match_type=parsed['match_type'],
            canonical=parsed.get('canonical_name'),
            confidence=parsed['confidence']
        )

        # Look the entity up by canonical name or by any of its variants
        matched_entity = None
        if parsed['canonical_name']:
            matched_entity = self._find_entity_by_name(
                parsed['canonical_name'],
                known_entities
            )

        # Decide what to do, based on the confidence
        if parsed['match_type'] == 'MATCH' and parsed['confidence'] >= self.AUTO_LINK_THRESHOLD:
            # High confidence (≥0.9): Auto-Link
            return NormalizationResult(
                entity_id=matched_entity.id if matched_entity else None,
                canonical_name=parsed['canonical_name'],
                confidence=parsed['confidence'],
                action='auto_link',
                needs_review=False
            )

        elif (parsed['match_type'] == 'LIKELY' or
              (parsed['match_type'] == 'MATCH' and
               self.REVIEW_THRESHOLD <= parsed['confidence'] < self.AUTO_LINK_THRESHOLD)):
            # Medium confidence (0.6-0.89): Review-Queue
            return NormalizationResult(
                entity_id=matched_entity.id if matched_entity else None,
                canonical_name=parsed['canonical_name'],
                confidence=parsed['confidence'],
                action='review_queue',
                needs_review=True
            )

        else:
            # Low confidence (<0.6): Ignore
            return NormalizationResult(
                entity_id=None,
                canonical_name=None,
                confidence=parsed['confidence'],
                action='ignore',
                needs_review=False
            )

    def _find_entity_by_name(
        self,
        name: str,
        known_entities: List[Entity]
    ) -> Optional[Entity]:
        """
        Find an entity by name, matching canonical names and variants.

        Args:
            name: name to look up
            known_entities: list of known entities

        Returns:
            The entity, or None
        """
        if not name:
            return None

        name_lower = name.lower().strip()

        for entity in known_entities:
            # Check canonical name with None-check
            if entity.canonical_name and entity.canonical_name.lower().strip() == name_lower:
                return entity

            # Check variants with None-checks
            if entity.variants:
                for variant in entity.variants:
                    if variant.variant_name and variant.variant_name.lower().strip() == name_lower:
                        return entity

        return None

    # Number of entities offered to the model in one prompt. The limit exists
    # because the inventory can hold thousands of institutions and the prompt
    # has to stay within the context of a self-hosted model.
    MAX_PROMPT_CANDIDATES = 50

    @staticmethod
    def _similarity(text: str, entity: Entity) -> float:
        """
        Score how closely an entity matches the text, for candidate selection.

        The score is the best over the canonical name and every variant, so
        that an abbreviation in the text finds the entity that lists it. Three
        signals are combined, in descending order of weight: one name being
        contained in the other, shared words, and character-level similarity
        from difflib for spellings that differ slightly.

        This is a pre-filter, not the decision. The model still chooses from
        the candidates it is given.
        """
        needle = text.lower().strip()
        if not needle:
            return 0.0

        names = [entity.canonical_name or ""]
        names += [v.variant_name for v in (entity.variants or []) if v.variant_name]

        best = 0.0
        needle_words = set(re.findall(r"\w+", needle))
        for name in names:
            candidate = name.lower().strip()
            if not candidate:
                continue

            if needle == candidate:
                return 1.0

            score = 0.0
            if needle in candidate or candidate in needle:
                score = max(score, 0.8)

            candidate_words = set(re.findall(r"\w+", candidate))
            if needle_words and candidate_words:
                overlap = len(needle_words & candidate_words) / len(needle_words | candidate_words)
                score = max(score, 0.7 * overlap)

            score = max(score, 0.6 * SequenceMatcher(None, needle, candidate).ratio())
            best = max(best, score)

        return best

    def _select_candidates(self, text: str, known_entities: List[Entity]) -> List[Entity]:
        """
        Reduce the inventory to the candidates worth putting in the prompt.

        Without this the prompt received whatever the database returned first.
        With an inventory of a few dozen entities that was the whole inventory;
        with a few thousand it is an arbitrary slice that need not contain the
        right answer.
        """
        if len(known_entities) <= self.MAX_PROMPT_CANDIDATES:
            return known_entities

        scored = sorted(
            known_entities,
            key=lambda entity: self._similarity(text, entity),
            reverse=True,
        )
        return scored[: self.MAX_PROMPT_CANDIDATES]

    def _build_normalization_prompt(
        self,
        text: str,
        entity_type: str,
        known_entities: List[Entity],
        context: Optional[str] = None
    ) -> str:
        """
        Build the normalization prompt.

        Args:
            text: text to normalize
            entity_type: entity type
            known_entities: known entities; reduced to the closest matches
            context: optional context

        Returns:
            The prompt as a string
        """
        # Build the entity list, including every variant
        entity_lines = []
        for entity in self._select_candidates(text, known_entities):
            if not entity.canonical_name:
                continue

            line = f"- {entity.canonical_name}"

            # Add variants if available
            if entity.variants:
                variant_names = [
                    v.variant_name for v in entity.variants
                    if v.variant_name
                ]
                if variant_names:
                    line += f" (auch: {', '.join(variant_names[:3])})"  # Max 3 variants

            entity_lines.append(line)

        entity_list = "\n".join(entity_lines) if entity_lines else "Keine bekannten Entitäten"

        entity_type_display = {
            'university': 'Hochschule/Universität',
            'location': 'Ort'
        }.get(entity_type, entity_type)

        prompt = f"""Text erwähnt: "{text}"

Bekannte {entity_type_display}en:
{entity_list}

Ist der Text eine dieser Entitäten?

"""

        if context and context.strip():
            # Limit context length
            context_preview = context[:500] + "..." if len(context) > 500 else context
            prompt += f"\nKontext: {context_preview}\n"

        prompt += """
Antwortformat:
MATCH: [Offizieller Name] (Confidence: 0.9-1.0)
LIKELY: [Wahrscheinlicher Name] (Confidence: 0.6-0.89)
NO_MATCH (Confidence: 0.0-0.59)

Beispiel:
Text: "TU Berlin"
MATCH: Technische Universität Berlin (Confidence: 0.95)
"""

        return prompt

    def _parse_normalization_response(self, response: str) -> dict:
        """
        Parse the LLM response.

        Expects a line such as:
            "MATCH: Technische Universitaet Berlin (Confidence: 0.95)"

        Args:
            response: the LLM response

        Returns:
            Dict with match_type, canonical_name and confidence
        """
        if not response or not response.strip():
            logger.warning("empty_normalization_response")
            return {
                'match_type': 'NO_MATCH',
                'canonical_name': None,
                'confidence': 0.0
            }

        lines = response.strip().split('\n')
        first_line = lines[0].strip() if lines else ""

        if not first_line:
            logger.warning("empty_first_line_in_response")
            return {
                'match_type': 'NO_MATCH',
                'canonical_name': None,
                'confidence': 0.0
            }

        # Parse match type
        match_type = 'NO_MATCH'
        rest = first_line

        if first_line.upper().startswith('MATCH:'):
            match_type = 'MATCH'
            rest = first_line[6:].strip()  # Remove "MATCH:"
        elif first_line.upper().startswith('LIKELY:'):
            match_type = 'LIKELY'
            rest = first_line[7:].strip()  # Remove "LIKELY:"
        elif first_line.upper().startswith('NO_MATCH'):
            return {
                'match_type': 'NO_MATCH',
                'canonical_name': None,
                'confidence': 0.0
            }

        # Parse name and confidence
        name = None
        confidence = 0.5  # Default

        try:
            if '(Confidence:' in rest:
                # Split at last occurrence
                parts = rest.rsplit('(Confidence:', 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    conf_str = parts[1].replace(')', '').strip()
                    try:
                        confidence = float(conf_str)
                        # Clamp between 0 and 1
                        confidence = max(0.0, min(1.0, confidence))
                    except ValueError:
                        logger.warning(
                            "confidence_parse_error",
                            confidence_str=conf_str
                        )
                        confidence = 0.5
                else:
                    name = rest.strip()
            else:
                # No confidence specified
                name = rest.strip()
                logger.debug("no_confidence_in_response", using_default=0.5)
        except Exception as e:
            logger.error(
                "response_parsing_error",
                response=response,
                error=str(e),
                exc_info=True
            )
            name = rest.strip() if rest else None

        return {
            'match_type': match_type,
            'canonical_name': name if name else None,
            'confidence': confidence
        }
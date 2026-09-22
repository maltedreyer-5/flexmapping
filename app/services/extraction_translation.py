# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Translation of individual extractions.

Translation happens per extraction (validated_result to validated_result_en)
rather than per profile. Translating a whole profile means re-splitting the
rendered Markdown afterwards to find out which field each passage belongs to;
per field, the mapping is known from the start.

Sequence:
1. An extraction holds validated_result in the capture language
2. The LLM produces validated_result_en
3. The profile generator picks the field matching the requested language
"""
import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import structlog
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# Translation prompt, kept short and precise for single fields
# Language the extraction pipeline produces. The shipped category prompts are
# written in German and instruct the model to answer in German, so this is the
# side every translation starts from. Keeping it as a constant rather than a
# word inside the prompt is what a future per-category output language would
# hook into.
SOURCE_LANGUAGE = "de"

LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
}


def language_name(code: str) -> str:
    """
    Return the English name of a language code, for use in the prompt.

    An unknown code raises instead of quietly falling back to English. A
    translation that is actually English but stored under another language code
    cannot be detected by anything downstream, so a failed job is the better
    outcome.
    """
    try:
        return LANGUAGE_NAMES[code.lower()]
    except KeyError:
        raise ValueError(
            f"No language name configured for code '{code}'. "
            f"Add it to LANGUAGE_NAMES before requesting translations into it."
        ) from None


# Source and target language are parameters rather than fixed words, so that
# the language actually requested is the language the model is asked for.
#
# {field_context} carries the per-prompt translation_context from the category
# configuration where one is set. Those hints exist to disambiguate short
# fields whose meaning is not obvious from the label alone.
EXTRACTION_TRANSLATION_PROMPT = """Translate this {source_language} text to {target_language}.

CONTEXT: This is the "{field_name}" field from a profile about {category} at a university.
{field_context}
RULES:
- Keep formatting (lists, bullet points, bold, italic)
- Do NOT translate proper names (people, institutions, projects, products)
- Keep URLs and email addresses unchanged
- Keep technical abbreviations (API, LLM, GPT, KI, etc.)
- Keep {source_language} academic terms if no good {target_language} equivalent exists

{source_language} TEXT:
{text}

Respond with ONLY the {target_language} translation, no explanations."""


class ExtractionTranslationService:
    """Translates extractions field by field"""
    
    def __init__(self, llm_client, db_session: AsyncSession):
        self.llm_client = llm_client
        self.db = db_session
    
    async def translate_extraction(
        self,
        extraction,  # Extraction model
        category_name: str = "AI initiative",
        target_language: str = "en",
    ) -> Optional[str]:
        """
        Translate a single extraction.

        Args:
            extraction: extraction carrying a validated_result
            category_name: category, used as context
            target_language: language code to translate into

        Returns:
            The translation, or None on failure
        """
        if not extraction.validated_result:
            return None
        
        # Skip fields marked as not translatable
        if extraction.prompt and not extraction.prompt.translatable:
            return None
        
        field_name = extraction.prompt.display_name if extraction.prompt else "Unknown"

        # Hint configured for this field in the category YAML, if any. Rendered
        # as its own line so the prompt reads cleanly when there is none.
        hint = (extraction.prompt.translation_context or "").strip() if extraction.prompt else ""
        field_context = f'The "{field_name}" field means: {hint}\n' if hint else ""

        prompt = EXTRACTION_TRANSLATION_PROMPT.format(
            field_name=field_name,
            field_context=field_context,
            category=category_name,
            text=extraction.validated_result,
            source_language=language_name(SOURCE_LANGUAGE),
            target_language=language_name(target_language),
        )
        
        try:
            response = await self.llm_client.complete(
                prompt=prompt,
                max_tokens=len(extraction.validated_result) * 2,  # Genug Platz
                temperature=0.3  # Keep translations consistent
            )
            
            # LLMResponse carries a .text attribute
            translation = response.text.strip() if response.text else ""
            
            # Basis-Validierung
            if not translation or len(translation) < 3:
                logger.warning(
                    "Translation too short",
                    extraction_id=extraction.id,
                    original_length=len(extraction.validated_result)
                )
                return None
            
            # Sanity check: the length should be roughly comparable (plus or minus 50 percent)
            ratio = len(translation) / len(extraction.validated_result)
            if ratio < 0.3 or ratio > 3.0:
                logger.warning(
                    "Translation length suspicious",
                    extraction_id=extraction.id,
                    ratio=ratio
                )
                # Use it anyway; it may still be valid
            
            return translation
            
        except Exception as e:
            logger.error(
                "Translation failed",
                extraction_id=extraction.id,
                error=str(e)
            )
            return None
    
    async def translate_source_extractions(
        self,
        source_id: str,
        force: bool = False
    ) -> Dict[str, int]:
        """
        Translate every extraction belonging to one source.

        Args:
            source_id: UUID of the source
            force: if True, re-translate fields that already have a translation

        Returns:
            Dict of statistics
        """
        from app.models import Extraction, Source, Category
        from sqlalchemy.orm import joinedload
        
        stats = {
            'total': 0,
            'translated': 0,
            'skipped': 0,
            'failed': 0
        }
        
        # Load the source together with its category (eager loading)
        source_result = await self.db.execute(
            select(Source)
            .options(joinedload(Source.category))
            .where(Source.id == source_id)
        )
        source = source_result.scalar_one_or_none()
        
        if not source:
            logger.error("Source not found", source_id=source_id)
            return stats
        
        category_name = source.category.display_name_en if source.category else "AI initiative"
        
        # Load the extractions together with their prompts (eager loading)
        query = (
            select(Extraction)
            .options(joinedload(Extraction.prompt))
            .where(
                Extraction.source_id == source_id,
                Extraction.validated_result.is_not(None),
                Extraction.validated_result != ''
            )
        )
        
        if not force:
            query = query.where(
                or_(
                    Extraction.translation_status == 'pending',
                    Extraction.translation_status.is_(None)
                )
            )
        
        result = await self.db.execute(query)
        extractions = result.unique().scalars().all()
        stats['total'] = len(extractions)
        
        for extraction in extractions:
            # Skip non-translatable fields; the prompt is already loaded
            if extraction.prompt and not extraction.prompt.translatable:
                extraction.translation_status = 'skipped'
                stats['skipped'] += 1
                continue
            
            translation = await self.translate_extraction(extraction, category_name, target_language)
            
            if translation:
                extraction.validated_result_en = translation
                extraction.translation_status = 'translated'
                extraction.translated_at = datetime.now(timezone.utc)
                stats['translated'] += 1
            else:
                extraction.translation_status = 'failed'
                stats['failed'] += 1
            
            # Rate limiting
            await asyncio.sleep(0.5)
        
        await self.db.commit()
        
        logger.info(
            "Source extractions translated",
            source_id=str(source_id),
            **stats
        )
        
        return stats
    
    async def translate_all_pending(
        self,
        limit: int = 100,
        force: bool = False
    ) -> Dict[str, int]:
        """
        Translate all pending extractions.

        Args:
            limit: maximum number of extractions to translate
            force: if True, re-translate fields that already have a translation

        Returns:
            Dict of statistics
        """
        from app.models import Extraction, Prompt, Source, Category
        from sqlalchemy.orm import joinedload, selectinload
        
        stats = {
            'total': 0,
            'translated': 0,
            'skipped': 0,
            'failed': 0
        }
        
        # Query for pending translations, with eager loading
        query = (
            select(Extraction)
            .join(Prompt, Extraction.prompt_id == Prompt.id)
            .options(
                joinedload(Extraction.prompt),
                joinedload(Extraction.source).joinedload(Source.category)
            )
            .where(
                Extraction.validated_result.is_not(None),
                Extraction.validated_result != '',
                Prompt.translatable == True  # Translatable fields only
            )
        )
        
        if not force:
            query = query.where(
                or_(
                    Extraction.translation_status == 'pending',
                    Extraction.translation_status.is_(None),
                    Extraction.validated_result_en.is_(None)
                )
            )
        
        query = query.limit(limit)
        
        result = await self.db.execute(query)
        extractions = result.unique().scalars().all()  # unique() wegen joinedload
        stats['total'] = len(extractions)
        
        logger.info(f"Found {stats['total']} extractions to translate")
        
        for i, extraction in enumerate(extractions):
            # Category name for context, already loaded via joinedload
            category_name = "AI initiative"
            if extraction.source and extraction.source.category:
                category_name = extraction.source.category.display_name_en or extraction.source.category.display_name
            
            translation = await self.translate_extraction(extraction, category_name, target_language)
            
            if translation:
                extraction.validated_result_en = translation
                extraction.translation_status = 'translated'
                extraction.translated_at = datetime.now(timezone.utc)
                stats['translated'] += 1
            else:
                extraction.translation_status = 'failed'
                stats['failed'] += 1
            
            # Log progress every 10 extractions
            if (i + 1) % 10 == 0:
                logger.info(f"Translation progress: {i + 1}/{stats['total']}")
            
            # Commit in batches of 20 extractions
            if (i + 1) % 20 == 0:
                await self.db.commit()
            
            # Rate limiting
            await asyncio.sleep(0.5)
        
        await self.db.commit()
        
        logger.info("Translation batch completed", **stats)
        
        return stats
    
    async def get_translation_stats(self) -> Dict[str, int]:
        """
        Return translation statistics.

        Returns:
            Dict of counts per status
        """
        from app.models import Extraction, Prompt
        from sqlalchemy import func
        
        # Total with a validated_result
        total_result = await self.db.execute(
            select(func.count()).select_from(Extraction).where(
                Extraction.validated_result.is_not(None),
                Extraction.validated_result != ''
            )
        )
        total = total_result.scalar() or 0
        
        # Translatable, meaning the prompt has translatable=True
        translatable_result = await self.db.execute(
            select(func.count())
            .select_from(Extraction)
            .join(Prompt, Extraction.prompt_id == Prompt.id)
            .where(
                Extraction.validated_result.is_not(None),
                Extraction.validated_result != '',
                Prompt.translatable == True
            )
        )
        translatable = translatable_result.scalar() or 0
        
        # Grouped by status
        translated_result = await self.db.execute(
            select(func.count()).select_from(Extraction).where(
                Extraction.translation_status == 'translated'
            )
        )
        translated = translated_result.scalar() or 0
        
        pending_result = await self.db.execute(
            select(func.count())
            .select_from(Extraction)
            .join(Prompt, Extraction.prompt_id == Prompt.id)
            .where(
                Extraction.validated_result.is_not(None),
                Extraction.validated_result != '',
                Prompt.translatable == True,
                or_(
                    Extraction.translation_status == 'pending',
                    Extraction.translation_status.is_(None),
                    Extraction.validated_result_en.is_(None)
                )
            )
        )
        pending = pending_result.scalar() or 0
        
        failed_result = await self.db.execute(
            select(func.count()).select_from(Extraction).where(
                Extraction.translation_status == 'failed'
            )
        )
        failed = failed_result.scalar() or 0
        
        return {
            'total_extractions': total,
            'translatable': translatable,
            'translated': translated,
            'pending': pending,
            'failed': failed,
            'skipped': total - translatable,
            'progress_percent': round(translated / translatable * 100, 1) if translatable > 0 else 0
        }


# Helper for the profile generator
def get_extraction_value(extraction, language: str = 'de') -> Optional[str]:
    """
    Return the value of an extraction in the requested language.

    Args:
        extraction: Extraction model
        language: 'de' or 'en'

    Returns:
        validated_result or validated_result_en
    """
    if language == 'en' and extraction.validated_result_en:
        return extraction.validated_result_en
    return extraction.validated_result

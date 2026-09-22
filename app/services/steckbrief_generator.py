# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Profile generator: renders Markdown profiles from extractions.

Template variables that have no value are replaced with "-" rather than left
in place. An unsubstituted "$institution" in a published profile looks like a
broken page; a dash reads as "not stated", which is what it means.
"""
from datetime import datetime, timezone
from string import Template
from typing import Dict, Optional
from uuid import UUID
import re

import markdown2
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Steckbrief, Source, Extraction, Category, Prompt
from app.repositories import (
    CategoryRepository, ExtractionRepository,
    PromptRepository, SourceRepository, SteckbriefRepository
)

logger = structlog.get_logger()


class SteckbriefGeneratorError(Exception):
    """Raised for profile generation errors"""
    pass


class SteckbriefGenerator:
    """Renders Markdown profiles from extractions"""

    # Pfad zu Templates

    def __init__(self, session: AsyncSession):
        self.session = session
        self.source_repo = SourceRepository(Source, session)
        self.extraction_repo = ExtractionRepository(Extraction, session)
        self.category_repo = CategoryRepository(Category, session)
        self.prompt_repo = PromptRepository(Prompt, session)
        self.steckbrief_repo = SteckbriefRepository(Steckbrief, session)

    def _get_template(self, category: Category, language: str = 'de') -> Optional[str]:
        """
        Return the profile template of a category.

        The template comes from the category definition, which is loaded from
        the YAML configuration file. There is one source, so changing the
        template in the configuration changes the rendered profile.

        The language parameter is accepted because callers pass it, but the
        template itself is language-independent: it is a layout of headings and
        `$variable` placeholders, and the values substituted into it are taken
        from the extraction in the requested language.
        """
        return category.steckbrief_template

    async def generate(
        self, 
        source_id: UUID,
        language: str = 'de'
    ) -> Steckbrief:
        """
        Generate the profile for one source.

        Args:
            source_id: source UUID
            language: language ('de' or 'en')

        Returns:
            Steckbrief object

        Raises:
            SteckbriefGeneratorError: on unrecoverable errors
        """
        logger.info("generating_steckbrief", source_id=str(source_id), language=language)

        try:
            # 1. Load the source with its details
            source = await self.source_repo.get_with_extractions(source_id)
            if not source:
                raise SteckbriefGeneratorError(f"Source {source_id} not found")

            if not source.category_id:
                raise SteckbriefGeneratorError(f"Source {source_id} has no category")

            # 2. Load the category
            category = await self.category_repo.get(source.category_id)
            if not category:
                raise SteckbriefGeneratorError(
                    f"Category {source.category_id} not found"
                )

            # 3. Load the template for the requested language
            template = self._get_template(category, language)
            if not template:
                raise SteckbriefGeneratorError(
                    f"No template for category {category.internal_name}, language {language}"
                )

            # 4. Load every extraction
            extractions = await self.extraction_repo.get_by_source(source_id)

            if not extractions:
                logger.warning(
                    "no_extractions_found",
                    source_id=str(source_id)
                )

            # 5. Filter by active field groups and confidence, per language
            field_values = self._collect_field_values(extractions, category, language)

            logger.info(
                "field_values_collected",
                source_id=str(source_id),
                language=language,
                num_fields=len(field_values),
                fields=list(field_values.keys())
            )

            # 6. Render the template
            markdown = self._render_template(
                template,
                field_values,
                source
            )

            # 6. HTML konvertieren
            html = self._markdown_to_html(markdown)

            # 7. Store. The two languages are stored in different places:
            if language == 'en':
                # the English profile goes into SteckbriefTranslation,
                steckbrief = await self._save_english_translation(
                    source_id,
                    markdown,
                    html
                )
            else:
                # the German one into the profile table itself
                steckbrief = await self._save_steckbrief(
                    source_id,
                    markdown,
                    html
                )

            logger.info(
                "steckbrief_generated",
                source_id=str(source_id),
                steckbrief_id=steckbrief.id,
                markdown_length=len(markdown),
                html_length=len(html)
            )

            return steckbrief

        except SteckbriefGeneratorError:
            # Re-raise unsere eigenen Errors
            raise
        except Exception as e:
            logger.error(
                "steckbrief_generation_failed",
                source_id=str(source_id),
                error=str(e),
                exc_info=True
            )
            raise SteckbriefGeneratorError(
                f"Failed to generate steckbrief for {source_id}: {e}"
            )

    def _collect_field_values(
        self,
        extractions: list[Extraction],
        category: Category,
        language: str = 'de'
    ) -> Dict[str, str]:
        """
        Collect and filter field values from the extractions.

        Args:
            extractions: list of extractions
            category: the category, carrying its active groups
            language: language ('de' or 'en')

        Returns:
            Dict of filtered field values
        """
        field_values = {}

        for extraction in extractions:
            prompt = extraction.prompt

            # Fields from active groups only
            if prompt.field_group not in category.active_groups:
                logger.debug(
                    "skipping_field_not_in_active_group",
                    field=prompt.internal_name,
                    group=prompt.field_group,
                    active_groups=category.active_groups
                )
                continue

            # High-confidence fields only
            if extraction.final_confidence < prompt.required_confidence:
                logger.debug(
                    "skipping_field_low_confidence",
                    field=prompt.internal_name,
                    confidence=extraction.final_confidence,
                    required=prompt.required_confidence
                )
                continue

            # Pick the value matching the requested language
            if language == 'en':
                # English: prefer validated_result_en, fall back to validated_result
                value = extraction.validated_result_en or extraction.validated_result or extraction.raw_result
            else:
                # Deutsch: validated_result verwenden
                value = extraction.validated_result or extraction.raw_result

            # Non-empty values only
            if value and value.strip():
                field_values[prompt.internal_name] = value.strip()
            else:
                logger.debug(
                    "skipping_empty_field",
                    field=prompt.internal_name
                )

        return field_values

    async def _save_steckbrief(
        self,
        source_id: UUID,
        markdown: str,
        html: str
    ) -> Steckbrief:
        """
        Insert or update the German profile.

        Args:
            source_id: source UUID
            markdown: Markdown content
            html: HTML content

        Returns:
            The stored profile
        """
        existing = await self.steckbrief_repo.get_by_source(source_id)

        if existing:
            logger.info(
                "updating_existing_steckbrief",
                steckbrief_id=existing.id,
                source_id=str(source_id)
            )
            existing.markdown_content = markdown
            existing.html_content = html
            existing.generated_at = datetime.now(timezone.utc)
            steckbrief = await self.steckbrief_repo.update_obj(existing)
        else:
            logger.info(
                "creating_new_steckbrief",
                source_id=str(source_id)
            )
            steckbrief = Steckbrief(
                source_id=source_id,
                markdown_content=markdown,
                html_content=html,
                generated_at=datetime.now(timezone.utc),
                published=False
            )
            steckbrief = await self.steckbrief_repo.create(steckbrief)

        return steckbrief

    async def _save_english_translation(
        self,
        source_id: UUID,
        markdown: str,
        html: str
    ) -> Steckbrief:
        """
        Store the English translation in SteckbriefTranslation.

        The German profile has to exist already: the translation row
        references it, and the source hash used for cache invalidation is
        taken from its content.

        Args:
            source_id: source UUID
            markdown: English Markdown content
            html: English HTML content (currently unused)

        Returns:
            The existing German profile, so that the return type matches
            generate()
        """
        from app.models import SteckbriefTranslation
        from sqlalchemy import select
        import hashlib
        
        # The German profile has to exist first
        steckbrief = await self.steckbrief_repo.get_by_source(source_id)
        if not steckbrief:
            raise SteckbriefGeneratorError(
                f"Cannot create EN translation: DE Steckbrief for {source_id} does not exist"
            )
        
        # Hash of the German content, used to invalidate the cache
        source_hash = hashlib.sha256(
            (steckbrief.markdown_content or "").encode('utf-8')
        ).hexdigest()
        
        # Does an English translation already exist?
        result = await self.session.execute(
            select(SteckbriefTranslation).where(
                SteckbriefTranslation.steckbrief_id == steckbrief.id,
                SteckbriefTranslation.language == 'en'
            )
        )
        existing_translation = result.scalar_one_or_none()
        
        if existing_translation:
            logger.info(
                "updating_english_translation",
                steckbrief_id=steckbrief.id,
                translation_id=existing_translation.id
            )
            existing_translation.markdown_content = markdown
            existing_translation.source_hash = source_hash
            existing_translation.translated_at = datetime.now(timezone.utc)
        else:
            logger.info(
                "creating_english_translation",
                steckbrief_id=steckbrief.id
            )
            new_translation = SteckbriefTranslation(
                steckbrief_id=steckbrief.id,
                language='en',
                markdown_content=markdown,
                source_hash=source_hash
            )
            self.session.add(new_translation)
        
        await self.session.flush()
        
        logger.info(
            "english_translation_saved",
            steckbrief_id=steckbrief.id,
            source_id=str(source_id)
        )
        
        return steckbrief

    def _render_template(
        self,
        template: str,
        values: Dict[str, str],
        source: Source
    ) -> str:
        """
        Render the template with the collected values.

        Args:
            template: template string, using $variable syntax
            values: field values
            source: source object, for metadata

        Returns:
            The rendered Markdown
        """
        # Template-Engine (Python string.Template)
        t = Template(template)

        # Missing values are left empty rather than raising
        safe_values = values.copy()

        # Add the source metadata
        safe_values['source_url'] = source.url
        safe_values['crawled_at'] = (
            source.crawled_at.strftime('%Y-%m-%d')
            if source.crawled_at
            else datetime.now(timezone.utc).strftime('%Y-%m-%d')
        )

        try:
            # First substitution, with the values we have
            rendered = t.safe_substitute(safe_values)

            # Replace every template variable that is still unfilled with "-"
            # The pattern covers both $variable and ${variable}
            rendered = re.sub(r'\$\{?[a-zA-Z_][a-zA-Z0-9_]*\}?', '-', rendered)

            logger.debug(
                "template_rendered",
                placeholders_used=len(values),
                template_length=len(template),
                output_length=len(rendered)
            )
            return rendered

        except Exception as e:
            logger.error(
                "template_rendering_error",
                error=str(e),
                available_fields=list(safe_values.keys()),
                exc_info=True
            )
            # Fallback: Einfache Markdown
            logger.warning("using_fallback_template")
            return self._generate_fallback_markdown(safe_values, source)

    def _generate_fallback_markdown(
        self,
        values: Dict[str, str],
        source: Source
    ) -> str:
        """
        Produce fallback Markdown when the template fails.

        Args:
            values: field values
            source: source object

        Returns:
            A plain Markdown rendering
        """
        lines = [
            f"# {values.get('project_name', values.get('service_name', 'Unbenanntes Projekt'))}",
            "",
            f"**URL:** {source.url}",
            ""
        ]

        # Emit every field that is available
        for key, value in sorted(values.items()):
            if key not in ['source_url', 'crawled_at', 'project_name', 'service_name']:
                # Capitalise the key, for readability
                display_key = key.replace('_', ' ').title()
                lines.append(f"**{display_key}:** {value}")
                lines.append("")

        logger.debug(
            "fallback_markdown_generated",
            num_fields=len(values)
        )

        return "\n".join(lines)

    def _markdown_to_html(self, markdown_text: str) -> str:
        """
        Konvertiere Markdown zu HTML

        Args:
            markdown_text: Markdown content

        Returns:
            HTML string
        """
        if not markdown_text or not markdown_text.strip():
            logger.warning("empty_markdown_for_html_conversion")
            return "<p>Kein Inhalt verfügbar</p>"

        try:
            html = markdown2.markdown(
                markdown_text,
                extras=[
                    "fenced-code-blocks",
                    "tables",
                    "header-ids",
                    "metadata",
                    "code-friendly"  # Bessere Code-Darstellung
                ]
            )

            logger.debug(
                "markdown_converted_to_html",
                markdown_length=len(markdown_text),
                html_length=len(html)
            )

            return html
        except Exception as e:
            logger.error(
                "markdown_to_html_error",
                error=str(e),
                markdown_preview=markdown_text[:100],
                exc_info=True
            )
            # Fallback: wrap the Markdown in <pre> to keep its formatting
            return f"<div class='markdown-fallback'><pre>{markdown_text}</pre></div>"
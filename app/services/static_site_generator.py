# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Static site generator: renders the public website from published profiles.

Everything it writes is relative to public_site_dir, and every internal link
is relative to the site root. The generated tree therefore works unchanged
whether it is served by a web server at /, by a CDN, or by this application
under /public.

The German and the English site are generated separately, into sibling
directories, because they contain different sets of profiles: only sources
with a translation appear in the English one.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound
from markdown2 import markdown
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Category, Steckbrief, Source, Extraction
from app.repositories import (
    CategoryRepository,
    SteckbriefRepository,
    SourceRepository,
    ExtractionRepository
)

logger = structlog.get_logger()
settings = get_settings()


class StaticSiteGeneratorError(Exception):
    """Raised for site generation errors"""
    pass


class StaticSiteGenerator:
    """Renders the public website from published profiles"""

    # Marker written into the output directory. Its presence is what permits
    # the next run to delete the directory contents; see _prepare_output_dir.
    OUTPUT_MARKER = ".flexmapping-site"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.output_dir = Path(settings.public_site_dir)
        # Resolved relative to the package, not to the current working
        # directory. Starting the CLI from anywhere other than the repository
        # root used to raise "Template directory not found".
        self.template_dir = Path(__file__).resolve().parent.parent.parent / "public_templates"
        self.base_url = settings.static_site_base_url

        # URL prefix for links inside the generated site.
        # The generated tree is self-contained, so every internal link is
        # relative to the site root. That keeps the same output usable whether
        # it is served at / by a web server or under /public by the application.
        # Path the generated site will be served under. Every internal link is
        # built from it, so an empty value produces root-relative links for a
        # web server or CDN, and "/public" produces links that work when the
        # application serves the same directory under that path.
        self.url_prefix = settings.public_site_url_prefix.rstrip("/")
        self.site_root = self.url_prefix

        # Repositories
        self.steckbrief_repo = SteckbriefRepository(Steckbrief, session)
        self.category_repo = CategoryRepository(Category, session)
        self.source_repo = SourceRepository(Source, session)
        self.extraction_repo = ExtractionRepository(Extraction, session)

        # Validate template directory exists
        if not self.template_dir.exists():
            raise StaticSiteGeneratorError(
                f"Template directory not found: {self.template_dir}"
            )

        # Jinja2 Environment
        try:
            self.env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=select_autoescape(['html', 'xml']),
                trim_blocks=True,
                lstrip_blocks=True
            )

            # Custom Jinja filters
            def date_filter(value, format='%d.%m.%Y'):
                """
                Format datetime or string to readable date
                Handles: datetime objects, ISO strings, 'now' keyword
                """
                if value is None:
                    return ""

                # Handle 'now' keyword
                if isinstance(value, str):
                    if value.lower() == 'now':
                        value = datetime.now(timezone.utc)
                    else:
                        # Try to parse ISO format strings
                        try:
                            if 'T' in value:
                                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            elif len(value) == 10:  # YYYY-MM-DD
                                value = datetime.strptime(value, '%Y-%m-%d')
                            else:
                                return value
                        except:
                            return value

                if hasattr(value, 'strftime'):
                    try:
                        return value.strftime(format)
                    except:
                        return str(value)

                return str(value)

            def striptags_filter(value):
                """Remove HTML tags from string"""
                if not value:
                    return ""
                import re
                return re.sub(r'<[^>]+>', '', str(value))

            self.env.filters['date'] = date_filter
            self.env.filters['markdown'] = lambda text: markdown(text) if text else ""
            self.env.filters['striptags'] = striptags_filter
            
            def get_title_filter(markdown_content):
                """Extract the title alone from Markdown, without the institution"""
                if not markdown_content:
                    return "Untitled"
                
                lines = markdown_content.split('\n')
                if lines and lines[0].startswith('#'):
                    return lines[0].lstrip('#').strip()
                return "Untitled"
            
            self.env.filters['get_title'] = get_title_filter
            
            def get_institution_filter(markdown_content):
                """Extract the institution from Markdown"""
                import re
                
                if not markdown_content:
                    return ""
                
                lines = markdown_content.split('\n')
                for line in lines[:15]:
                    if 'Institution' in line and ':' in line:
                        institution = line.split(':', 1)[-1].strip()
                        # Markdown-Formatierung entfernen
                        institution = re.sub(r'\*+', '', institution).strip()
                        if institution and institution not in ['Nicht angegeben', '-']:
                            return institution
                return ""
            
            self.env.filters['get_institution'] = get_institution_filter
            
            def get_description_filter(markdown_content, max_length=200):
                """
                Extract a short description from the Markdown content.

                Looks for a description section and falls back to the first
                paragraph.
                """
                import re
                
                if not markdown_content:
                    return ""
                
                lines = markdown_content.split('\n')
                in_description = False
                description_lines = []
                
                # Look for the description section first
                for line in lines:
                    # Find the description section, in any of its spellings
                    if re.match(r'^##\s*(Beschreibung|Description|Kurzbeschreibung)', line, re.IGNORECASE):
                        in_description = True
                        continue
                    
                    # A new section ends the description
                    if in_description and line.startswith('##'):
                        break
                    
                    # Beschreibungszeilen sammeln
                    if in_description and line.strip():
                        # Markdown-Formatierung entfernen
                        clean_line = re.sub(r'\*+', '', line.strip())
                        clean_line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean_line)
                        if clean_line:
                            description_lines.append(clean_line)
                
                # No description section: take the first paragraph after the heading
                if not description_lines:
                    skip_header = True
                    for line in lines:
                        # Skip the heading
                        if skip_header and (line.startswith('#') or not line.strip()):
                            if not line.startswith('#') and not line.strip():
                                skip_header = False
                            continue
                        
                        # Skip metadata lines such as Institution: or URL:
                        if ':' in line and any(kw in line for kw in ['Institution', 'URL', 'Datum', 'Status', 'Kategorie']):
                            continue
                        
                        # Neue Sektion = Ende
                        if line.startswith('##'):
                            break
                        
                        if line.strip():
                            clean_line = re.sub(r'\*+', '', line.strip())
                            clean_line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean_line)
                            if clean_line:
                                description_lines.append(clean_line)
                                # One paragraph only
                                if len(' '.join(description_lines)) > max_length:
                                    break
                
                description = ' '.join(description_lines)
                
                # Truncate to max_length
                if len(description) > max_length:
                    description = description[:max_length-3].rsplit(' ', 1)[0] + '...'
                
                return description
            
            self.env.filters['get_description'] = get_description_filter
            
            def linkify_institutions_filter(markdown_content, url_prefix=''):
                """
                Turn institution names in the Markdown into search links.

                Recognises the spellings that occur in the generated profiles:
                - **Institution:** Name
                - Institution: Name
                - **Institution**: Name
                """
                import re
                from urllib.parse import quote
                
                if not markdown_content:
                    return markdown_content
                
                # English or German search page?
                search_page = 'search.html' if '/en' in url_prefix else 'suche.html'
                
                lines = markdown_content.split('\n')
                result_lines = []
                
                for line in lines:
                    # Patterns for the different spellings:
                    # **Institution:** Name
                    # **Institution**: Name
                    # Institution: Name
                    patterns = [
                        r'^(\*\*Institution:\*\*\s*)(.+)$',       # **Institution:** Name
                        r'^(\*\*Institution\*\*:\s*)(.+)$',       # **Institution**: Name
                        r'^(Institution:\s*)(.+)$',               # Institution: Name
                    ]
                    
                    matched = False
                    for pattern in patterns:
                        match = re.match(pattern, line, re.IGNORECASE)
                        if match:
                            prefix = match.group(1)
                            institution = match.group(2).strip()
                            # Strip Markdown formatting before putting the name into a URL
                            clean_institution = re.sub(r'\*+', '', institution).strip()
                            if clean_institution and clean_institution not in ['Nicht angegeben', '-', '', 'N/A']:
                                # URL-encode for the query parameter
                                encoded = quote(clean_institution)
                                # Render as a Markdown link
                                linked = f'{prefix}[{institution}]({url_prefix}/{search_page}?q={encoded})'
                                result_lines.append(linked)
                                matched = True
                                break
                    
                    if not matched:
                        result_lines.append(line)
                
                return '\n'.join(result_lines)
            
            self.env.filters['linkify_institutions'] = linkify_institutions_filter
            
            # Kept for templates that still call the old filter name
            def title_with_institution_filter(markdown_content):
                """Kept for templates that still call the old filter name; returns the title"""
                return get_title_filter(markdown_content)
            
            self.env.filters['title_with_institution'] = title_with_institution_filter

            logger.info(
                "static_site_generator_initialized",
                template_dir=str(self.template_dir),
                output_dir=str(self.output_dir),
                url_prefix=self.url_prefix
            )
        except Exception as e:
            logger.error("Failed to initialize Jinja2 environment", error=str(e))
            raise StaticSiteGeneratorError(f"Jinja2 initialization failed: {e}")

    def _extract_title(self, markdown_content: str) -> str:
        """Extract the title from Markdown content"""
        if not markdown_content:
            return "Untitled"
        
        lines = markdown_content.split('\n')
        if lines and lines[0].startswith('#'):
            return lines[0].lstrip('#').strip()
        return "Untitled"
    
    def _extract_institution(self, markdown_content: str) -> str:
        """Extract the institution from Markdown content"""
        import re
        
        if not markdown_content:
            return ""
        
        lines = markdown_content.split('\n')
        for line in lines[:20]:  # Search the first 20 lines
            if 'Institution' in line and ':' in line:
                institution = line.split(':', 1)[-1].strip()
                # Markdown-Formatierung entfernen
                institution = re.sub(r'\*+', '', institution).strip()
                # Links entfernen [text](url) -> text
                institution = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', institution)
                if institution and institution not in ['Nicht angegeben', '-', '']:
                    return institution
        return ""
    
    def _extract_description(self, markdown_content: str) -> str:
        """Extract the description from Markdown content"""
        if not markdown_content:
            return ""
        
        lines = markdown_content.split('\n')
        in_description = False
        description_lines = []
        
        for line in lines:
            # Beschreibungs-Sektion finden
            if line.strip().lower() in ['## beschreibung', '## description']:
                in_description = True
                continue
            
            # A new section ends the description
            if in_description and line.startswith('##'):
                break
            
            # Beschreibungszeilen sammeln
            if in_description and line.strip():
                description_lines.append(line.strip())
        
        description = ' '.join(description_lines)
        
        # Truncate to 300 characters
        if len(description) > 300:
            description = description[:297] + '...'
        
        return description

    async def generate_full_site(self) -> Dict[str, int]:
        """
        Generate the complete static website.

        Returns:
            Dict of statistics (pages_generated, categories, steckbriefe, errors)
        """
        logger.info("Starting full site generation")

        stats = {
            'pages_generated': 0,
            'categories': 0,
            'steckbriefe': 0,
            'errors': 0
        }

        try:
            # Prepare the output directory
            self._prepare_output_dir()

            # 1. Assets kopieren
            try:
                self._copy_assets()
            except Exception as e:
                logger.error("Failed to copy assets", error=str(e))
                stats['errors'] += 1

            # 2. Load the data
            categories = await self.category_repo.get_active()
            all_steckbriefe = await self.steckbrief_repo.get_published()

            logger.info(
                "data_loaded",
                categories_count=len(categories),
                steckbriefe_count=len(all_steckbriefe)
            )

            # Group by category
            steckbriefe_by_category = {}
            for steckbrief in all_steckbriefe:
                cat_id = steckbrief.source.category_id
                if cat_id not in steckbriefe_by_category:
                    steckbriefe_by_category[cat_id] = []
                steckbriefe_by_category[cat_id].append(steckbrief)

            # 3. Homepage generieren
            try:
                await self._generate_homepage(categories, all_steckbriefe)
                stats['pages_generated'] += 1
            except Exception as e:
                logger.error("Failed to generate homepage", error=str(e), exc_info=True)
                stats['errors'] += 1

            # 4. Generate the category pages
            for category in categories:
                try:
                    steckbriefe = steckbriefe_by_category.get(category.id, [])
                    await self._generate_category_page(category, steckbriefe)
                    stats['categories'] += 1
                    stats['pages_generated'] += 1
                except Exception as e:
                    logger.error(
                        "Failed to generate category page",
                        category=category.internal_name,
                        error=str(e),
                        exc_info=True
                    )
                    stats['errors'] += 1

            # 5. Detail-Seiten generieren
            for steckbrief in all_steckbriefe:
                try:
                    await self._generate_detail_page(steckbrief)
                    stats['steckbriefe'] += 1
                    stats['pages_generated'] += 1
                    logger.debug(
                        "detail_page_generated",
                        steckbrief_id=steckbrief.id,
                        source_id=str(steckbrief.source_id)
                    )
                except Exception as e:
                    logger.error(
                        "Failed to generate detail page",
                        steckbrief_id=steckbrief.id,
                        source_id=str(steckbrief.source_id),
                        error=str(e),
                        exc_info=True
                    )
                    stats['errors'] += 1

            # 6. Generate the search page
            try:
                await self._generate_search_page(categories)
                stats['pages_generated'] += 1
            except Exception as e:
                logger.error("Failed to generate search page", error=str(e))
                stats['errors'] += 1

            # 7. Generate the search index (JSON)
            try:
                await self._generate_search_index(all_steckbriefe)
            except Exception as e:
                logger.error("Failed to generate search index", error=str(e))
                stats['errors'] += 1

            # 8. Sitemap generieren
            try:
                await self._generate_sitemap(categories, all_steckbriefe)
            except Exception as e:
                logger.error("Failed to generate sitemap", error=str(e))
                stats['errors'] += 1

            # 9. Static pages (Impressum, etc.)
            try:
                await self._generate_static_pages()
                stats['pages_generated'] += 2
            except Exception as e:
                logger.error("Failed to generate static pages", error=str(e))
                stats['errors'] += 1

            # 10. ENGLISCHE VERSION GENERIEREN
            try:
                logger.info("Starting English site generation as part of full site")
                en_stats = await self.generate_english_site()
                stats['pages_generated'] += en_stats.get('pages_generated', 0)
                stats['errors'] += en_stats.get('errors', 0)
                # Additional statistics for the English version
                stats['en_steckbriefe'] = en_stats.get('steckbriefe', 0)
                stats['en_skipped'] = en_stats.get('skipped', 0)
                logger.info("English site generation completed", **en_stats)
            except Exception as e:
                logger.error("Failed to generate English site", error=str(e), exc_info=True)
                stats['errors'] += 1

            logger.info("Site generation completed", **stats)
            return stats

        except Exception as e:
            logger.error("Site generation failed critically", error=str(e), exc_info=True)
            stats['errors'] += 1
            return stats

    def _prepare_output_dir(self):
        """
        Create or empty the output directory.

        Everything inside the directory is deleted, and the path comes from
        PUBLIC_SITE_DIR or from --output-dir. A typo there used to be enough to
        erase an unrelated directory, so a marker file is required before
        anything is removed: either the directory is empty, or it carries the
        marker from a previous generation run.
        """
        try:
            if self.output_dir.exists():
                marker = self.output_dir / self.OUTPUT_MARKER
                existing = list(self.output_dir.iterdir())

                if existing and not marker.exists():
                    raise StaticSiteGeneratorError(
                        f"Refusing to clear '{self.output_dir}': it is not empty and carries no "
                        f"'{self.OUTPUT_MARKER}' marker, so it was not produced by this generator. "
                        f"Point PUBLIC_SITE_DIR at a directory used only for the generated site, "
                        f"or create the marker file yourself if this really is the right target."
                    )

                for item in existing:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                logger.info("Cleared output directory", path=str(self.output_dir))
            else:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Created output directory", path=str(self.output_dir))

            # Written before any content, so an interrupted run still leaves a
            # directory that the next run is allowed to clear.
            (self.output_dir / self.OUTPUT_MARKER).write_text(
                "This directory is generated by FlexMapping and is emptied on every run.\n"
                "Do not store anything here that you want to keep.\n",
                encoding="utf-8",
            )

            # Create subdirectories
            (self.output_dir / "assets" / "css").mkdir(parents=True, exist_ok=True)
            (self.output_dir / "assets" / "js").mkdir(parents=True, exist_ok=True)
            (self.output_dir / "assets" / "data").mkdir(parents=True, exist_ok=True)
            (self.output_dir / "details").mkdir(parents=True, exist_ok=True)

            logger.info("Output directory prepared", path=str(self.output_dir))
        except Exception as e:
            logger.error("Failed to prepare output directory", error=str(e))
            raise StaticSiteGeneratorError(f"Cannot prepare output directory: {e}")

    def _copy_assets(self):
        """Kopiert CSS/JS Assets"""
        assets_src = self.template_dir / "assets"
        assets_dst = self.output_dir / "assets"

        if not assets_src.exists():
            logger.warning("Assets source directory not found", path=str(assets_src))
            return

        try:
            # CSS
            css_src = assets_src / "css"
            if css_src.exists():
                for css_file in css_src.glob("*.css"):
                    try:
                        shutil.copy2(css_file, assets_dst / "css" / css_file.name)
                        logger.debug("CSS file copied", file=css_file.name)
                    except Exception as e:
                        logger.warning("Failed to copy CSS file", file=css_file.name, error=str(e))

            # JS
            js_src = assets_src / "js"
            if js_src.exists():
                for js_file in js_src.glob("*.js"):
                    try:
                        shutil.copy2(js_file, assets_dst / "js" / js_file.name)
                        logger.debug("JS file copied", file=js_file.name)
                    except Exception as e:
                        logger.warning("Failed to copy JS file", file=js_file.name, error=str(e))

            logger.info("Assets copied successfully")
        except Exception as e:
            logger.error("Asset copying failed", error=str(e))
            raise

    def _safe_write_file(self, path: Path, content: str):
        """Sicheres Schreiben"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            logger.debug("File written", path=str(path), size=len(content))
        except Exception as e:
            logger.error("Failed to write file", path=str(path), error=str(e))
            raise StaticSiteGeneratorError(f"Cannot write file {path}: {e}")

    def _safe_render_template(self, template_name: str, **context) -> str:
        """Render a template, with the i18n strings in context"""
        try:
            template = self.env.get_template(template_name)
            # url_prefix is added to every template context, so that no
            # template has to know where the site is mounted. It carries the
            # language segment for the English tree.
            context['url_prefix'] = context.get('url_prefix', self.url_prefix)
            # site_root is the same path without the language segment. The
            # language switch has to leave /en/ behind, so it cannot use
            # url_prefix.
            context['site_root'] = self.site_root
            
            # i18n: load the German strings unless the caller passed another set
            if 'i18n' not in context:
                context['i18n'] = self._load_i18n('de')
            if 'language' not in context:
                context['language'] = 'de'
            
            return template.render(**context)
        except TemplateNotFound:
            logger.error("Template not found", template=template_name)
            raise StaticSiteGeneratorError(f"Template not found: {template_name}")
        except Exception as e:
            logger.error("Template rendering failed", template=template_name, error=str(e), exc_info=True)
            raise StaticSiteGeneratorError(f"Template rendering failed: {e}")

    def _get_steckbrief_title(self, steckbrief: Steckbrief) -> str:
        """Extract the title from a profile's Markdown"""
        if not steckbrief.markdown_content:
            return "Untitled"

        first_line = steckbrief.markdown_content.split('\n')[0]
        if first_line.startswith('#'):
            return first_line.lstrip('#').strip()
        return first_line.strip() or "Untitled"

    async def _generate_homepage(
        self,
        categories: List[Category],
        all_steckbriefe: List[Steckbrief]
    ):
        """Generate the homepage"""

        # Compute the statistics
        stats = {}
        for category in categories:
            count = sum(1 for s in all_steckbriefe
                       if s.source.category_id == category.id)
            stats[category.internal_name] = count

        # Neueste Steckbriefe (top 6)
        latest = sorted(all_steckbriefe,
                       key=lambda s: s.generated_at,
                       reverse=True)[:6]

        html = self._safe_render_template(
            'homepage.html',
            categories=categories,
            stats=stats,
            total_count=len(all_steckbriefe),  # Total count, for the page header
            latest_steckbriefe=latest,
            base_url=self.base_url
        )

        output_file = self.output_dir / "index.html"
        self._safe_write_file(output_file, html)

        logger.info("Homepage generated", latest_count=len(latest))

    async def _generate_category_page(
        self,
        category: Category,
        steckbriefe: List[Steckbrief]
    ):
        """Generate a category page"""

        steckbriefe_sorted = sorted(
            steckbriefe,
            key=lambda s: s.generated_at,
            reverse=True
        )

        # Distinct institutions, for the filter
        institutions = set()
        for steckbrief in steckbriefe:
            try:
                extractions = await self.extraction_repo.get_by_source(steckbrief.source_id)
                for ext in extractions:
                    if (ext.prompt.internal_name == 'institution'
                        and ext.validated_result
                        and ext.validated_result.strip()):
                        institutions.add(ext.validated_result)
            except Exception as e:
                logger.warning("Failed to extract institution", steckbrief_id=steckbrief.id, error=str(e))

        html = self._safe_render_template(
            'category.html',
            category=category,
            steckbriefe=steckbriefe_sorted,
            institutions=sorted(institutions),
            base_url=self.base_url
        )

        # Create the category directory
        cat_dir = self.output_dir / category.internal_name
        cat_dir.mkdir(exist_ok=True)

        output_file = cat_dir / "index.html"
        self._safe_write_file(output_file, html)

        logger.info("Category page generated", category=category.internal_name, steckbriefe_count=len(steckbriefe))

    async def _generate_detail_page(self, steckbrief: Steckbrief):
        """Generate a profile detail page"""

        # Load every extraction, for the metadata
        extractions = await self.extraction_repo.get_by_source(steckbrief.source_id)

        # Convert the extractions into a dict
        extraction_dict = {}
        for ext in extractions:
            if (ext.validated_result
                and ext.validated_result.strip()
                and ext.final_confidence >= ext.prompt.required_confidence):
                extraction_dict[ext.prompt.internal_name] = {
                    'value': ext.validated_result,
                    'confidence': ext.final_confidence,
                    'display_name': ext.prompt.display_name
                }

        html = self._safe_render_template(
            'detail.html',
            steckbrief=steckbrief,
            source=steckbrief.source,
            category=steckbrief.source.category,
            extractions=extraction_dict,
            base_url=self.base_url
        )

        output_file = self.output_dir / "details" / f"{steckbrief.source_id}.html"
        self._safe_write_file(output_file, html)

        logger.debug("Detail page written", path=str(output_file))

    async def _generate_search_page(self, categories: List[Category]):
        """Generate the search page"""

        html = self._safe_render_template(
            'search.html',
            categories=categories,
            base_url=self.base_url
        )

        output_file = self.output_dir / "suche.html"
        self._safe_write_file(output_file, html)

        logger.info("Search page generated")

    async def _generate_search_index(self, steckbriefe: List[Steckbrief]):
        """
        Generate the search index (JSON) for the client-side search.

        The index carries more than the visible fields: every extracted field,
        the full text of the Markdown, and the entity variants. Searching for
        "HU Berlin" has to find an entry whose profile spells the institution
        out in full.
        """
        from sqlalchemy import select
        from app.models import Entity, EntityVariant

        index = []

        for steckbrief in steckbriefe:
            try:
                extractions = await self.extraction_repo.get_by_source(steckbrief.source_id)

                title = ""
                description = ""
                institution = ""
                
                # Collect every field for full-text search
                all_text_parts = []
                
                # Entity ids, to look their variants up
                linked_entity_ids = set()

                for ext in extractions:
                    if ext.validated_result and ext.validated_result.strip():
                        result = ext.validated_result.strip()
                        
                        # Extract the specific fields
                        if ext.prompt.internal_name in ['project_name', 'service_name', 'course_name', 'title']:
                            title = result
                        elif ext.prompt.internal_name in ['description', 'short_description', 'public_description']:
                            if not description:
                                description = result[:300]
                        elif ext.prompt.internal_name == 'institution':
                            institution = result
                        
                        # Collect every field for the full text
                        all_text_parts.append(result)
                        
                        # Remember the entity link
                        if ext.linked_entity_id:
                            linked_entity_ids.add(ext.linked_entity_id)

                # Load the entity variants (for example "HU Berlin", "Humboldt-Uni")
                entity_variants = []
                if linked_entity_ids:
                    try:
                        variant_result = await self.session.execute(
                            select(EntityVariant.variant_name)
                            .where(EntityVariant.entity_id.in_(linked_entity_ids))
                        )
                        entity_variants = [v[0] for v in variant_result.fetchall()]
                        
                        # Include the canonical names as well
                        entity_result = await self.session.execute(
                            select(Entity.canonical_name)
                            .where(Entity.id.in_(linked_entity_ids))
                        )
                        entity_variants.extend([e[0] for e in entity_result.fetchall()])
                    except Exception as e:
                        logger.debug("Could not load entity variants", error=str(e))

                # Fallback: take the title from the Markdown
                if not title:
                    title = self._get_steckbrief_title(steckbrief)

                # Full text: every field plus the Markdown content, without HTML tags
                fulltext_parts = all_text_parts.copy()
                
                # Add the Markdown content, cleaned up
                if steckbrief.markdown_content:
                    # Strip Markdown formatting and collapse whitespace
                    clean_markdown = steckbrief.markdown_content
                    clean_markdown = clean_markdown.replace('#', '')
                    clean_markdown = clean_markdown.replace('**', '')
                    clean_markdown = clean_markdown.replace('*', '')
                    clean_markdown = clean_markdown.replace('`', '')
                    clean_markdown = ' '.join(clean_markdown.split())  # Whitespace normalisieren
                    fulltext_parts.append(clean_markdown)
                
                # Add the entity variants, so a search for an abbreviation finds the entry
                fulltext_parts.extend(entity_variants)
                
                # Assemble the full text, deduplicated
                fulltext = ' '.join(set(fulltext_parts))
                # Cap the length, to keep the JSON index small enough to download
                if len(fulltext) > 5000:
                    fulltext = fulltext[:5000]

                if title:
                    index.append({
                        'id': str(steckbrief.source_id),
                        'title': title,
                        'description': description,
                        'institution': institution if institution and institution not in ['Nicht angegeben', '-', ''] else '',
                        'category': steckbrief.source.category.display_name,
                        'category_id': steckbrief.source.category.internal_name,
                        'url': f"{self.url_prefix}/details/{steckbrief.source_id}.html",
                        # Full text, for the extended search
                        'fulltext': fulltext,
                        # Entity variants kept separate, so exact hits can be ranked higher
                        'entity_variants': entity_variants
                    })
            except Exception as e:
                logger.warning("Failed to process steckbrief for search index", steckbrief_id=steckbrief.id, error=str(e))

        output_file = self.output_dir / "assets" / "data" / "search-index.json"
        try:
            self._safe_write_file(output_file, json.dumps(index, ensure_ascii=False, indent=2))
            logger.info("Search index generated", items=len(index))
        except Exception as e:
            logger.error("Failed to write search index", error=str(e))
            raise
        
        # Generate the entity index used for autocomplete
        await self._generate_entity_index()

    async def _generate_entity_index(self):
        """
        Generate the entity index (JSON) used for search autocomplete.

        Holds every entity with its variants, so that a partial input can be
        completed to a canonical name.
        """
        from sqlalchemy import select
        from app.models import Entity, EntityVariant
        
        try:
            # Load every entity
            entity_result = await self.session.execute(
                select(Entity)
            )
            entities = entity_result.scalars().all()
            
            entity_index = []
            
            for entity in entities:
                # Load the variants
                variant_result = await self.session.execute(
                    select(EntityVariant.variant_name)
                    .where(EntityVariant.entity_id == entity.id)
                )
                variants = [v[0] for v in variant_result.fetchall()]
                
                # Entity-Typ bestimmen
                entity_type = entity.entity_type or 'institution'
                
                entity_index.append({
                    'id': entity.id,
                    'name': entity.canonical_name,
                    'type': entity_type,
                    'variants': variants,
                    # Every search term belonging to this entity
                    'search_terms': [entity.canonical_name] + variants
                })
            
            # Group by type, for a clearer presentation
            institutions = [e for e in entity_index if e['type'] == 'institution']
            other = [e for e in entity_index if e['type'] != 'institution']
            
            # Output
            output = {
                'institutions': sorted(institutions, key=lambda x: x['name']),
                'other': sorted(other, key=lambda x: x['name']),
                'all': entity_index
            }
            
            output_file = self.output_dir / "assets" / "data" / "entities.json"
            self._safe_write_file(output_file, json.dumps(output, ensure_ascii=False, indent=2))
            logger.info("Entity index generated", count=len(entity_index))
            
        except Exception as e:
            logger.warning("Failed to generate entity index", error=str(e))

    async def _generate_sitemap(
        self,
        categories: List[Category],
        steckbriefe: List[Steckbrief]
    ):
        """Generate sitemap.xml"""

        urls = []

        # Homepage
        urls.append({
            'loc': f"{self.base_url}/",
            'lastmod': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'changefreq': 'daily',
            'priority': '1.0'
        })

        # Category pages
        for category in categories:
            urls.append({
                'loc': f"{self.base_url}/{category.internal_name}/",
                'lastmod': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
                'changefreq': 'daily',
                'priority': '0.8'
            })

        # Detail-Seiten
        for steckbrief in steckbriefe:
            urls.append({
                'loc': f"{self.base_url}/details/{steckbrief.source_id}.html",
                'lastmod': steckbrief.generated_at.strftime('%Y-%m-%d'),
                'changefreq': 'weekly',
                'priority': '0.6'
            })

        # Search page
        urls.append({
            'loc': f"{self.base_url}/suche.html",
            'lastmod': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'changefreq': 'weekly',
            'priority': '0.7'
        })

        # XML generieren
        sitemap_xml = ['<?xml version="1.0" encoding="UTF-8"?>']
        sitemap_xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

        for url in urls:
            sitemap_xml.append('  <url>')
            sitemap_xml.append(f'    <loc>{url["loc"]}</loc>')
            sitemap_xml.append(f'    <lastmod>{url["lastmod"]}</lastmod>')
            sitemap_xml.append(f'    <changefreq>{url["changefreq"]}</changefreq>')
            sitemap_xml.append(f'    <priority>{url["priority"]}</priority>')
            sitemap_xml.append('  </url>')

        sitemap_xml.append('</urlset>')

        output_file = self.output_dir / "sitemap.xml"
        self._safe_write_file(output_file, '\n'.join(sitemap_xml))

        logger.info("Sitemap generated", urls=len(urls))

    async def _generate_static_pages(self):
        """Generate the standalone pages: imprint and API documentation"""

        # Impressum
        impressum_html = self._safe_render_template(
            'impressum.html',
            base_url=self.base_url
        )
        self._safe_write_file(self.output_dir / "impressum.html", impressum_html)

        # API-Dokumentation
        api_html = self._safe_render_template(
            'api.html',
            base_url=self.base_url
        )
        self._safe_write_file(self.output_dir / "api.html", api_html)

        logger.info("Static pages generated")

    async def generate_english_site(self) -> Dict[str, int]:
        """
        Generate the English version of the site, from the translated profiles
        and the English UI strings.

        Returns:
            Dict of statistics
        """
        from app.models import SteckbriefTranslation
        from sqlalchemy import select
        import yaml
        
        logger.info("Starting English site generation")
        
        stats = {
            'pages_generated': 0,
            'categories': 0,
            'steckbriefe': 0,
            'skipped': 0,
            'errors': 0
        }
        
        # Output directory of the English version
        en_output_dir = self.output_dir / "en"
        en_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load the i18n strings
        i18n = self._load_i18n('en')
        
        try:
            # Assets kopieren (CSS, JS, Bilder)
            assets_src = self.template_dir / "assets"
            assets_dst = en_output_dir / "assets"
            if assets_src.exists():
                if assets_dst.exists():
                    shutil.rmtree(assets_dst)
                shutil.copytree(assets_src, assets_dst)
            
            # Load the data
            categories = await self.category_repo.get_active()
            all_steckbriefe = await self.steckbrief_repo.get_published()
            
            # Load the translations
            result = await self.session.execute(
                select(SteckbriefTranslation).where(
                    SteckbriefTranslation.language == 'en'
                )
            )
            translations = {t.steckbrief_id: t for t in result.scalars().all()}
            
            logger.info(
                "english_data_loaded",
                categories_count=len(categories),
                steckbriefe_count=len(all_steckbriefe),
                translations_count=len(translations)
            )
            
            # Use only profiles that have a translation
            translated_steckbriefe = []
            for steckbrief in all_steckbriefe:
                if steckbrief.id in translations:
                    # Attach the translation to the profile object, for this run only
                    steckbrief._en_translation = translations[steckbrief.id]
                    translated_steckbriefe.append(steckbrief)
                else:
                    stats['skipped'] += 1
            
            if not translated_steckbriefe:
                logger.warning("No translated steckbriefe found, skipping English site generation")
                return stats
            
            # Group by category
            steckbriefe_by_category = {}
            for steckbrief in translated_steckbriefe:
                cat_id = steckbrief.source.category_id
                if cat_id not in steckbriefe_by_category:
                    steckbriefe_by_category[cat_id] = []
                steckbriefe_by_category[cat_id].append(steckbrief)
            
            # Homepage generieren
            try:
                await self._generate_english_homepage(
                    en_output_dir, categories, translated_steckbriefe, i18n
                )
                stats['pages_generated'] += 1
            except Exception as e:
                logger.error("Failed to generate English homepage", error=str(e), exc_info=True)
                stats['errors'] += 1
            
            # Generate the category pages
            for category in categories:
                try:
                    steckbriefe = steckbriefe_by_category.get(category.id, [])
                    if steckbriefe:  # Only where translated profiles exist
                        await self._generate_english_category_page(
                            en_output_dir, category, steckbriefe, i18n
                        )
                        stats['categories'] += 1
                        stats['pages_generated'] += 1
                except Exception as e:
                    logger.error(
                        "Failed to generate English category page",
                        category=category.internal_name,
                        error=str(e),
                        exc_info=True
                    )
                    stats['errors'] += 1
            
            # Detail-Seiten generieren
            for steckbrief in translated_steckbriefe:
                try:
                    await self._generate_english_detail_page(
                        en_output_dir, steckbrief, i18n
                    )
                    stats['steckbriefe'] += 1
                    stats['pages_generated'] += 1
                except Exception as e:
                    logger.error(
                        "Failed to generate English detail page",
                        steckbrief_id=steckbrief.id,
                        error=str(e),
                        exc_info=True
                    )
                    stats['errors'] += 1
            
            # Generate the search page
            try:
                await self._generate_english_search_page(
                    en_output_dir, categories, translated_steckbriefe, i18n
                )
                stats['pages_generated'] += 1
                
                # Copy the entity index to the English version: entity names such as
                # university names are not translated, so the index is identical
                de_entity_index = self.output_dir / "assets" / "data" / "entities.json"
                en_entity_index = en_output_dir / "assets" / "data" / "entities.json"
                if de_entity_index.exists():
                    shutil.copy2(de_entity_index, en_entity_index)
                    logger.debug("Entity index copied to English site")
                    
            except Exception as e:
                logger.error("Failed to generate English search page", error=str(e))
                stats['errors'] += 1
            
            # Generate the API page
            try:
                api_html = self._safe_render_template(
                    'api.html',
                    url_prefix=f"{self.url_prefix}/en",
                    i18n=i18n,
                    language='en'
                )
                self._safe_write_file(en_output_dir / "api.html", api_html)
                stats['pages_generated'] += 1
            except Exception as e:
                logger.error("Failed to generate English API page", error=str(e))
                stats['errors'] += 1
            
            # Generate the imprint page
            try:
                imprint_html = self._safe_render_template(
                    'impressum.html',
                    url_prefix=f"{self.url_prefix}/en",
                    i18n=i18n,
                    language='en'
                )
                self._safe_write_file(en_output_dir / "imprint.html", imprint_html)
                stats['pages_generated'] += 1
            except Exception as e:
                logger.error("Failed to generate English imprint page", error=str(e))
                stats['errors'] += 1
            
            logger.info(
                "english_site_generated",
                pages=stats['pages_generated'],
                steckbriefe=stats['steckbriefe'],
                skipped=stats['skipped'],
                errors=stats['errors']
            )
            
            return stats
            
        except Exception as e:
            logger.error("English site generation failed", error=str(e), exc_info=True)
            stats['errors'] += 1
            return stats
    
    def _load_i18n(self, language: str) -> dict:
        """Load the i18n strings for one language"""
        import yaml
        
        i18n_path = Path(__file__).parent.parent / "config" / "i18n" / f"{language}.yaml"
        if i18n_path.exists():
            with open(i18n_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return {}
    
    async def _generate_english_homepage(
        self, 
        output_dir: Path, 
        categories: list, 
        steckbriefe: list,
        i18n: dict
    ):
        """Generate the English homepage"""
        # Compute the statistics, as the German version does
        stats = {}
        for category in categories:
            count = sum(1 for s in steckbriefe if s.source.category_id == category.id)
            stats[category.internal_name] = count
        
        total_count = len(steckbriefe)
        
        # The six most recent profiles, as the German version does
        latest = sorted(
            steckbriefe,
            key=lambda s: s.generated_at or datetime.min,
            reverse=True
        )[:6]
        
        # English version: load the translation if there is one and wrap it in an
        # object that presents the same attributes as a profile, so the shared
        class SteckbriefWrapper:
            """Presents the English content behind the same attributes as a profile"""
            def __init__(self, original, translation_content):
                self.id = original.id
                self.source_id = original.source_id
                self.source = original.source
                self.generated_at = original.generated_at
                self.markdown_content = translation_content or original.markdown_content
        
        latest_wrapped = []
        for s in latest:
            translation = getattr(s, '_en_translation', None)
            md_content = translation.markdown_content if translation else s.markdown_content
            latest_wrapped.append(SteckbriefWrapper(s, md_content))
        
        html = self._safe_render_template(
            'homepage.html',
            base_url="/en",
            url_prefix=f"{self.url_prefix}/en",
            categories=categories,
            stats=stats,
            total_count=total_count,
            latest_steckbriefe=latest_wrapped,  # Korrigiert: latest_steckbriefe statt recent_steckbriefe
            i18n=i18n,
            language='en'
        )
        
        self._safe_write_file(output_dir / "index.html", html)
    
    async def _generate_english_category_page(
        self,
        output_dir: Path,
        category,
        steckbriefe: list,
        i18n: dict
    ):
        """Generate an English category page"""
        # Create the directory
        cat_dir = output_dir / category.internal_name
        cat_dir.mkdir(parents=True, exist_ok=True)
        
        # Profile data carrying the English content
        steckbriefe_data = []
        institutions = set()
        
        for s in steckbriefe:
            translation = getattr(s, '_en_translation', None)
            md_content = translation.markdown_content if translation else s.markdown_content
            
            institution = self._extract_institution(md_content)
            if institution and institution not in ['Nicht angegeben', '-', 'Not specified']:
                institutions.add(institution)
            
            steckbriefe_data.append({
                'id': s.id,
                'source_id': str(s.source_id),
                'title': self._extract_title(md_content),
                'institution': institution,
                'description': self._extract_description(md_content),
                'generated_at': s.generated_at,
                'url': f"../details/{s.source_id}.html",
                'markdown_content': md_content  # Needed by the template filters
            })
        
        # Sort by date
        steckbriefe_data.sort(
            key=lambda x: x['generated_at'] or datetime.min,
            reverse=True
        )
        
        html = self._safe_render_template(
            'category.html',
            base_url="/en",
            url_prefix=f"{self.url_prefix}/en",
            category={
                'internal_name': category.internal_name,
                'display_name': category.display_name_en or category.display_name
            },
            steckbriefe=steckbriefe_data,
            institutions=sorted(institutions),  # Institutions, for the filter
            i18n=i18n,
            language='en'
        )
        
        self._safe_write_file(cat_dir / "index.html", html)
    
    async def _generate_english_detail_page(
        self,
        output_dir: Path,
        steckbrief,
        i18n: dict
    ):
        """Generate an English detail page"""
        details_dir = output_dir / "details"
        details_dir.mkdir(parents=True, exist_ok=True)
        
        translation = getattr(steckbrief, '_en_translation', None)
        md_content = translation.markdown_content if translation else steckbrief.markdown_content
        
        # Take the title and institution from the Markdown
        title = self._extract_title(md_content)
        institution = self._extract_institution(md_content)
        
        # Build the extractions dict the template expects
        extractions = {
            'project_name': {'value': title},
            'service_name': {'value': title},
            'title': {'value': title},
            'institution': {'value': institution}
        }
        
        # Markdown zu HTML
        html_content = markdown(
            md_content or "",
            extras=['tables', 'fenced-code-blocks', 'break-on-newline']
        )
        
        # Source object, for the template
        source = steckbrief.source
        category = source.category
        
        html = self._safe_render_template(
            'detail.html',
            base_url="/en",
            url_prefix=f"{self.url_prefix}/en",
            steckbrief={
                'id': steckbrief.id,
                'source_id': str(steckbrief.source_id),
                'markdown_content': md_content,
                'html_content': html_content,
                'published_at': steckbrief.published_at,
                'generated_at': steckbrief.generated_at
            },
            source=source,
            category=category,
            extractions=extractions,
            i18n=i18n,
            language='en'
        )
        
        # File name uses source_id, matching the German version
        self._safe_write_file(details_dir / f"{steckbrief.source_id}.html", html)
    
    async def _generate_english_search_page(
        self,
        output_dir: Path,
        categories: list,
        steckbriefe: list,
        i18n: dict
    ):
        """Generate the English search page and its search index"""
        # Search index for the English version
        search_index = []
        institutions = set()
        
        for steckbrief in steckbriefe:
            translation = getattr(steckbrief, '_en_translation', None)
            md_content = translation.markdown_content if translation else steckbrief.markdown_content
            
            title = self._extract_title(md_content)
            institution = self._extract_institution(md_content)
            description = self._extract_description(md_content)
            
            if institution:
                institutions.add(institution)
            
            category = steckbrief.source.category
            
            # Full text taken from the English Markdown
            fulltext = ""
            if md_content:
                clean_markdown = md_content
                clean_markdown = clean_markdown.replace('#', '')
                clean_markdown = clean_markdown.replace('**', '')
                clean_markdown = clean_markdown.replace('*', '')
                clean_markdown = clean_markdown.replace('`', '')
                fulltext = ' '.join(clean_markdown.split())
                if len(fulltext) > 5000:
                    fulltext = fulltext[:5000]
            
            search_index.append({
                'id': str(steckbrief.source_id),  # File name uses source_id, matching the German version
                'title': title,
                'institution': institution,
                'description': description,
                'category': category.display_name_en or category.display_name,
                'category_id': category.internal_name,
                'url': f"details/{steckbrief.source_id}.html",  # File name uses source_id, matching the German version
                'date': steckbrief.generated_at.strftime('%Y-%m-%d') if steckbrief.generated_at else '',
                'fulltext': fulltext,
                'entity_variants': []  # No German variants in the English version
            })
        
        # Write the search index into assets/data, as the German version does
        assets_data_dir = output_dir / "assets" / "data"
        assets_data_dir.mkdir(parents=True, exist_ok=True)
        index_path = assets_data_dir / "search-index.json"
        self._safe_write_file(index_path, json.dumps(search_index, ensure_ascii=False, indent=2))
        
        # Categories, for the filter
        categories_data = []
        for cat in categories:
            count = len([s for s in steckbriefe if s.source.category_id == cat.id])
            if count > 0:
                categories_data.append({
                    'internal_name': cat.internal_name,
                    'display_name': cat.display_name_en or cat.display_name,
                    'count': count
                })
        
        html = self._safe_render_template(
            'search.html',
            base_url="/en",
            url_prefix=f"{self.url_prefix}/en",
            categories=categories_data,
            institutions=sorted(institutions),
            total_count=len(steckbriefe),
            i18n=i18n,
            language='en'
        )
        
        self._safe_write_file(output_dir / "search.html", html)

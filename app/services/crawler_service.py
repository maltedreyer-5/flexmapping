# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Crawler: fetches pages and converts them to Markdown.

One main page is crawled together with a configurable number of linked
subpages on the same domain. Subpages are chosen by a rule-based score rather
than by an LLM call, because the choice has to be cheap: it happens once per
link on every page.

The instance is shared between workers, so the rate limiter and the robots.txt
cache are both guarded by locks.
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Set, Dict
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import structlog
from bs4 import BeautifulSoup
from markdownify import markdownify

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@dataclass
class PageContent:
    """Content of a single page"""
    url: str
    html: str
    status_code: int
    title: str = ""


@dataclass
class CrawlResult:
    """Result of one crawl run"""
    url: str
    markdown: str
    size: int
    pages_crawled: int
    timestamp: datetime
    success: bool = True
    error: Optional[str] = None


class CrawlerError(Exception):
    """Raised for crawler errors"""
    pass


class RateLimiter:
    """Thread-safe Rate Limiter pro Domain"""

    def __init__(self):
        self.last_request: dict[str, float] = {}
        self._lock = asyncio.Lock()  # Lock: several workers share one crawler instance

    async def wait(self, domain: str, delay: float):
        """Wait if the rate limit requires it. Safe to call from several workers."""
        wait_time = 0  # Initialised before the lock block, so the value survives leaving it
        
        async with self._lock:
            now = time.time()
            if domain in self.last_request:
                elapsed = now - self.last_request[domain]
                if elapsed < delay:
                    wait_time = delay - elapsed
                    logger.debug("rate_limit_wait", domain=domain, wait_time=wait_time)
            # No else needed, wait_time is already 0

            self.last_request[domain] = time.time()

        # Wait outside of lock
        if wait_time > 0:
            await asyncio.sleep(wait_time)


class CrawlerService:
    """Crawls pages and produces consolidated Markdown"""

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_markdown_size: Optional[int] = None,
        user_agent: Optional[str] = None,
        multi_page_enabled: Optional[bool] = None,
        max_pages: Optional[int] = None,
        verify_ssl: Optional[bool] = None,
        respect_robots: Optional[bool] = None
    ):
        self.timeout = timeout or settings.crawler_timeout
        self.max_markdown_size = max_markdown_size or settings.crawler_max_markdown_size
        self.user_agent = user_agent or settings.crawler_user_agent
        self.multi_page_enabled = multi_page_enabled if multi_page_enabled is not None else settings.crawler_multi_page_enabled
        self.max_pages = max_pages or settings.crawler_max_pages
        self.verify_ssl = verify_ssl if verify_ssl is not None else getattr(settings, 'crawler_verify_ssl', True)
        self.respect_robots = respect_robots if respect_robots is not None else getattr(settings, 'crawler_respect_robots', True)
        self.rate_limiter = RateLimiter()

        # Cache of robots.txt parsers, guarded by a lock
        self._robots_cache: Dict[str, RobotFileParser] = {}
        self._robots_lock = asyncio.Lock()

        logger.info(
            "crawler_service_initialized",
            timeout=self.timeout,
            max_markdown_size=self.max_markdown_size,
            multi_page_enabled=self.multi_page_enabled,
            max_pages=self.max_pages,
            verify_ssl=self.verify_ssl,
            respect_robots=self.respect_robots
        )

    def _validate_url(self, url: str) -> bool:
        """
        Validate a URL.

        Args:
            url: the URL to validate

        Returns:
            True if valid, False otherwise
        """
        if not url or not url.strip():
            return False

        try:
            parsed = urlparse(url)
            # Must carry both a scheme and a netloc
            if not parsed.scheme or not parsed.netloc:
                logger.warning("url_missing_scheme_or_netloc", url=url[:100], scheme=parsed.scheme, netloc=parsed.netloc)
                return False
            # http and https only
            if parsed.scheme not in ['http', 'https']:
                logger.warning("url_invalid_scheme", url=url[:100], scheme=parsed.scheme)
                return False
            return True
        except Exception as e:
            logger.warning("url_validation_failed", url=url[:100], error=str(e))
            return False
    
    def _normalize_url(self, url: str) -> Optional[str]:
        """
        Normalize URL - add https:// if missing, strip whitespace
        
        Args:
            url: URL to normalize
            
        Returns:
            Normalized URL or None if invalid
        """
        if not url:
            return None
        
        # CRITICAL: Strip ALL whitespace (including tabs, newlines)
        url = url.strip()
        
        if not url:
            return None
        
        # Add https:// if no protocol
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'https://' + url
        
        # Validate after normalization
        if self._validate_url(url):
            return url
        return None

    async def crawl_url(
        self,
        url: str,
        rate_limit: Optional[float] = None,
        additional_urls: Optional[List[str]] = None
    ) -> CrawlResult:
        """
        Crawl a URL together with its linked subpages.

        Args:
            url: the main URL
            rate_limit: requests per second (default: from configuration)
            additional_urls: optional extra URLs, added by hand

        Returns:
            CrawlResult carrying the consolidated Markdown
        """
        # Normalise and validate the URL
        normalized_url = self._normalize_url(url)
        if not normalized_url:
            logger.error("invalid_url", url=url[:100] if url else "None")
            return CrawlResult(
                url=url or "invalid",
                markdown="",
                size=0,
                pages_crawled=0,
                timestamp=datetime.now(timezone.utc),
                success=False,
                error=f"Invalid URL: '{url}' - URL must start with http:// or https://"
            )
        
        url = normalized_url

        rate_limit = rate_limit or settings.crawler_default_rate_limit

        try:
            # 1. Check robots.txt, but only when respect_robots is on
            if self.respect_robots and not await self.can_crawl(url):
                return CrawlResult(
                    url=url,
                    markdown="",
                    size=0,
                    pages_crawled=0,
                    timestamp=datetime.now(timezone.utc),
                    success=False,
                    error="Crawling forbidden by robots.txt. Tipp: CRAWLER_RESPECT_ROBOTS=false in .env setzen"
                )

            # 2. Hauptseite crawlen
            domain = self._get_domain(url)
            await self.rate_limiter.wait(domain, 1.0 / rate_limit)

            main_page = await self._fetch_page(url)
            pages = [main_page]

            # 3. Multi-Page: Unterseiten crawlen
            if self.multi_page_enabled:
                if additional_urls:
                    # Drop URLs that failed validation
                    valid_additional = [
                        u for u in additional_urls
                        if self._validate_url(u)
                    ]
                    subpage_urls = valid_additional[:self.max_pages - 1]
                    logger.info(
                        "crawling_manual_subpages",
                        url=url,
                        num_subpages=len(subpage_urls)
                    )
                else:
                    # Extract and prioritise links automatically
                    links = self._extract_links(main_page, url)
                    prioritized = self._prioritize_links(links, url)
                    subpage_urls = prioritized[:self.max_pages - 1]

                    logger.info(
                        "crawling_auto_subpages",
                        url=url,
                        num_links=len(links),
                        num_selected=len(subpage_urls)
                    )

                # Subpages crawlen
                for subpage_url in subpage_urls:
                    try:
                        await self.rate_limiter.wait(domain, 1.0 / rate_limit)
                        subpage = await self._fetch_page(subpage_url)
                        pages.append(subpage)

                    except Exception as e:
                        logger.warning(
                            "subpage_crawl_failed",
                            url=subpage_url,
                            error=str(e),
                            error_type=type(e).__name__
                        )

            # Guard against an empty page list
            if not pages:
                raise CrawlerError("No pages were crawled successfully")

            # 4. Konsolidiertes Markdown generieren
            markdown = self._generate_consolidated_markdown(url, pages)

            logger.info(
                "crawl_completed",
                url=url,
                pages_crawled=len(pages),
                markdown_size=len(markdown)
            )

            return CrawlResult(
                url=url,
                markdown=markdown,
                size=len(markdown),
                pages_crawled=len(pages),
                timestamp=datetime.now(timezone.utc),
                success=True
            )

        except httpx.HTTPError as e:
            logger.error(
                "http_error",
                url=url,
                error=str(e),
                error_type=type(e).__name__
            )
            return CrawlResult(
                url=url,
                markdown="",
                size=0,
                pages_crawled=0,
                timestamp=datetime.now(timezone.utc),
                success=False,
                error=f"HTTP Error: {str(e)}"
            )
        except Exception as e:
            logger.error(
                "crawl_failed",
                url=url,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return CrawlResult(
                url=url,
                markdown="",
                size=0,
                pages_crawled=0,
                timestamp=datetime.now(timezone.utc),
                success=False,
                error=str(e)
            )

    async def can_crawl(self, url: str) -> bool:
        """
        Check whether robots.txt permits crawling this URL.

        robots.txt is fetched with httpx rather than urllib, because urllib
        has no way to honour the verify_ssl setting, and institutions running
        self-signed certificates would otherwise fail here before the crawl
        itself gets a chance.
        """
        if not self._validate_url(url):
            return False

        try:
            # Make sure the URL carries a scheme
            if not url.startswith('http://') and not url.startswith('https://'):
                url = 'https://' + url
            
            base_url = self._get_base_url(url)
            if not base_url or not base_url.startswith('http'):
                logger.warning("invalid_base_url", url=url, base_url=base_url)
                return True  # Allow crawling when the check itself fails
            
            robots_url = f"{base_url}/robots.txt"

            # Cache access, guarded by the lock
            async with self._robots_lock:
                # Cache check
                if robots_url in self._robots_cache:
                    rp = self._robots_cache[robots_url]
                else:
                    # Build a new parser
                    rp = RobotFileParser()
                    # Do not call set_url here: it would fetch robots.txt through urllib,
        # bypassing the verify_ssl setting below
                    
                    # Fetch robots.txt with httpx, so that verify_ssl is honoured
                    try:
                        async with httpx.AsyncClient(
                            timeout=10,
                            follow_redirects=True,
                            verify=self.verify_ssl
                        ) as client:
                            response = await client.get(
                                robots_url,
                                headers={"User-Agent": self.user_agent}
                            )
                            
                            if response.status_code == 200:
                                # Parse the robots.txt content
                                lines = response.text.splitlines()
                                rp.parse(lines)
                                
                                logger.debug(
                                    "robots_txt_loaded",
                                    url=robots_url
                                )
                            else:
                                # 404 or another status: allow
                                logger.debug(
                                    "robots_txt_not_found",
                                    url=robots_url,
                                    status_code=response.status_code
                                )
                                return True

                        # Store it in the cache
                        self._robots_cache[robots_url] = rp

                    except Exception as e:
                        # TLS or other transport failure while fetching
                        logger.warning(
                            "robots_txt_load_failed",
                            url=robots_url,
                            error=str(e)
                        )
                        # On failure, allow. Refusing to crawl because robots.txt was
                # unreachable would stall every source on a flaky host.
                        return True

            # Evaluate the rules outside the lock
            # can_fetch is wrapped: a malformed robots.txt makes the parser raise
            try:
                allowed = rp.can_fetch(self.user_agent, url)
            except Exception as e:
                logger.warning(
                    "robots_can_fetch_error",
                    url=url,
                    error=str(e)
                )
                return True  # Allow on failure

            logger.debug(
                "robots_txt_check",
                url=url,
                allowed=allowed
            )

            return allowed

        except Exception as e:
            logger.warning(
                "robots_txt_check_failed",
                url=url,
                error=str(e),
                exc_info=True
            )
            # Allow on failure, deliberately on the permissive side
            return True

    async def _fetch_page(self, url: str) -> PageContent:
        """Fetch a single page"""
        # CRITICAL: Validate and clean URL before httpx request
        if not url:
            raise CrawlerError("Empty URL provided to _fetch_page")
        
        url = url.strip()
        
        if not url.startswith('http://') and not url.startswith('https://'):
            logger.error(
                "fetch_page_invalid_url",
                url=repr(url)[:200],
                error="URL missing protocol"
            )
            raise CrawlerError(f"Invalid URL (missing protocol): {url[:100]}")
        
        logger.debug(
            "fetch_page_starting",
            url=url[:200],
            verify_ssl=self.verify_ssl
        )
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                verify=self.verify_ssl
            ) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": self.user_agent}
                )
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')
                title_tag = soup.find('title')
                title = title_tag.get_text().strip() if title_tag else ""

                return PageContent(
                    url=url,
                    html=response.text,
                    status_code=response.status_code,
                    title=title
                )
        except httpx.HTTPStatusError as e:
            logger.error(
                "http_status_error",
                url=url,
                status_code=e.response.status_code,
                error=str(e)
            )
            raise
        except httpx.TimeoutException:
            logger.error("request_timeout", url=url, timeout=self.timeout)
            raise
        except httpx.ConnectError as e:
            # TLS problems usually surface as ConnectError
            error_msg = str(e)
            if 'SSL' in error_msg or 'CERTIFICATE' in error_msg or 'certificate' in error_msg:
                logger.error(
                    "ssl_certificate_error",
                    url=url,
                    error=error_msg,
                    hint="Set CRAWLER_VERIFY_SSL=false to skip SSL verification"
                )
                raise CrawlerError(f"SSL-Zertifikatsfehler: {error_msg}. Tipp: CRAWLER_VERIFY_SSL=false in .env setzen")
            logger.error("connection_error", url=url, error=error_msg)
            raise
        except Exception as e:
            error_msg = str(e)
            # Catch the remaining TLS failures too
            if 'SSL' in error_msg or 'CERTIFICATE' in error_msg or 'certificate' in error_msg:
                logger.error(
                    "ssl_certificate_error",
                    url=url,
                    error=error_msg
                )
                raise CrawlerError(f"SSL-Zertifikatsfehler: {error_msg}. Tipp: CRAWLER_VERIFY_SSL=false in .env setzen")
            logger.error(
                "fetch_page_failed",
                url=url,
                error=error_msg,
                error_type=type(e).__name__
            )
            raise

    def _extract_links(self, page: PageContent, base_url: str) -> List[str]:
        """Extract every link from a page"""
        try:
            soup = BeautifulSoup(page.html, 'html.parser')
            links = []
            base_domain = urlparse(base_url).netloc

            for a_tag in soup.find_all('a', href=True):
                try:
                    href = a_tag['href']

                    # Skip leere hrefs
                    if not href or not href.strip():
                        continue

                    absolute_url = urljoin(base_url, href)

                    # Validiere URL
                    if not self._validate_url(absolute_url):
                        continue

                    # Same-domain links only
                    if urlparse(absolute_url).netloc == base_domain:
                        # No fragments, no duplicates
                        clean_url = absolute_url.split('#')[0] if '#' in absolute_url else absolute_url

                        if clean_url and clean_url not in links and clean_url != base_url:
                            links.append(clean_url)
                except Exception as e:
                    logger.debug(
                        "link_extraction_error",
                        href=str(a_tag.get('href', ''))[:100],
                        error=str(e)
                    )
                    continue

            return links
        except Exception as e:
            logger.error(
                "extract_links_failed",
                error=str(e),
                exc_info=True
            )
            return []

    def _prioritize_links(self, links: List[str], base_url: str) -> List[str]:
        """Rule-based link prioritisation, without an LLM call"""
        if not links:
            return []

        # Keyword-Kategorien
        # Matched against lowercased URL paths, so these must be written the
        # way they appear in a URL. Umlauts are the trap: a German site links
        # to /ueber-uns rather than the umlaut form, so the plain-ASCII spellings
        # matches. The percent-encoded form is checked too, because some sites
        # do emit it.
        high_priority = [
            'team', 'kontakt', 'contact', 'about', 'ueber', '%c3%bcber',
            'menschen', 'people', 'staff', 'mitarbeiter',
        ]
        medium_priority = ['projekt', 'project', 'forschung', 'research']
        low_priority = [
            'publikation', 'publication', 'veroeffentlichung', 'paper',
            'service', 'angebot', 'offer',
        ]
        # Pages that carry no content worth extracting. Both languages are
        # listed: an English-language university site has /imprint and
        # /privacy where a German one has /impressum and /datenschutz.
        exclude = [
            'impressum', 'imprint', 'datenschutz', 'privacy', 'cookie',
            'login', 'agb', 'terms', 'legal', 'barrierefreiheit',
            'accessibility', 'sitemap',
        ]

        scored_links = []
        base_domain = self._get_domain(base_url)

        for link in links:
            try:
                path = link.lower()
                score = 0

                # High-Priority-Keywords
                if any(kw in path for kw in high_priority):
                    score += 10

                # Medium-Priority
                elif any(kw in path for kw in medium_priority):
                    score += 8

                # Low-Priority
                elif any(kw in path for kw in low_priority):
                    score += 6

                # Default score for everything else
                else:
                    score += 3

                # Penalties
                if any(kw in path for kw in exclude):
                    score -= 5

                # Exclude external links
                if self._get_domain(link) != base_domain:
                    score -= 10

                # Keep only links with a positive score
                if score > 0:
                    scored_links.append((score, link))
            except Exception as e:
                logger.debug("link_scoring_error", link=link[:100], error=str(e))
                continue

        # Sort by score, highest first
        scored_links.sort(reverse=True, key=lambda x: x[0])

        return [link for score, link in scored_links]

    def _sanitize_for_postgres(self, text: str) -> str:
        """
        Remove NULL bytes and other characters PostgreSQL rejects.

        PostgreSQL cannot store NULL bytes (0x00) in TEXT or VARCHAR columns,
        and pages in the wild do contain them. Without this the whole crawl
        result is lost at insert time.
        """
        if not text:
            return text
        
        # Entferne NULL-Bytes
        sanitized = text.replace('\x00', '')
        
        # Strip the remaining control characters, keeping newline, tab and CR
        # ASCII 0-8, 11-12 and 14-31 are control characters
        import re
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', sanitized)
        
        # Make sure the string is valid UTF-8
        try:
            # Encode and decode to drop invalid UTF-8 sequences
            sanitized = sanitized.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
        except Exception as e:
            # Not fatal: this only affects one candidate link, so the crawl
            # continues. Logged at debug level because malformed links on
            # foreign pages are common and would otherwise flood the log.
            logger.debug("Failed to evaluate candidate link", error=str(e))
        
        return sanitized

    def _generate_consolidated_markdown(
        self,
        primary_url: str,
        pages: List[PageContent]
    ) -> str:
        """Build consolidated Markdown from several pages"""
        if not pages:
            logger.error("no_pages_for_markdown_generation")
            return "# ERROR: No pages were crawled"

        # Metadata
        metadata = f"""# [METADATA]
Source-UUID: {primary_url}
Primary-URL: {primary_url}
Crawled-Pages: {len(pages)}
Crawl-Timestamp: {datetime.now(timezone.utc).isoformat()}Z
Total-Size: {sum(len(p.html) for p in pages)}

"""

        sections = []

        # Hauptseite
        main_page = pages[0]
        main_content = self._extract_main_content(main_page.html)
        main_markdown = markdownify(str(main_content), heading_style="ATX")

        sections.append(f"""# [MAIN_PAGE]
## URL: {main_page.url}
## Title: {main_page.title}
## Page-Type: PRIMARY

{main_markdown}
""")

        # Unterseiten
        for i, page in enumerate(pages[1:], 1):
            try:
                page_type = self._infer_page_type(page.url)
                content = self._extract_main_content(page.html)
                markdown = markdownify(str(content), heading_style="ATX")

                sections.append(f"""---

# [SUBPAGE_{i}: {page_type.upper()}]
## URL: {page.url}
## Title: {page.title}
## Page-Type: {page_type.upper()}

{markdown}
""")
            except Exception as e:
                logger.warning(
                    "subpage_markdown_generation_failed",
                    page_url=page.url,
                    error=str(e)
                )

        # Join the sections
        full_markdown = metadata + "\n".join(sections)

        # Sanitize for PostgreSQL: strip NULL bytes and invalid characters
        full_markdown = self._sanitize_for_postgres(full_markdown)

        # Size limit
        if len(full_markdown) > self.max_markdown_size:
            full_markdown = full_markdown[:self.max_markdown_size] + "\n\n[TRUNCATED]"
            logger.warning(
                "markdown_truncated",
                original_size=len(full_markdown),
                max_size=self.max_markdown_size
            )

        return full_markdown

    def _extract_main_content(self, html: str) -> BeautifulSoup:
        """
        Extract the main content of a page, heuristically.

        Falls back through progressively looser selectors, because university
        sites rarely use the semantic markup the first selector looks for.
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Versuche verschiedene Content-Container zu finden
            content = (
                soup.find('main') or
                soup.find('article') or
                soup.find(id='content') or
                soup.find(class_='content') or
                soup.find('div', class_='main') or
                soup.body
            )

            # Guard against content being None
            if not content:
                logger.warning("no_content_container_found")
                # Fallback: Ganzes Dokument
                content = soup

            # Entferne Navigation, Footer, Sidebar
            for unwanted in content.find_all(['nav', 'footer', 'aside', 'script', 'style']):
                unwanted.decompose()

            return content
        except Exception as e:
            logger.error(
                "content_extraction_failed",
                error=str(e),
                exc_info=True
            )
            # Fallback: Leeres BeautifulSoup
            return BeautifulSoup("<p>Content extraction failed</p>", 'html.parser')

    def _infer_page_type(self, url: str) -> str:
        """Infer the page type from the URL"""
        try:
            path = url.lower()

            if any(kw in path for kw in ['team', 'menschen', 'people', 'staff',
                                         'mitarbeiter', 'about', 'ueber', '%c3%bcber']):
                return 'TEAM'
            elif any(kw in path for kw in ['kontakt', 'contact']):
                return 'CONTACT'
            elif any(kw in path for kw in ['publikation', 'publication',
                                           'veroeffentlichung', 'paper']):
                return 'PUBLICATIONS'
            elif any(kw in path for kw in ['projekt', 'project', 'forschung', 'research']):
                return 'PROJECT'
            elif any(kw in path for kw in ['service', 'angebot', 'offer', 'tool']):
                return 'SERVICE'
            else:
                return 'OTHER'
        except Exception:
            return 'OTHER'

    def _get_domain(self, url: str) -> str:
        """Extract the domain from a URL"""
        try:
            return urlparse(url).netloc
        except Exception:
            return "unknown"

    def _get_base_url(self, url: str) -> str:
        """Extrahiere Base-URL (scheme + netloc)"""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return url
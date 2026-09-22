#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
CLI Script zum Generieren der statischen Website

Verwendung:
    python generate_site.py
    
Optional mit Custom-Konfiguration:
    python generate_site.py --output-dir /var/www/html
"""
import asyncio
import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import structlog
from app.config import get_settings
from app.database import get_db_session
from app.services.static_site_generator import StaticSiteGenerator

logger = structlog.get_logger()


async def generate_site(output_dir: str = None):
    """
    Generiert die komplette statische Website
    
    Args:
        output_dir: Optional custom output directory
    """
    settings = get_settings()
    
    if output_dir:
        settings.public_site_dir = output_dir
    
    logger.info(
        "Starting static site generation",
        output_dir=settings.public_site_dir
    )
    
    try:
        async with get_db_session() as session:
            generator = StaticSiteGenerator(session)
            stats = await generator.generate_full_site()
            
            logger.info("Site generation completed successfully", **stats)
            
            print("\n✓ Static site generated successfully!")
            print(f"  Pages: {stats['pages_generated']}")
            print(f"  Categories: {stats['categories']}")
            print(f"  Steckbriefe: {stats['steckbriefe']}")
            print(f"  Output: {settings.public_site_dir}")
            
            return True
            
    except Exception as e:
        logger.error("Site generation failed", error=str(e), exc_info=True)
        print(f"\n✗ Error: {str(e)}", file=sys.stderr)
        return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Generate the static FlexMapping website"
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        help='Custom output directory (default: from config)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG)
        )
    
    # Run generation
    success = asyncio.run(generate_site(output_dir=args.output_dir))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

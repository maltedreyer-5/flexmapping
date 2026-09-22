# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Category configuration loader.

Reads the category YAML files and synchronises them into the database. The
YAML files are the single source of truth; the database rows are a copy that
the admin interface can edit.
"""
import os
from pathlib import Path
from typing import Optional

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Category, Prompt, CategoryPrompt

logger = structlog.get_logger()

# Default location of the category configuration files
DEFAULT_CONFIG_DIR = Path(__file__).parent / "config" / "categories"


def get_config_dir() -> Path:
    """
    Return the directory holding the category YAML files.

    Precedence: the FLEXMAP_CONFIG_DIR setting, then the legacy
    PROMPTKI_CONFIG_DIR environment variable, then the packaged default.
    The legacy name is still honoured so that an existing .env keeps working;
    it is read directly from the environment because it is not a setting.
    """
    config_dir = get_settings().config_dir or os.environ.get("PROMPTKI_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "categories"
    return DEFAULT_CONFIG_DIR


def load_yaml_file(filepath: Path) -> Optional[dict]:
    """Load a single YAML file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load YAML file", path=str(filepath), error=str(e))
        return None


def load_all_category_configs() -> list[dict]:
    """Load every category configuration from the configuration directory."""
    config_dir = get_config_dir()
    
    if not config_dir.exists():
        logger.warning("Config directory does not exist", path=str(config_dir))
        return []
    
    configs = []
    for yaml_file in config_dir.glob("*.yaml"):
        config = load_yaml_file(yaml_file)
        if config:
            config['_source_file'] = yaml_file.name
            configs.append(config)
            logger.debug("Loaded category config", file=yaml_file.name)
    
    logger.info(f"Loaded {len(configs)} category configurations")
    return configs


def validate_config(config: dict) -> tuple[bool, list[str]]:
    """
    Validate one category configuration.

    Returns: (is_valid, list of errors)
    """
    errors = []
    
    # Check category section
    if 'category' not in config:
        errors.append("Missing 'category' section")
        return False, errors
    
    cat = config['category']
    required_cat_fields = ['internal_name', 'display_name', 'steckbrief_template', 'field_groups', 'active_groups']
    for field in required_cat_fields:
        if field not in cat:
            errors.append(f"Missing required category field: {field}")
    
    # Check prompts section
    if 'prompts' not in config:
        errors.append("Missing 'prompts' section")
        return False, errors
    
    prompts = config['prompts']
    if not isinstance(prompts, list) or len(prompts) == 0:
        errors.append("'prompts' must be a non-empty list")
        return False, errors
    
    # Check each prompt
    required_prompt_fields = ['internal_name', 'display_name', 'field_group']
    prompt_names = set()
    for i, prompt in enumerate(prompts):
        for field in required_prompt_fields:
            if field not in prompt:
                errors.append(f"Prompt {i+1}: Missing required field '{field}'")
        
        # Check for prompt template (either name)
        if 'prompt_template' not in prompt and 'extract_prompt' not in prompt:
            errors.append(f"Prompt {i+1}: Missing 'prompt_template' or 'extract_prompt'")
        
        if 'internal_name' in prompt:
            if prompt['internal_name'] in prompt_names:
                errors.append(f"Duplicate prompt internal_name: {prompt['internal_name']}")
            prompt_names.add(prompt['internal_name'])
    
    # Check field_groups reference existing prompts
    if 'field_groups' in cat:
        for group_name, fields in cat['field_groups'].items():
            for field in fields:
                if field not in prompt_names:
                    errors.append(f"field_groups.{group_name} references undefined prompt: {field}")
    
    return len(errors) == 0, errors


async def export_category_to_yaml(session: AsyncSession, category_id: int) -> Optional[str]:
    """Export a category from the database as a YAML string."""
    # Get category
    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    category = result.scalar_one_or_none()
    if not category:
        return None
    
    # Get associated prompts
    result = await session.execute(
        select(Prompt, CategoryPrompt.display_order)
        .join(CategoryPrompt, Prompt.id == CategoryPrompt.prompt_id)
        .where(CategoryPrompt.category_id == category_id)
        .order_by(CategoryPrompt.display_order)
    )
    prompts_data = result.fetchall()
    
    # Build YAML structure
    yaml_data = {
        'category': {
            'internal_name': category.internal_name,
            'display_name': category.display_name,
            'field_groups': category.field_groups or {},
            'active_groups': category.active_groups or [],
            'steckbrief_template': category.steckbrief_template
        },
        'prompts': []
    }
    
    for prompt, _ in prompts_data:
        yaml_data['prompts'].append({
            'internal_name': prompt.internal_name,
            'display_name': prompt.display_name,
            'field_group': prompt.field_group,
            'output_format': prompt.field_type,  # Map back to YAML name
            'prompt_template': prompt.extract_prompt  # Map back to YAML name
        })
    
    # Convert to YAML string
    return yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False, sort_keys=False)


async def sync_category_from_config(
    session: AsyncSession, 
    config: dict, 
    force_update: bool = False
) -> dict:
    """
    Synchronise one category configuration into the database.

    Args:
        session: database session
        config: parsed YAML configuration
        force_update: if True, overwrite existing entries

    Returns:
        dict of sync statistics
    """
    stats = {
        'category_created': False,
        'category_updated': False,
        'category_skipped': False,
        'prompts_created': 0,
        'prompts_updated': 0,
        'prompts_skipped': 0,
        'mappings_created': 0,
        'mappings_deleted': 0
    }
    
    cat_data = config['category']
    internal_name = cat_data['internal_name']
    
    # 1. Check if category exists
    result = await session.execute(
        select(Category).where(Category.internal_name == internal_name)
    )
    existing_cat = result.scalar_one_or_none()
    
    if existing_cat:
        if force_update:
            # Update existing category
            existing_cat.display_name = cat_data['display_name']
            existing_cat.display_name_en = cat_data.get('display_name_en')
            existing_cat.steckbrief_template = cat_data['steckbrief_template']
            existing_cat.field_groups = cat_data['field_groups']
            existing_cat.active_groups = cat_data['active_groups']
            existing_cat.is_active = True
            category_id = existing_cat.id
            stats['category_updated'] = True
            
            # Delete old mappings when force updating
            delete_result = await session.execute(
                CategoryPrompt.__table__.delete().where(
                    CategoryPrompt.category_id == category_id
                )
            )
            stats['mappings_deleted'] = delete_result.rowcount
            logger.info(f"Updated category: {internal_name}, deleted {stats['mappings_deleted']} old mappings")
        else:
            # Skip existing
            category_id = existing_cat.id
            stats['category_skipped'] = True
            logger.debug(f"Skipped existing category: {internal_name}")
    else:
        # Create new category
        new_cat = Category(
            internal_name=internal_name,
            display_name=cat_data['display_name'],
            display_name_en=cat_data.get('display_name_en'),
            steckbrief_template=cat_data['steckbrief_template'],
            field_groups=cat_data['field_groups'],
            active_groups=cat_data['active_groups'],
            is_active=True
        )
        session.add(new_cat)
        await session.flush()
        category_id = new_cat.id
        stats['category_created'] = True
        logger.info(f"Created category: {internal_name}")
    
    # 2. Process prompts
    prompt_id_map = {}  # internal_name -> id
    
    for prompt_data in config['prompts']:
        prompt_name = prompt_data['internal_name']
        
        result = await session.execute(
            select(Prompt).where(Prompt.internal_name == prompt_name)
        )
        existing_prompt = result.scalar_one_or_none()
        
        # Map YAML field names to DB column names
        extract_prompt = prompt_data.get('prompt_template', prompt_data.get('extract_prompt', ''))
        
        # Fallback validation prompt, with a structured output format
        default_validate_prompt = """Prüfe den extrahierten Wert auf Plausibilität und Qualität.

Extrahierter Wert: {raw_result}

Bewerte:
1. Ist der Wert syntaktisch korrekt (keine HTML-Tags, keine Artefakte)?
2. Ist der Wert inhaltlich plausibel für das Feld?
3. Ist der Wert vollständig oder abgeschnitten?

Antworte NUR in diesem Format:
QUALITY: HIGH | MEDIUM | LOW | INSUFFICIENT
SCORE: 0.0-1.0
NOTES: Kurze Begründung
RESULT: Der bereinigte/korrigierte Wert (oder der Original-Wert wenn korrekt)"""
        
        validate_prompt = prompt_data.get('validate_prompt', default_validate_prompt)
        field_type = prompt_data.get('output_format', prompt_data.get('field_type', 'text'))
        
        if existing_prompt:
            if force_update:
                existing_prompt.display_name = prompt_data['display_name']
                existing_prompt.extract_prompt = extract_prompt
                existing_prompt.validate_prompt = validate_prompt
                existing_prompt.field_type = field_type
                existing_prompt.field_group = prompt_data['field_group']
                existing_prompt.is_active = True
                # Translation fields
                existing_prompt.display_name_en = prompt_data.get('display_name_en')
                existing_prompt.translatable = prompt_data.get('translatable', True)
                existing_prompt.translation_context = prompt_data.get('translation_context')
                existing_prompt.entity_type = prompt_data.get('entity_type')  # Entity linking
                prompt_id_map[prompt_name] = existing_prompt.id
                stats['prompts_updated'] += 1
            else:
                # These fields are refreshed even without force_update, so that a corrected
                # translatable flag in the YAML always reaches the database
                existing_prompt.translatable = prompt_data.get('translatable', True)
                existing_prompt.display_name_en = prompt_data.get('display_name_en')
                existing_prompt.entity_type = prompt_data.get('entity_type')
                prompt_id_map[prompt_name] = existing_prompt.id
                stats['prompts_skipped'] += 1
        else:
            new_prompt = Prompt(
                internal_name=prompt_name,
                display_name=prompt_data['display_name'],
                display_name_en=prompt_data.get('display_name_en'),
                extract_prompt=extract_prompt,
                validate_prompt=validate_prompt,
                field_type=field_type,
                field_group=prompt_data['field_group'],
                is_active=True,
                # Translation fields
                translatable=prompt_data.get('translatable', True),
                translation_context=prompt_data.get('translation_context'),
                # Entity linking
                entity_type=prompt_data.get('entity_type')
            )
            session.add(new_prompt)
            await session.flush()
            prompt_id_map[prompt_name] = new_prompt.id
            stats['prompts_created'] += 1
            logger.debug(f"Created prompt: {prompt_name}")
    
    # 3. Create category-prompt mappings (always create if missing)
    for order, prompt_data in enumerate(config['prompts'], start=1):
        prompt_name = prompt_data['internal_name']
        prompt_id = prompt_id_map.get(prompt_name)
        
        if not prompt_id:
            logger.warning(f"No prompt_id for {prompt_name}, skipping mapping")
            continue
        
        # Check if mapping exists (only needed when not force_update, since we deleted them above)
        if not force_update:
            result = await session.execute(
                select(CategoryPrompt).where(
                    CategoryPrompt.category_id == category_id,
                    CategoryPrompt.prompt_id == prompt_id
                )
            )
            existing_mapping = result.scalar_one_or_none()
            if existing_mapping:
                continue
        
        # Create mapping
        mapping = CategoryPrompt(
            category_id=category_id,
            prompt_id=prompt_id,
            display_order=order * 10
        )
        session.add(mapping)
        stats['mappings_created'] += 1
    
    logger.info(f"Category sync complete: {internal_name}", **stats)
    return stats


async def load_categories_from_config(
    session: AsyncSession,
    only_new: bool = True
) -> dict:
    """
    Load every category from the configuration files.

    Args:
        session: database session
        only_new: if True, load new categories only and leave existing ones alone

    Returns:
        dict of overall statistics
    """
    configs = load_all_category_configs()
    
    total_stats = {
        'categories_created': 0,
        'categories_updated': 0,
        'categories_skipped': 0,
        'prompts_created': 0,
        'prompts_updated': 0,
        'prompts_skipped': 0,
        'mappings_created': 0,
        'mappings_deleted': 0,
        'errors': []
    }
    
    for config in configs:
        # Validate
        is_valid, errors = validate_config(config)
        if not is_valid:
            source_file = config.get('_source_file', 'unknown')
            total_stats['errors'].append({
                'file': source_file,
                'errors': errors
            })
            logger.error(f"Invalid config: {source_file}", errors=errors)
            continue
        
        # Sync
        try:
            stats = await sync_category_from_config(
                session, 
                config, 
                force_update=not only_new
            )
            
            if stats['category_created']:
                total_stats['categories_created'] += 1
            if stats['category_updated']:
                total_stats['categories_updated'] += 1
            if stats['category_skipped']:
                total_stats['categories_skipped'] += 1
            total_stats['prompts_created'] += stats['prompts_created']
            total_stats['prompts_updated'] += stats['prompts_updated']
            total_stats['prompts_skipped'] += stats['prompts_skipped']
            total_stats['mappings_created'] += stats['mappings_created']
            total_stats['mappings_deleted'] += stats.get('mappings_deleted', 0)
            
        except Exception as e:
            source_file = config.get('_source_file', 'unknown')
            total_stats['errors'].append({
                'file': source_file,
                'errors': [str(e)]
            })
            logger.error(f"Failed to sync config: {source_file}", error=str(e))
    
    await session.commit()
    
    logger.info(
        "Category config sync completed",
        categories_created=total_stats['categories_created'],
        categories_updated=total_stats['categories_updated'],
        categories_skipped=total_stats['categories_skipped'],
        prompts_created=total_stats['prompts_created'],
        errors=len(total_stats['errors'])
    )
    
    return total_stats


async def run_seed_if_empty(session: AsyncSession) -> bool:
    """
    Load categories from the configuration files only if none exist yet.

    Called during application startup.
    """
    result = await session.execute(select(Category).limit(1))
    existing = result.scalar_one_or_none()
    
    if existing:
        logger.info("Categories already exist, skipping auto-seed")
        return False
    
    logger.info("No categories found, loading from config files")
    stats = await load_categories_from_config(session, only_new=True)
    
    if stats['categories_created'] > 0:
        logger.info(f"Auto-seed completed: {stats['categories_created']} categories created")
        return True
    elif stats['errors']:
        logger.warning("Auto-seed completed with errors", errors=stats['errors'])
    
    return False

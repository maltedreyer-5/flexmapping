# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Repository layer for database access.

Services talk to repositories, not to SQLAlchemy directly. Relationships that
are needed outside the session are loaded eagerly here: a lazy load after the
session closes raises rather than returning nothing, and it does so at the
call site rather than at the query.
"""
from datetime import datetime, timezone
from typing import Generic, List, Optional, Type, TypeVar
from uuid import UUID

import structlog
from sqlalchemy import select, update, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.models import (
    Base, Source, Prompt, Category, CategoryPrompt, Extraction,
    Entity, EntityVariant, EntityNormalizationQueue, Steckbrief,
    JobQueue, PromptDependency
)

logger = structlog.get_logger()

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Base repository with the common CRUD operations"""

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get(self, id: int) -> Optional[ModelType]:
        """Get by ID"""
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[ModelType]:
        """Get all with pagination"""
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, obj: ModelType) -> ModelType:
        """Create new object"""
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update_obj(self, obj: ModelType) -> ModelType:
        """Update object"""
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete_obj(self, obj: ModelType) -> None:
        """Delete object"""
        await self.session.delete(obj)
        await self.session.flush()

    async def count(self) -> int:
        """Count total records"""
        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return result.scalar()


class SourceRepository(BaseRepository[Source]):
    """Repository for sources"""

    async def get_by_url(self, url: str) -> Optional[Source]:
        """Get Source by URL"""
        result = await self.session.execute(
            select(Source).where(Source.url == url)
        )
        return result.scalar_one_or_none()

    async def get_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Source]:
        """Get Sources by status"""
        result = await self.session.execute(
            select(Source)
            .where(Source.status == status)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_status_and_category(
        self,
        status: Optional[str] = None,
        category_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Source]:
        """Get Sources by status and/or category"""
        query = select(Source)

        conditions = []
        if status:
            conditions.append(Source.status == status)
        if category_id:
            conditions.append(Source.category_id == category_id)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_sources(
        self,
        status: Optional[str] = None,
        category_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[Source]:
        """List sources with optional filters"""
        return await self.get_by_status_and_category(
            status=status,
            category_id=category_id,
            skip=skip,
            limit=limit
        )

    async def get_with_extractions(self, source_id: UUID) -> Optional[Source]:
        """Get Source with all extractions"""
        result = await self.session.execute(
            select(Source)
            .where(Source.id == source_id)
            .options(selectinload(Source.extractions))
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        source_id: UUID,
        status: str,
        error_message: Optional[str] = None
    ) -> None:
        """Update Source status"""
        stmt = (
            update(Source)
            .where(Source.id == source_id)
            .values(status=status, error_message=error_message)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def count_by_status(self, status: str) -> int:
        """Count sources by status"""
        result = await self.session.execute(
            select(func.count()).select_from(Source).where(Source.status == status)
        )
        return result.scalar()

    async def count_by_category(self, category_id: int, status: Optional[str] = None) -> int:
        """Count sources by category and optional status"""
        query = select(func.count()).select_from(Source).where(Source.category_id == category_id)

        if status:
            query = query.where(Source.status == status)

        result = await self.session.execute(query)
        return result.scalar()

    async def count_since(self, cutoff_date: datetime, status: Optional[str] = None) -> int:
        """Count sources created since cutoff date"""
        query = select(func.count()).select_from(Source).where(Source.created_at >= cutoff_date)

        if status:
            query = query.where(Source.status == status)

        result = await self.session.execute(query)
        return result.scalar()


class PromptRepository(BaseRepository[Prompt]):
    """Repository for prompts"""

    async def get_by_internal_name(self, name: str) -> Optional[Prompt]:
        """Get Prompt by internal name"""
        result = await self.session.execute(
            select(Prompt).where(Prompt.internal_name == name)
        )
        return result.scalar_one_or_none()

    async def get_with_dependencies(self, prompt_id: int) -> Optional[Prompt]:
        """
        Get a prompt with its dependencies eagerly loaded.

        The dependencies are read after the session has been handed back, so
        a lazy load at that point raises instead of returning them.
        """
        result = await self.session.execute(
            select(Prompt)
            .where(Prompt.id == prompt_id)
            .options(selectinload(Prompt.dependencies))
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> List[Prompt]:
        """Get all active prompts"""
        result = await self.session.execute(
            select(Prompt).where(Prompt.is_active == True)
        )
        return list(result.scalars().all())

    async def list_all(self, active_only: bool = False) -> List[Prompt]:
        """List all prompts with optional active filter"""
        query = select(Prompt)

        if active_only:
            query = query.where(Prompt.is_active == True)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_category(self, category_id: int, active_only: bool = True) -> List[Prompt]:
        """Get Prompts for category with dependencies eager loaded"""
        query = (
            select(Prompt)
            .join(CategoryPrompt)
            .where(CategoryPrompt.category_id == category_id)
            .options(selectinload(Prompt.dependencies))
            .order_by(CategoryPrompt.display_order)
        )

        if active_only:
            query = query.where(Prompt.is_active == True)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_field_group(self, field_group: str) -> List[Prompt]:
        """Get Prompts by field group"""
        result = await self.session.execute(
            select(Prompt).where(Prompt.field_group == field_group)
        )
        return list(result.scalars().all())


class CategoryRepository(BaseRepository[Category]):
    """Repository for categories"""

    async def get_by_internal_name(self, name: str) -> Optional[Category]:
        """Get Category by internal name"""
        result = await self.session.execute(
            select(Category).where(Category.internal_name == name)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> List[Category]:
        """Get all active categories"""
        result = await self.session.execute(
            select(Category).where(Category.is_active == True)
        )
        return list(result.scalars().all())

    async def list_all(self, active_only: bool = False) -> List[Category]:
        """List all categories with optional active filter"""
        query = select(Category)

        if active_only:
            query = query.where(Category.is_active == True)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_with_prompts(self, category_id: int) -> Optional[Category]:
        """Get Category with associated prompts"""
        result = await self.session.execute(
            select(Category)
            .where(Category.id == category_id)
            .options(
                selectinload(Category.prompt_associations)
                .selectinload(CategoryPrompt.prompt)
            )
        )
        return result.scalar_one_or_none()


class ExtractionRepository(BaseRepository[Extraction]):
    """Repository for extractions"""

    async def get_by_source(self, source_id: UUID) -> List[Extraction]:
        """Get all extractions for a source"""
        result = await self.session.execute(
            select(Extraction)
            .where(Extraction.source_id == source_id)
            .options(joinedload(Extraction.prompt))
        )
        return list(result.scalars().unique().all())

    async def get_by_source_and_prompt(
        self,
        source_id: UUID,
        prompt_id: int
    ) -> Optional[Extraction]:
        """Get specific extraction"""
        result = await self.session.execute(
            select(Extraction)
            .where(
                Extraction.source_id == source_id,
                Extraction.prompt_id == prompt_id
            )
        )
        return result.scalar_one_or_none()

    async def get_low_confidence(
        self,
        threshold: float = 0.7,
        skip: int = 0,
        limit: int = 100
    ) -> List[Extraction]:
        """Get extractions with low confidence"""
        result = await self.session.execute(
            select(Extraction)
            .where(Extraction.final_confidence < threshold)
            .options(
                joinedload(Extraction.source).joinedload(Source.category),
                joinedload(Extraction.prompt)
            )
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_for_entity_normalization(
        self,
        entity_type: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[Extraction]:
        """Get extractions that need entity normalization"""
        result = await self.session.execute(
            select(Extraction)
            .join(Prompt)
            .where(
                Prompt.entity_type == entity_type,
                Extraction.linked_entity_id.is_(None),
                Extraction.validated_result.is_not(None)
            )
            .options(
                joinedload(Extraction.source),
                joinedload(Extraction.prompt)
            )
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().unique().all())


class EntityRepository(BaseRepository[Entity]):
    """Repository for entities"""

    async def get_by_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of type"""
        result = await self.session.execute(
            select(Entity)
            .where(Entity.entity_type == entity_type)
            .options(selectinload(Entity.variants))
        )
        return list(result.scalars().all())

    async def list_all(self) -> List[Entity]:
        """List all entities"""
        result = await self.session.execute(
            select(Entity).options(selectinload(Entity.variants))
        )
        return list(result.scalars().all())

    async def get_by_name(
        self,
        entity_type: str,
        canonical_name: str
    ) -> Optional[Entity]:
        """Get entity by type and canonical name"""
        result = await self.session.execute(
            select(Entity)
            .where(
                Entity.entity_type == entity_type,
                Entity.canonical_name == canonical_name
            )
        )
        return result.scalar_one_or_none()

    async def find_by_variant(
        self,
        variant_name: str
    ) -> Optional[Entity]:
        """Find entity by variant name"""
        result = await self.session.execute(
            select(Entity)
            .join(EntityVariant)
            .where(EntityVariant.variant_name == variant_name)
        )
        return result.scalar_one_or_none()

    async def add_variant(
        self,
        entity_id: int,
        variant_name: str,
        is_auto_detected: bool = False
    ) -> EntityVariant:
        """Add variant to entity"""
        variant = EntityVariant(
            entity_id=entity_id,
            variant_name=variant_name,
            is_auto_detected=is_auto_detected
        )
        self.session.add(variant)
        await self.session.flush()
        await self.session.refresh(variant)
        return variant

    async def get_normalization_queue(
        self,
        status: str = 'pending',
        entity_type: Optional[str] = None,
        limit: int = 100
    ) -> List[EntityNormalizationQueue]:
        """Get normalization queue items with every relationship eagerly loaded"""
        query = (
            select(EntityNormalizationQueue)
            .where(EntityNormalizationQueue.status == status)
            .options(
                selectinload(EntityNormalizationQueue.extraction)
                    .selectinload(Extraction.source)
                    .selectinload(Source.category),
                selectinload(EntityNormalizationQueue.extraction)
                    .selectinload(Extraction.prompt),
                selectinload(EntityNormalizationQueue.llm_suggestion_entity)
                    .selectinload(Entity.variants)
            )
        )

        if entity_type:
            query = query.where(EntityNormalizationQueue.entity_type == entity_type)

        query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().unique().all())


class EntityNormalizationQueueRepository(BaseRepository[EntityNormalizationQueue]):
    """Repository for the entity normalization queue"""

    async def get_pending(
        self,
        entity_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100
    ) -> List[EntityNormalizationQueue]:
        """Get pending normalization tasks"""
        query = select(EntityNormalizationQueue).where(
            EntityNormalizationQueue.status == 'pending'
        )

        if entity_type:
            query = query.where(
                EntityNormalizationQueue.entity_type == entity_type
            )

        query = query.options(
            joinedload(EntityNormalizationQueue.extraction)
            .joinedload(Extraction.source)
        ).offset(skip).limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().unique().all())

    async def mark_reviewed(
        self,
        queue_id: int,
        reviewed_by: str
    ) -> None:
        """Mark as reviewed"""
        stmt = (
            update(EntityNormalizationQueue)
            .where(EntityNormalizationQueue.id == queue_id)
            .values(
                status='reviewed',
                reviewed_by=reviewed_by,
                reviewed_at=datetime.now(timezone.utc)
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()


class SteckbriefRepository(BaseRepository[Steckbrief]):
    """Repository for generated profiles"""

    async def get_by_source(self, source_id: UUID) -> Optional[Steckbrief]:
        """Get the profile belonging to a source"""
        result = await self.session.execute(
            select(Steckbrief)
            .where(Steckbrief.source_id == source_id)
            .options(joinedload(Steckbrief.source))
        )
        return result.scalar_one_or_none()

    async def get_published(
        self,
        skip: int = 0,
        limit: int = 100
    ) -> List[Steckbrief]:
        """Get all published Steckbriefe"""
        result = await self.session.execute(
            select(Steckbrief)
            .where(Steckbrief.published == True)
            .options(joinedload(Steckbrief.source).joinedload(Source.category))
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def list_published(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> List[Steckbrief]:
        """List published Steckbriefe (alias for get_published with swapped params)"""
        return await self.get_published(skip=offset, limit=limit)

    async def publish(
        self,
        steckbrief_id: int
    ) -> None:
        """Mark a profile as published"""
        stmt = (
            update(Steckbrief)
            .where(Steckbrief.id == steckbrief_id)
            .values(
                published=True,
                published_at=datetime.now(timezone.utc)
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()


class JobQueueRepository(BaseRepository[JobQueue]):
    """Repository for the job queue table"""

    async def get_pending(
        self,
        limit: int = 100
    ) -> List[JobQueue]:
        """Get pending jobs ordered by priority"""
        result = await self.session.execute(
            select(JobQueue)
            .where(JobQueue.status == 'pending')
            .order_by(JobQueue.priority.desc(), JobQueue.scheduled_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_running(self, job_id: int) -> None:
        """Mark job as running"""
        stmt = (
            update(JobQueue)
            .where(JobQueue.id == job_id)
            .values(
                status='running',
                started_at=datetime.now(timezone.utc)
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_completed(self, job_id: int) -> None:
        """Mark job as completed"""
        stmt = (
            update(JobQueue)
            .where(JobQueue.id == job_id)
            .values(
                status='completed',
                completed_at=datetime.now(timezone.utc)
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_failed(
        self,
        job_id: int,
        error: str
    ) -> None:
        """Mark job as failed"""
        stmt = (
            update(JobQueue)
            .where(JobQueue.id == job_id)
            .values(
                status='failed',
                last_error=error,
                attempts=JobQueue.attempts + 1
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Database sessions and engines.

Startup retries the connection instead of failing on the first attempt: in a
Compose deployment the application container regularly comes up before the
database is accepting connections.
"""
import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base

logger = structlog.get_logger()
settings = get_settings()

# Async engine, used by the API and the worker
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Async Session Maker
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Sync engine, used by Alembic and the health check
sync_engine = create_engine(
    settings.database_url_sync,
    echo=settings.debug,
    pool_pre_ping=True
)

# Sync Session Maker
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)


async def wait_for_db(max_retries: int = 30, retry_interval: float = 2.0) -> bool:
    """
    Wait until the database accepts connections.

    Args:
        max_retries: maximum number of attempts
        retry_interval: seconds to wait between attempts

    Returns:
        True on success, False after max_retries
    """
    logger.info(
        "Waiting for database connection",
        max_retries=max_retries,
        retry_interval=retry_interval
    )

    for attempt in range(1, max_retries + 1):
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

            logger.info(
                "Database connection established",
                attempt=attempt,
                max_retries=max_retries
            )
            return True

        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    "Database connection failed, retrying",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                    retry_in=retry_interval
                )
                await asyncio.sleep(retry_interval)
            else:
                logger.error(
                    "Database connection failed after all retries",
                    attempts=max_retries,
                    error=str(e)
                )
                return False

    return False


async def init_db():
    """Initialise the database: create the tables and seed the default data"""
    # Wait for the database first
    if not await wait_for_db():
        # A production instance that cannot reach its database has no usable
        # state: the tables are missing and every request fails. Raising here
        # surfaces as a container restart loop, which an operator notices;
        # continuing would leave a process that answers requests with errors
        # while nothing draws attention to the cause.
        if settings.is_production():
            raise RuntimeError(
                "Could not connect to the database after all retries. "
                "Check DATABASE_URL and DATABASE_URL_SYNC."
            )
        logger.error(
            "Could not connect to database, skipping initialization",
            hint="Startup continues because ENVIRONMENT is not production.",
        )
        return

    # Then create the tables
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        logger.info("Database tables created successfully")

    except Exception as e:
        logger.error(
            "Failed to create database tables",
            error=str(e),
            exc_info=True
        )
        # Don't raise - allow app to continue
        # Normal in production, where the tables already exist

    # Seed default categories and prompts if empty
    try:
        from app.seed import run_seed_if_empty
        async with AsyncSessionLocal() as session:
            await run_seed_if_empty(session)
    except Exception as e:
        logger.error(
            "Failed to seed database",
            error=str(e),
            exc_info=True
        )
        # Don't raise - seeding is optional


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency providing an async database session.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_sync_session() -> Session:
    """Return a synchronous session, for Alembic and synchronous code."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for sessions managed by hand.

    Usage:
        async with get_db_session() as db:
            result = await db.execute(query)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def check_db_connection() -> bool:
    """
    Synchronous database check, for the health endpoint.

    Returns:
        True if the database is reachable, False otherwise
    """
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        return False
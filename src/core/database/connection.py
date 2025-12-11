import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

# Add config to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import event
from config.settings import get_settings
import structlog

logger = structlog.get_logger()

settings = get_settings()

# Ensure data directory exists
data_dir = Path(__file__).parent.parent.parent.parent / "data"
data_dir.mkdir(exist_ok=True)

# Create async engine - use StaticPool for SQLite
engine_kwargs = {
    "echo": False,
}

# SQLite specific settings
if "sqlite" in settings.database_url:
    engine_kwargs["poolclass"] = StaticPool
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    from sqlalchemy.pool import NullPool
    engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Global session for singleton pattern (optional use)
_global_session: Optional[AsyncSession] = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session (dependency injection)"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session (context manager)"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_or_create_session() -> AsyncSession:
    """Get or create a global session (for long-running operations)"""
    global _global_session
    if _global_session is None:
        _global_session = AsyncSessionLocal()
    return _global_session


async def close_global_session():
    """Close global session"""
    global _global_session
    if _global_session:
        await _global_session.close()
        _global_session = None


async def init_db():
    """Initialize database tables"""
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database initialized", url=settings.database_url)


async def drop_db():
    """Drop all database tables (for testing)"""
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    logger.info("Database tables dropped")

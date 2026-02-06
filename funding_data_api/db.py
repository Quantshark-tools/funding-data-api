"""Database engine and session management.

Engine and session_factory are initialized at module import time
(singleton pattern). Use SessionDep for FastAPI dependency injection.
"""

from collections.abc import AsyncGenerator
from typing import Annotated

import sqlalchemy_timescaledb  # noqa: F401 need for connection
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from funding_data_api.settings import settings

# =============================================================================
# Engine initialization (singleton)
# =============================================================================


def get_engine_kwargs() -> dict[str, object]:
    """Returns engine kwargs with defaults and optional FDA overrides."""
    defaults = {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 50,
    }
    user_kwargs = settings.db.engine_kwargs or {}
    return {**defaults, **user_kwargs}


# Module-level singleton, initialized at import time
engine = create_async_engine(
    settings.db.connection_url,
    **get_engine_kwargs(),
)

# =============================================================================
# Session factory (singleton)
# =============================================================================


def get_session_kwargs() -> dict[str, object]:
    """Returns session kwargs with defaults and optional FDA overrides."""
    defaults = {
        "expire_on_commit": False,
    }
    user_kwargs = settings.db.session_kwargs or {}
    return {**defaults, **user_kwargs}


session_factory = async_sessionmaker(
    engine,
    **get_session_kwargs(),  # type: ignore[arg-type]
)

# =============================================================================
# FastAPI dependency
# =============================================================================


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yields database session with automatic cleanup."""
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()


SessionDep = Annotated[AsyncSession, Depends(get_session)]

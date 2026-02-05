import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_db_smoke(db_session: AsyncSession) -> None:
    await db_session.execute(text("SELECT 1"))

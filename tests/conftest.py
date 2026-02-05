import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy_timescaledb  # noqa: F401 need for dialect registration
from quantshark_shared.testing.db import DatabaseConfig
from sqlalchemy.ext.asyncio import AsyncSession

pytest_plugins = ["quantshark_shared.testing.fixtures"]


@pytest.fixture(scope="session")
def fda_db_env(db_config: DatabaseConfig) -> DatabaseConfig:
    os.environ["FDA_DB_HOST"] = db_config.host
    os.environ["FDA_DB_PORT"] = str(db_config.port)
    os.environ["FDA_DB_USER"] = db_config.user
    os.environ["FDA_DB_PASSWORD"] = db_config.password
    os.environ["FDA_DB_DBNAME"] = db_config.dbname
    return db_config


@pytest_asyncio.fixture
async def db_session(fda_db_env: DatabaseConfig) -> AsyncIterator[AsyncSession]:
    from funding_data_api.db import get_session

    async for session in get_session():
        yield session

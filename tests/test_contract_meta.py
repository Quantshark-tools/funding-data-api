from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from quantshark_shared.models.contract import Contract
from quantshark_shared.testing.db import truncate_all_tables
from sqlalchemy.ext.asyncio import AsyncSession

from funding_data_api.queries.meta import get_contract_by_id

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]


@pytest_asyncio.fixture()
async def db_cleanup(db_session: AsyncSession) -> AsyncIterator[None]:
    await truncate_all_tables(db_session, exclude={"alembic_version"})
    yield
    await truncate_all_tables(db_session, exclude={"alembic_version"})


@pytest.mark.asyncio
async def test_get_contract_by_id_returns_contract(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    db_cleanup: None,
) -> None:
    contract = await contract_factory(
        asset_name="BTC",
        section_name="Binance",
        quote_name="USDT",
        funding_interval=8,
    )

    result = await get_contract_by_id(db_session, contract.id)

    assert result is not None
    assert result.id == contract.id
    assert result.asset_name == "BTC"
    assert result.section_name == "Binance"
    assert result.quote_name == "USDT"
    assert result.funding_interval == 8
    assert result.deprecated is False


@pytest.mark.asyncio
async def test_get_contract_by_id_returns_none_for_unknown_id(
    db_session: AsyncSession,
    db_cleanup: None,
) -> None:
    result = await get_contract_by_id(db_session, uuid4())

    assert result is None

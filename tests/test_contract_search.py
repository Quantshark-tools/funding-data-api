from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from quantshark_shared.models.contract import Contract
from quantshark_shared.testing.db import truncate_all_tables
from sqlalchemy.ext.asyncio import AsyncSession

from funding_data_api.queries.contract_search import search_contracts

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]


@pytest_asyncio.fixture()
async def db_cleanup(db_session: AsyncSession) -> AsyncIterator[None]:
    await truncate_all_tables(db_session, exclude={"alembic_version"})
    yield
    await truncate_all_tables(db_session, exclude={"alembic_version"})


@pytest.mark.asyncio
async def test_contract_search_prefers_asset_over_section_prefix(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    db_cleanup: None,
) -> None:
    await contract_factory(asset_name="HYPE", section_name="Binance", quote_name="USDT")
    await contract_factory(asset_name="HYPE", section_name="Hyperliquid", quote_name="USDT")
    await contract_factory(asset_name="BTC", section_name="Hyperliquid", quote_name="USDT")

    results = await search_contracts(db_session, query="hype", limit=10, debug=True)

    assert [result.asset_name for result in results] == ["HYPE", "HYPE", "BTC"]
    assert results[0].section_name == "Hyperliquid"


@pytest.mark.asyncio
async def test_contract_search_handles_typos_with_fuzzy_matching(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    db_cleanup: None,
) -> None:
    await contract_factory(asset_name="HYPE", section_name="Binance", quote_name="USDT")
    await contract_factory(asset_name="BTC", section_name="Binance", quote_name="USDT")

    results = await search_contracts(db_session, query="btchype", limit=10, debug=False)

    asset_names = {result.asset_name for result in results}
    assert {"BTC", "HYPE"}.issubset(asset_names)

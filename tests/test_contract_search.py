from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from quantshark_shared.models.contract import Contract
from quantshark_shared.testing.db import truncate_all_tables
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from funding_data_api.queries.contract_search import search_contracts

MATCH_QUALITY_SQL = """
CREATE OR REPLACE FUNCTION match_quality(
  field_value TEXT,
  search_token TEXT
) RETURNS INTEGER AS $$
DECLARE
  field_lower TEXT;
  token_lower TEXT;
  token_len INTEGER;
  field_len INTEGER;
  sim_score REAL;
BEGIN
  field_lower := lower(trim(field_value));
  token_lower := lower(trim(search_token));

  IF field_lower = '' OR token_lower = '' THEN
    RETURN 0;
  END IF;

  token_len := length(token_lower);
  field_len := length(field_lower);

  IF token_len <= 2 THEN
    IF field_lower = token_lower THEN
      RETURN 10000;
    END IF;

    IF field_lower LIKE token_lower || '%' THEN
      RETURN 8000 + (2000 * token_len / field_len)::INTEGER;
    END IF;

    IF field_lower ~ ('(^|[^a-z0-9])' || token_lower || '([^a-z0-9]|$)') THEN
      RETURN 5000;
    END IF;

    IF field_lower LIKE '%' || token_lower || '%' THEN
      RETURN 300;
    END IF;

    RETURN 0;
  END IF;

  IF field_lower = token_lower THEN
    RETURN 10000;
  END IF;

  IF field_lower LIKE token_lower || '%' THEN
    RETURN 5000 + (5000 * token_len / field_len)::INTEGER;
  END IF;

  IF field_lower ~ ('(^|[^a-z0-9])' || token_lower) THEN
    RETURN 2000;
  END IF;

  IF field_lower LIKE '%' || token_lower || '%' THEN
    RETURN 500;
  END IF;

  sim_score := similarity(field_lower, token_lower);

  IF sim_score > 0.2 THEN
    RETURN (sim_score * 300)::INTEGER;
  END IF;

  RETURN 0;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]


@pytest_asyncio.fixture()
async def search_prerequisites(db_session: AsyncSession) -> AsyncIterator[None]:
    await db_session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    await db_session.execute(text(MATCH_QUALITY_SQL))
    await db_session.commit()
    yield


@pytest_asyncio.fixture()
async def db_cleanup(db_session: AsyncSession) -> AsyncIterator[None]:
    await truncate_all_tables(db_session, exclude={"alembic_version"})
    yield
    await truncate_all_tables(db_session, exclude={"alembic_version"})


@pytest.mark.asyncio
async def test_contract_search_prefers_asset_over_section_prefix(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    search_prerequisites: None,
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
    search_prerequisites: None,
    db_cleanup: None,
) -> None:
    await contract_factory(asset_name="HYPE", section_name="Binance", quote_name="USDT")
    await contract_factory(asset_name="BTC", section_name="Binance", quote_name="USDT")

    results = await search_contracts(db_session, query="btchype", limit=10, debug=False)

    asset_names = {result.asset_name for result in results}
    assert {"BTC", "HYPE"}.issubset(asset_names)

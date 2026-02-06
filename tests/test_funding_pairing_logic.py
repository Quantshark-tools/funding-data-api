from collections.abc import Awaitable, Callable
from datetime import datetime

import pytest
from quantshark_shared.models import Contract, LiveFundingPoint
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from funding_data_api.queries.funding_data import get_funding_rate_differences

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]
# Ensures full DB cleanup before/after each test in this module.
pytestmark = pytest.mark.usefixtures("db_cleanup_for_query_tests")


@pytest.mark.asyncio
async def test_no_duplicate_pairs_without_compare_for(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_NO_DUP"

    contracts: list[Contract] = []
    sections = ["Exchange_A", "Exchange_B", "Exchange_C"]
    for section in sections:
        contract = await contract_factory(asset_name, section, "USDT", 8)
        contracts.append(contract)
        db_session.add(
            LiveFundingPoint(contract_id=contract.id, funding_rate=0.01, timestamp=datetime.now())
        )

    await db_session.commit()
    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result = await get_funding_rate_differences(
        db_session,
        asset_names=[asset_name],
        compare_for_section=None,
    )

    assert result.total_count == 3

    seen_pairs: set[frozenset[tuple]] = set()
    for item in result.data:
        pair = frozenset(
            [
                (item.contract_1_id, item.contract_1_section),
                (item.contract_2_id, item.contract_2_section),
            ]
        )
        assert pair not in seen_pairs
        seen_pairs.add(pair)

    all_contract_ids = {c.id for c in contracts}
    found_contract_ids = {item.contract_1_id for item in result.data} | {
        item.contract_2_id for item in result.data
    }
    assert found_contract_ids == all_contract_ids


@pytest.mark.asyncio
async def test_compare_for_section_always_in_contract_1(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_COMPARE"
    compare_section = "Target_Exchange"
    other_sections = ["Exchange_X", "Exchange_Y", "Exchange_Z"]

    compare_contract = await contract_factory(asset_name, compare_section, "USDT", 8)
    db_session.add(
        LiveFundingPoint(
            contract_id=compare_contract.id,
            funding_rate=0.01,
            timestamp=datetime.now(),
        )
    )

    for section in other_sections:
        contract = await contract_factory(asset_name, section, "USDT", 8)
        db_session.add(
            LiveFundingPoint(contract_id=contract.id, funding_rate=0.02, timestamp=datetime.now())
        )

    await db_session.commit()
    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result = await get_funding_rate_differences(
        db_session,
        asset_names=[asset_name],
        compare_for_section=compare_section,
    )

    assert result.total_count == 3
    for item in result.data:
        assert item.contract_1_section == compare_section
        assert item.contract_2_section != compare_section
        assert item.contract_2_section in other_sections

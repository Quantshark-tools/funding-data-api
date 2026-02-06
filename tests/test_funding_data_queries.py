from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from quantshark_shared.models import Contract, HistoricalFundingPoint, LiveFundingPoint
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from funding_data_api.dto.enums import NormalizeToInterval
from funding_data_api.queries.funding_data import (
    get_aggregated_live_points,
    get_cumulative_funding_differences,
    get_funding_rate_differences,
    get_historical_funding_differences_avg,
)

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]
# Ensures full DB cleanup before/after each test in this module.
pytestmark = pytest.mark.usefixtures("db_cleanup_for_query_tests")


def generate_live_funding_points(contract_id: UUID) -> list[LiveFundingPoint]:
    points: list[LiveFundingPoint] = []
    now = datetime.now()
    total_minutes = 3 * 24 * 60
    for i in range(total_minutes):
        points.append(
            LiveFundingPoint(
                contract_id=contract_id,
                timestamp=now - timedelta(minutes=i),
                funding_rate=0.0001 * ((i % 10) - 5),
            )
        )
    return points


@pytest.mark.parametrize(
    "start_offset_secs,end_offset_secs,min_expected_points",
    [
        (-int(timedelta(days=3).total_seconds()), 0, 50),
        (-int(timedelta(minutes=30).total_seconds()), 0, 5),
        (
            -int(timedelta(minutes=90).total_seconds()),
            -int(timedelta(minutes=30).total_seconds()),
            5,
        ),
        (
            -int(timedelta(days=2).total_seconds()),
            -int(timedelta(minutes=30).total_seconds()),
            20,
        ),
        (-int(timedelta(days=3).total_seconds()), -int(timedelta(hours=3).total_seconds()), 10),
    ],
)
@pytest.mark.asyncio
async def test_get_aggregated_live_points(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    engine: AsyncEngine,
    start_offset_secs: int,
    end_offset_secs: int,
    min_expected_points: int,
) -> None:
    contract = await contract_factory("BTC_AGG", "CEX_AGG", "USDT", 8)
    db_session.add_all(generate_live_funding_points(contract.id))
    await db_session.commit()

    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_connection.execute(
            text("CALL refresh_continuous_aggregate('lfp_5min', NULL, NULL);")
        )
        await autocommit_connection.execute(
            text("CALL refresh_continuous_aggregate('lfp_15min', NULL, NULL);")
        )
        await autocommit_connection.execute(
            text("CALL refresh_continuous_aggregate('lfp_1hour', NULL, NULL);")
        )

    now_ts = int(datetime.now().timestamp())
    result = await get_aggregated_live_points(
        db_session,
        contract_id=contract.id,
        from_ts=now_ts + start_offset_secs,
        to_ts=now_ts + end_offset_secs,
    )

    assert len(result) >= min_expected_points
    assert all(
        (now_ts + start_offset_secs) <= item.timestamp <= (now_ts + end_offset_secs)
        for item in result
    )
    for i in range(len(result) - 1):
        assert result[i].timestamp <= result[i + 1].timestamp


@pytest.mark.parametrize(
    "base_interval,target_interval,expected_multiplier",
    [
        (1, NormalizeToInterval.H8, 8.0),
        (4, NormalizeToInterval.H8, 2.0),
        (8, NormalizeToInterval.D1, 3.0),
        (1, NormalizeToInterval.RAW, 1.0),
        (8, NormalizeToInterval.D365, 1095.0),
    ],
)
@pytest.mark.asyncio
async def test_get_aggregated_live_points_with_normalization(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
    base_interval: int,
    target_interval: NormalizeToInterval,
    expected_multiplier: float,
) -> None:
    contract = await contract_factory(
        f"BTC-{base_interval}-{target_interval.value}",
        "CEX-NORM",
        "USDT",
        base_interval,
    )
    raw_rate = 0.0123
    db_session.add(
        LiveFundingPoint(
            timestamp=datetime.now() - timedelta(minutes=30),
            contract_id=contract.id,
            funding_rate=raw_rate,
        )
    )
    await db_session.commit()

    result = await get_aggregated_live_points(
        db_session,
        contract_id=contract.id,
        from_ts=int((datetime.now() - timedelta(days=1)).timestamp()),
        to_ts=int(datetime.now().timestamp()),
        normalize_to_interval=target_interval,
    )

    assert len(result) == 1
    assert result[0].funding_rate == pytest.approx(raw_rate * expected_multiplier)


@pytest.mark.asyncio
async def test_get_funding_rate_differences_basic_scenario(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_BASIC_SCENARIO"
    quote_name = "USDT"
    section_a, section_b, section_c = "ExchangeA", "ExchangeB", "ExchangeC"

    contract_a = await contract_factory(asset_name, section_a, quote_name, 8)
    contract_b = await contract_factory(asset_name, section_b, quote_name, 8)
    contract_c = await contract_factory(asset_name, section_c, quote_name, 1)

    now = datetime.now()
    db_session.add_all(
        [
            LiveFundingPoint(contract_id=contract_a.id, funding_rate=0.01, timestamp=now),
            LiveFundingPoint(contract_id=contract_b.id, funding_rate=-0.02, timestamp=now),
            LiveFundingPoint(contract_id=contract_c.id, funding_rate=0.005, timestamp=now),
        ]
    )
    await db_session.commit()

    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result = await get_funding_rate_differences(db_session, asset_names=[asset_name])

    assert len(result.data) == 3
    assert result.total_count == 3
    assert result.offset == 0
    assert result.has_more is False

    top_result = result.data[0]
    assert top_result.asset_name == asset_name
    assert {top_result.contract_1_section, top_result.contract_2_section} == {section_b, section_c}


@pytest.mark.asyncio
async def test_get_cumulative_funding_differences_basic_scenario(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_CUMULATIVE"
    section_a, section_b = "ExchangeA_C", "ExchangeB_C"

    contract_8h = await contract_factory(asset_name, section_a, "USDT", 8)
    contract_1h = await contract_factory(asset_name, section_b, "USDT", 1)

    base_dt = datetime(2024, 1, 1, 0, 0, 0)
    funding_points: list[HistoricalFundingPoint] = []

    for i in range(24):
        current_dt = base_dt + timedelta(hours=i)
        funding_points.append(
            HistoricalFundingPoint(
                contract_id=contract_1h.id,
                funding_rate=0.001 * (i + 1),
                timestamp=current_dt,
            )
        )

        if i % 8 == 0:
            ts_dt = current_dt - timedelta(minutes=5) if i == 0 else current_dt
            funding_points.append(
                HistoricalFundingPoint(
                    contract_id=contract_8h.id,
                    funding_rate=0.01 * (i // 8 + 1),
                    timestamp=ts_dt,
                )
            )

    db_session.add_all(funding_points)
    await db_session.commit()

    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result = await get_cumulative_funding_differences(
        db_session,
        from_ts=int((base_dt + timedelta(hours=1)).timestamp()),
        to_ts=int((base_dt + timedelta(hours=23)).timestamp()),
        asset_names=[asset_name],
    )

    assert len(result.data) == 1
    assert result.total_count == 1
    res = result.data[0]
    assert res.aligned_from == int(base_dt.timestamp())
    assert res.aligned_to == int((base_dt + timedelta(hours=16)).timestamp())


@pytest.mark.asyncio
async def test_get_funding_rate_differences_with_min_diff(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_MIN_DIFF_TEST"
    quote_name = "USDT"

    contracts = [
        await contract_factory(asset_name, "ExchangeA", quote_name, 8),
        await contract_factory(asset_name, "ExchangeB", quote_name, 8),
        await contract_factory(asset_name, "ExchangeC", quote_name, 8),
        await contract_factory(asset_name, "ExchangeD", quote_name, 8),
    ]

    now = datetime.now()
    db_session.add_all(
        [
            LiveFundingPoint(contract_id=contracts[0].id, funding_rate=0.01, timestamp=now),
            LiveFundingPoint(contract_id=contracts[1].id, funding_rate=0.005, timestamp=now),
            LiveFundingPoint(contract_id=contracts[2].id, funding_rate=0.015, timestamp=now),
            LiveFundingPoint(contract_id=contracts[3].id, funding_rate=0.002, timestamp=now),
        ]
    )
    await db_session.commit()

    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result_no_filter = await get_funding_rate_differences(db_session, asset_names=[asset_name])
    assert len(result_no_filter.data) == 6

    result_with_filter = await get_funding_rate_differences(
        db_session,
        asset_names=[asset_name],
        min_diff=6.0,
    )
    assert len(result_with_filter.data) == 3

    result_empty = await get_funding_rate_differences(
        db_session,
        asset_names=[asset_name],
        min_diff=100.0,
    )
    assert len(result_empty.data) == 0


@pytest.mark.asyncio
async def test_get_historical_funding_differences_avg_with_normalization(
    db_session: AsyncSession,
    contract_factory: ContractFactory,
) -> None:
    asset_name = "BTC_AVG_NORMALIZED_TEST"

    contract_a = await contract_factory(asset_name, "ExchangeA_AVG", "USDT", 8)
    contract_b = await contract_factory(asset_name, "ExchangeB_AVG", "USDT", 4)
    contract_c = await contract_factory(asset_name, "ExchangeC_AVG", "USDT", 8)

    from_time = datetime(2024, 1, 1, 0, 0)
    to_time = datetime(2024, 1, 1, 23, 59)

    funding_records: list[HistoricalFundingPoint] = []
    for i in range(3):
        funding_records.append(
            HistoricalFundingPoint(
                contract_id=contract_a.id,
                funding_rate=0.002,
                timestamp=from_time + timedelta(hours=8 * i),
            )
        )
    for i in range(6):
        funding_records.append(
            HistoricalFundingPoint(
                contract_id=contract_b.id,
                funding_rate=0.001,
                timestamp=from_time + timedelta(hours=4 * i),
            )
        )
    for i in range(3):
        funding_records.append(
            HistoricalFundingPoint(
                contract_id=contract_c.id,
                funding_rate=0.008,
                timestamp=from_time + timedelta(hours=8 * i),
            )
        )

    db_session.add_all(funding_records)
    await db_session.commit()

    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()

    result_normalized = await get_historical_funding_differences_avg(
        db_session,
        from_ts=int(from_time.timestamp()),
        to_ts=int(to_time.timestamp()),
        normalize_to_interval=NormalizeToInterval.D1,
        asset_names=[asset_name],
    )
    assert len(result_normalized.data) == 3
    assert result_normalized.data[0].abs_difference == pytest.approx(0.018, abs=0.001)

    result_filtered = await get_historical_funding_differences_avg(
        db_session,
        from_ts=int(from_time.timestamp()),
        to_ts=int(to_time.timestamp()),
        normalize_to_interval=NormalizeToInterval.D1,
        asset_names=[asset_name],
        min_diff=0.01,
    )
    assert len(result_filtered.data) == 2

    with pytest.raises(ValueError, match="RAW normalization is not supported"):
        await get_historical_funding_differences_avg(
            db_session,
            from_ts=int(from_time.timestamp()),
            to_ts=int(to_time.timestamp()),
            normalize_to_interval=NormalizeToInterval.RAW,
            asset_names=[asset_name],
        )

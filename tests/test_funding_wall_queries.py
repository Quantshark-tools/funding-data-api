from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from quantshark_shared.models import Asset, Contract, HistoricalFundingPoint, LiveFundingPoint
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from funding_data_api.dto.enums import NormalizeToInterval
from funding_data_api.queries.funding_data import (
    get_funding_wall_historical_normalized,
    get_funding_wall_historical_raw,
    get_funding_wall_live_normalized,
    get_funding_wall_live_raw,
)

ContractFactory = Callable[[str, str, str, int], Awaitable[Contract]]
# Ensures full DB cleanup before/after each test in this module.
pytestmark = pytest.mark.usefixtures("db_cleanup_for_query_tests")


@pytest_asyncio.fixture
async def multi_contract_setup(contract_factory: ContractFactory) -> dict[str, Contract]:
    contracts: dict[str, Contract] = {}
    contracts["BTC_Binance"] = await contract_factory("BTC", "Binance", "USDT", 8)
    contracts["BTC_OKX"] = await contract_factory("BTC", "OKX", "USDT", 8)
    contracts["ETH_Binance"] = await contract_factory("ETH", "Binance", "USDT", 8)
    contracts["ETH_OKX"] = await contract_factory("ETH", "OKX", "USDT", 4)
    contracts["SOL_Binance"] = await contract_factory("SOL", "Binance", "USDT", 8)
    return contracts


@pytest_asyncio.fixture
async def setup_live_data(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
) -> dict[str, float]:
    now = datetime.now(UTC)
    expected: dict[str, float] = {
        "BTC_Binance": 0.001,
        "BTC_OKX": 0.0015,
        "ETH_Binance": -0.0005,
        "ETH_OKX": 0.0008,
        "SOL_Binance": 0.002,
    }

    db_session.add_all(
        [
            LiveFundingPoint(
                contract_id=multi_contract_setup["BTC_Binance"].id,
                timestamp=now - timedelta(minutes=5),
                funding_rate=expected["BTC_Binance"],
            ),
            LiveFundingPoint(
                contract_id=multi_contract_setup["BTC_OKX"].id,
                timestamp=now - timedelta(minutes=3),
                funding_rate=expected["BTC_OKX"],
            ),
            LiveFundingPoint(
                contract_id=multi_contract_setup["ETH_Binance"].id,
                timestamp=now - timedelta(minutes=2),
                funding_rate=expected["ETH_Binance"],
            ),
            LiveFundingPoint(
                contract_id=multi_contract_setup["ETH_OKX"].id,
                timestamp=now - timedelta(minutes=1),
                funding_rate=expected["ETH_OKX"],
            ),
            LiveFundingPoint(
                contract_id=multi_contract_setup["SOL_Binance"].id,
                timestamp=now - timedelta(minutes=4),
                funding_rate=expected["SOL_Binance"],
            ),
            LiveFundingPoint(
                contract_id=multi_contract_setup["BTC_Binance"].id,
                timestamp=now - timedelta(minutes=15),
                funding_rate=0.999,
            ),
        ]
    )
    await db_session.commit()
    return expected


@pytest_asyncio.fixture
async def setup_historical_data(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
) -> dict[str, list[float]]:
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    expected_rates: dict[str, list[float]] = {}

    btc_binance_rates = [0.001, 0.002, 0.0015]
    btc_okx_rates = [0.0008, 0.0012, 0.001]
    eth_binance_rates = [-0.0005, 0.0003]

    rows: list[HistoricalFundingPoint] = []
    for i, rate in enumerate(btc_binance_rates):
        rows.append(
            HistoricalFundingPoint(
                contract_id=multi_contract_setup["BTC_Binance"].id,
                timestamp=base_time + timedelta(hours=i * 8),
                funding_rate=rate,
            )
        )
    for i, rate in enumerate(btc_okx_rates):
        rows.append(
            HistoricalFundingPoint(
                contract_id=multi_contract_setup["BTC_OKX"].id,
                timestamp=base_time + timedelta(hours=i * 8),
                funding_rate=rate,
            )
        )
    for i, rate in enumerate(eth_binance_rates):
        rows.append(
            HistoricalFundingPoint(
                contract_id=multi_contract_setup["ETH_Binance"].id,
                timestamp=base_time + timedelta(hours=i * 8),
                funding_rate=rate,
            )
        )

    expected_rates["BTC_Binance"] = btc_binance_rates
    expected_rates["BTC_OKX"] = btc_okx_rates
    expected_rates["ETH_Binance"] = eth_binance_rates

    db_session.add_all(rows)
    await db_session.commit()
    return expected_rates


@pytest.mark.asyncio
async def test_get_funding_wall_live_raw_basic_functionality(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_live_data: dict[str, float],
) -> None:
    result = await get_funding_wall_live_raw(
        db_session,
        asset_names=["BTC", "ETH"],
        section_names=["Binance", "OKX"],
    )

    assert result.exchanges == ["Binance", "OKX"]
    assert len(result.assets) == 2
    btc_asset = next(a for a in result.assets if a.asset == "BTC")
    eth_asset = next(a for a in result.assets if a.asset == "ETH")

    assert btc_asset.rates["Binance"] == setup_live_data["BTC_Binance"]
    assert btc_asset.rates["OKX"] == setup_live_data["BTC_OKX"]
    assert eth_asset.rates["Binance"] == setup_live_data["ETH_Binance"]
    assert eth_asset.rates["OKX"] == setup_live_data["ETH_OKX"]


@pytest.mark.asyncio
async def test_get_funding_wall_live_raw_missing_exchange_data(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_live_data: dict[str, float],
) -> None:
    result = await get_funding_wall_live_raw(
        db_session,
        asset_names=["SOL"],
        section_names=["Binance", "OKX"],
    )

    assert len(result.assets) == 1
    sol = result.assets[0]
    assert sol.rates["Binance"] == setup_live_data["SOL_Binance"]
    assert sol.rates["OKX"] is None


@pytest.mark.asyncio
async def test_get_funding_wall_live_normalized_basic_functionality(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_live_data: dict[str, float],
) -> None:
    result = await get_funding_wall_live_normalized(
        db_session,
        asset_names=["BTC", "ETH"],
        section_names=["Binance", "OKX"],
        normalize_to_interval=NormalizeToInterval.H1,
    )

    btc_asset = next(a for a in result.assets if a.asset == "BTC")
    eth_asset = next(a for a in result.assets if a.asset == "ETH")

    assert btc_asset.rates["Binance"] == pytest.approx(
        setup_live_data["BTC_Binance"] * (1.0 / 8.0)
    )
    assert btc_asset.rates["OKX"] == pytest.approx(setup_live_data["BTC_OKX"] * (1.0 / 8.0))
    assert eth_asset.rates["Binance"] == pytest.approx(
        setup_live_data["ETH_Binance"] * (1.0 / 8.0)
    )
    assert eth_asset.rates["OKX"] == pytest.approx(setup_live_data["ETH_OKX"] * (1.0 / 4.0))


@pytest.mark.asyncio
async def test_get_funding_wall_historical_raw_basic_functionality(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_historical_data: dict[str, list[float]],
) -> None:
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    from_ts = int(base_time.timestamp())
    to_ts = int((base_time + timedelta(days=3)).timestamp())

    result = await get_funding_wall_historical_raw(
        db_session,
        asset_names=["BTC", "ETH"],
        section_names=["Binance", "OKX"],
        from_ts=from_ts,
        to_ts=to_ts,
    )

    btc_asset = next(a for a in result.assets if a.asset == "BTC")
    eth_asset = next(a for a in result.assets if a.asset == "ETH")
    assert btc_asset.rates["Binance"] == sum(setup_historical_data["BTC_Binance"])
    assert btc_asset.rates["OKX"] == sum(setup_historical_data["BTC_OKX"])
    assert eth_asset.rates["Binance"] == sum(setup_historical_data["ETH_Binance"])
    assert eth_asset.rates["OKX"] is None


@pytest.mark.asyncio
async def test_get_funding_wall_historical_normalized_basic_functionality(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_historical_data: dict[str, list[float]],
) -> None:
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    result = await get_funding_wall_historical_normalized(
        db_session,
        asset_names=["BTC"],
        section_names=["Binance", "OKX"],
        from_ts=int(base_time.timestamp()),
        to_ts=int((base_time + timedelta(days=3)).timestamp()),
        normalize_to_interval=NormalizeToInterval.H1,
    )

    btc = result.assets[0]
    btc_binance_avg = sum(setup_historical_data["BTC_Binance"]) / len(
        setup_historical_data["BTC_Binance"]
    )
    btc_okx_avg = sum(setup_historical_data["BTC_OKX"]) / len(setup_historical_data["BTC_OKX"])

    assert btc.rates["Binance"] == pytest.approx(btc_binance_avg * (1.0 / 8.0))
    assert btc.rates["OKX"] == pytest.approx(btc_okx_avg * (1.0 / 8.0))


@pytest.mark.asyncio
async def test_get_funding_wall_market_cap_rank_included(
    db_session: AsyncSession,
    multi_contract_setup: dict[str, Contract],
    setup_live_data: dict[str, float],
) -> None:
    await db_session.execute(update(Asset).where(Asset.name == "BTC").values(market_cap_rank=1))
    await db_session.execute(update(Asset).where(Asset.name == "ETH").values(market_cap_rank=2))
    await db_session.commit()

    result = await get_funding_wall_live_raw(
        db_session,
        asset_names=["BTC", "ETH"],
        section_names=["Binance"],
    )

    btc_asset = next(a for a in result.assets if a.asset == "BTC")
    eth_asset = next(a for a in result.assets if a.asset == "ETH")
    assert btc_asset.market_cap_rank == 1
    assert eth_asset.market_cap_rank == 2


@pytest.mark.asyncio
async def test_contract_enriched_view_can_refresh(db_session: AsyncSession) -> None:
    await db_session.execute(text("REFRESH MATERIALIZED VIEW contract_enriched;"))
    await db_session.commit()
    assert True

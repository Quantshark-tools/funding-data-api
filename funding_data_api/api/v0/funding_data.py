"""Funding-data endpoints."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from funding_data_api.db import SessionDep
from funding_data_api.dto.enums import NormalizeToInterval
from funding_data_api.dto.funding_data import (
    FundingPeriodSums,
    FundingPoint,
    FundingWallResponse,
    PaginatedCumulativeFundingDifference,
    PaginatedFundingRateDifference,
)
from funding_data_api.queries.funding_data import (
    get_aggregated_live_points,
    get_cumulative_funding_differences,
    get_funding_period_sums,
    get_funding_rate_differences,
    get_funding_wall_historical_normalized,
    get_funding_wall_historical_raw,
    get_funding_wall_live_normalized,
    get_funding_wall_live_raw,
    get_historical_funding_differences_avg,
    get_historical_points,
)

router = APIRouter(prefix="/funding-data", tags=["funding-data"])


def validate_time_range(from_ts: int, to_ts: int) -> tuple[int, int]:
    now_ts = int(datetime.now().timestamp())
    one_year_ago_ts = int((datetime.now() - timedelta(days=365)).timestamp())

    if from_ts < one_year_ago_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"from_ts cannot be older than 1 year. Minimum allowed: {one_year_ago_ts}",
        )

    if from_ts >= to_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_ts must be less than to_ts",
        )

    if to_ts > now_ts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="to_ts cannot be in the future",
        )

    return from_ts, to_ts


TimeRangeValidated = Annotated[tuple[int, int], Depends(validate_time_range)]


def validate_optional_time_range(
    from_ts: int | None = None, to_ts: int | None = None
) -> tuple[int | None, int | None]:
    if from_ts is None and to_ts is None:
        return None, None

    if from_ts is None or to_ts is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both from_ts and to_ts must be provided together",
        )

    validate_time_range(from_ts, to_ts)
    return from_ts, to_ts


OptionalTimeRangeValidated = Annotated[
    tuple[int | None, int | None], Depends(validate_optional_time_range)
]


@router.get(
    "/historical_points",
    response_model=Sequence[FundingPoint],
    summary="Get historical funding points for a contract",
)
async def historical_points(
    session: SessionDep,
    contract_id: UUID,
    time_range: TimeRangeValidated,
    normalize_to_interval: NormalizeToInterval = NormalizeToInterval.RAW,
) -> Sequence[FundingPoint]:
    from_ts, to_ts = time_range
    return await get_historical_points(
        session,
        contract_id=contract_id,
        from_ts=from_ts,
        to_ts=to_ts,
        normalize_to_interval=normalize_to_interval,
    )


@router.get(
    "/live_points",
    response_model=Sequence[FundingPoint],
    summary="Get aggregated live funding points for a contract",
)
async def live_points(
    session: SessionDep,
    contract_id: UUID,
    time_range: TimeRangeValidated,
    normalize_to_interval: NormalizeToInterval = NormalizeToInterval.RAW,
) -> Sequence[FundingPoint]:
    from_ts, to_ts = time_range
    return await get_aggregated_live_points(
        session,
        contract_id=contract_id,
        from_ts=from_ts,
        to_ts=to_ts,
        normalize_to_interval=normalize_to_interval,
    )


@router.get(
    "/period_sums/{contract_id}",
    response_model=FundingPeriodSums,
    summary="Get funding sums for different time periods for a specific contract",
)
async def period_sums(
    session: SessionDep,
    contract_id: UUID,
) -> FundingPeriodSums:
    return await get_funding_period_sums(session, contract_id)


@router.get(
    "/diff/live_differences",
    response_model=PaginatedFundingRateDifference,
    summary="Get latest funding rate differences between contracts for the same asset",
)
async def funding_rate_differences(
    session: SessionDep,
    asset_names: list[str] | None = Query(
        None,
        description="List of asset names to filter by. 'all' or leave empty for all assets.",
    ),
    section_names: list[str] | None = Query(
        None,
        description="List of section names to filter by. 'all' or leave empty for all sections.",
    ),
    quote_names: list[str] | None = Query(
        None,
        description=(
            "List of quote currency names to filter by. 'all' or leave empty for all quotes."
        ),
    ),
    normalize_to_interval: NormalizeToInterval = NormalizeToInterval.D365,
    compare_for_section: str | None = Query(
        None, description="A specific section to compare against all others."
    ),
    min_diff: float | None = Query(
        None,
        ge=0,
        description=(
            "Minimum absolute difference to filter results. "
            "Only differences >= min_diff will be returned."
        ),
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedFundingRateDifference:
    return await get_funding_rate_differences(
        session,
        asset_names=asset_names,
        section_names=section_names,
        quote_names=quote_names,
        normalize_to_interval=normalize_to_interval,
        compare_for_section=compare_for_section,
        min_diff=min_diff,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/diff/historical_differences",
    response_model=PaginatedCumulativeFundingDifference,
    summary="Get historical funding differences over a time period with optional normalization",
)
async def historical_funding_differences(
    session: SessionDep,
    time_range: TimeRangeValidated,
    normalize_to_interval: NormalizeToInterval = NormalizeToInterval.RAW,
    asset_names: list[str] | None = Query(None),
    section_names: list[str] | None = Query(None),
    quote_names: list[str] | None = Query(None),
    compare_for_section: str | None = Query(None),
    min_diff: float | None = Query(None, ge=0),
    buffer_minutes: int = 30,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedCumulativeFundingDifference:
    from_ts, to_ts = time_range
    if normalize_to_interval == NormalizeToInterval.RAW:
        return await get_cumulative_funding_differences(
            session,
            from_ts=from_ts,
            to_ts=to_ts,
            asset_names=asset_names,
            section_names=section_names,
            quote_names=quote_names,
            compare_for_section=compare_for_section,
            min_diff=min_diff,
            buffer_minutes=buffer_minutes,
            offset=offset,
            limit=limit,
        )

    return await get_historical_funding_differences_avg(
        session,
        from_ts=from_ts,
        to_ts=to_ts,
        normalize_to_interval=normalize_to_interval,
        asset_names=asset_names,
        section_names=section_names,
        quote_names=quote_names,
        compare_for_section=compare_for_section,
        min_diff=min_diff,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/diff/historical_cumulative_differences",
    response_model=PaginatedCumulativeFundingDifference,
    summary="Get cumulative funding differences over a time period",
)
async def historical_cumulative_differences(
    session: SessionDep,
    time_range: TimeRangeValidated,
    asset_names: list[str] | None = Query(None),
    section_names: list[str] | None = Query(None),
    quote_names: list[str] | None = Query(None),
    compare_for_section: str | None = Query(None),
    min_diff: float | None = Query(None, ge=0),
    buffer_minutes: int = 30,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> PaginatedCumulativeFundingDifference:
    from_ts, to_ts = time_range
    return await get_cumulative_funding_differences(
        session,
        from_ts=from_ts,
        to_ts=to_ts,
        asset_names=asset_names,
        section_names=section_names,
        quote_names=quote_names,
        compare_for_section=compare_for_section,
        min_diff=min_diff,
        buffer_minutes=buffer_minutes,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/funding-wall",
    response_model=FundingWallResponse,
    summary="Get funding wall matrix data",
)
async def funding_wall(
    session: SessionDep,
    time_range: OptionalTimeRangeValidated,
    period: Literal["live", "historical"],
    assets: list[str] = Query(..., description="List of asset names to filter by"),
    exchanges: list[str] = Query(..., description="List of exchange names to filter by"),
    normalize: NormalizeToInterval = Query(..., description="Normalization interval"),
) -> FundingWallResponse:
    from_ts, to_ts = time_range

    if period == "live":
        if normalize == NormalizeToInterval.RAW:
            return await get_funding_wall_live_raw(session, assets, exchanges)
        return await get_funding_wall_live_normalized(session, assets, exchanges, normalize)

    if (not from_ts) or (not to_ts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_ts and to_ts are required for historical period",
        )

    if normalize == NormalizeToInterval.RAW:
        return await get_funding_wall_historical_raw(
            session,
            asset_names=assets,
            section_names=exchanges,
            from_ts=from_ts,
            to_ts=to_ts,
        )

    return await get_funding_wall_historical_normalized(
        session,
        asset_names=assets,
        section_names=exchanges,
        from_ts=from_ts,
        to_ts=to_ts,
        normalize_to_interval=normalize,
    )

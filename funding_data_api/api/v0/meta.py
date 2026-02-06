"""Meta endpoints for assets, sections, and quotes."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from funding_data_api.db import SessionDep
from funding_data_api.dto.base import BaseResponse
from funding_data_api.dto.meta import (
    AssetNames,
    ContractMeta,
    ContractSearchResults,
    QuoteNames,
    SectionNames,
)
from funding_data_api.queries.contract_search import DEFAULT_LIMIT, MAX_LIMIT
from funding_data_api.queries.contract_search import search_contracts as fetch_contracts
from funding_data_api.queries.meta import (
    get_all_assets,
    get_all_quotes,
    get_all_sections,
    get_contract_by_id,
)

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/assets")
async def get_assets(session: SessionDep) -> BaseResponse[AssetNames]:
    """Get all asset names that exist in contracts.

    Returns assets sorted by market_cap_rank (ascending), then alphabetically
    for assets without market_cap_rank.
    """
    assets = await get_all_assets(session)
    return BaseResponse(data=AssetNames(names=assets))


@router.get("/sections")
async def get_sections(session: SessionDep) -> BaseResponse[SectionNames]:
    """Get all section names ordered alphabetically."""
    sections = await get_all_sections(session)
    return BaseResponse(data=SectionNames(names=sections))


@router.get("/quotes")
async def get_quotes(session: SessionDep) -> BaseResponse[QuoteNames]:
    """Get all quote names ordered alphabetically."""
    quotes = await get_all_quotes(session)
    return BaseResponse(data=QuoteNames(names=quotes))


@router.get("/contracts/search", response_model_exclude_none=True)
async def search_contracts(
    session: SessionDep,
    query: str = Query(min_length=1, max_length=200),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    debug: bool = Query(False),
) -> BaseResponse[ContractSearchResults]:
    """Search contracts with prefix-aware scoring and fuzzy fallback."""
    contracts = await fetch_contracts(session, query=query, limit=limit, debug=debug)
    return BaseResponse(data=ContractSearchResults(contracts=contracts))


@router.get("/contracts/{contract_id}")
async def get_contract_meta(session: SessionDep, contract_id: UUID) -> BaseResponse[ContractMeta]:
    """Get single contract metadata by contract id."""
    contract = await get_contract_by_id(session, contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract not found",
        )

    return BaseResponse(data=contract)

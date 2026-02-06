"""Query helpers for meta endpoints."""

from uuid import UUID

from quantshark_shared.models.asset import Asset
from quantshark_shared.models.contract import Contract
from quantshark_shared.models.quote import Quote
from quantshark_shared.models.section import Section
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from funding_data_api.dto.meta import ContractMeta


async def get_all_assets(session: AsyncSession) -> list[str]:
    """Get all asset names that exist in contracts.

    Returns assets sorted by market_cap_rank (ascending), then alphabetically
    for assets without market_cap_rank.
    """
    # Get distinct asset names from contracts
    contracts_result = await session.execute(select(Contract.asset_name).distinct())
    contract_asset_names = {row[0] for row in contracts_result}

    # Fetch all assets with those names, ordered by market_cap_rank
    # Ascending rank = better rank (1 is better than 100)
    assets_result = await session.execute(
        select(Asset)
        .where(col(Asset.name).in_(contract_asset_names))
        .order_by(col(Asset.market_cap_rank))
    )
    assets = assets_result.scalars().all()

    # Extract names in market cap order (None values end up last)
    sorted_asset_names = [asset.name for asset in assets if asset.market_cap_rank is not None]

    # Add remaining assets without market_cap_rank, sorted alphabetically
    remaining_names = contract_asset_names - set(sorted_asset_names)
    sorted_asset_names.extend(sorted(remaining_names))

    return sorted_asset_names


async def get_all_sections(session: AsyncSession) -> list[str]:
    """Get all section names ordered alphabetically."""
    result = await session.execute(select(Section.name).order_by(Section.name))
    return [row[0] for row in result]


async def get_all_quotes(session: AsyncSession) -> list[str]:
    """Get all quote names ordered alphabetically."""
    result = await session.execute(select(Quote.name).order_by(Quote.name))
    return [row[0] for row in result]


async def get_contract_by_id(session: AsyncSession, contract_id: UUID) -> ContractMeta | None:
    """Get single contract metadata by contract id."""
    result = await session.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if contract is None:
        return None

    return ContractMeta(
        id=contract.id,
        asset_name=contract.asset_name,
        section_name=contract.section_name,
        quote_name=contract.quote_name,
        funding_interval=contract.funding_interval,
        synced=contract.synced,
        special_fields=contract.special_fields,
        deprecated=contract.deprecated,
    )

"""DTOs for meta endpoints."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AssetNames(BaseModel):
    names: list[str]


class SectionNames(BaseModel):
    names: list[str]


class QuoteNames(BaseModel):
    names: list[str]


class ContractSearchResult(BaseModel):
    id: UUID
    asset_name: str
    section_name: str
    quote_name: str
    funding_interval: int
    relevance_score: int
    asset_score: int | None = None
    section_score: int | None = None
    quote_score: int | None = None
    fuzzy_score: int | None = None


class ContractSearchResults(BaseModel):
    contracts: list[ContractSearchResult]


class ContractMeta(BaseModel):
    id: UUID
    asset_name: str
    section_name: str
    quote_name: str
    funding_interval: int
    synced: bool
    special_fields: dict[str, Any]
    deprecated: bool

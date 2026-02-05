"""Query dependency for contract search."""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import text

from funding_data_api.db import SessionDep
from funding_data_api.dto.meta import ContractSearchResult

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
SIMILARITY_THRESHOLD = 0.1
FUZZY_MIN_SCORE = 200

SEARCH_CONTRACTS_SQL = text(
    """
    WITH
    tokens AS (
      SELECT unnest(
        regexp_split_to_array(lower(trim(:query)), E'[\\s\\-/]+')
      ) AS token
      WHERE trim(:query) != ''
    ),
    candidates AS (
      SELECT c.*
      FROM contract c
      WHERE c.deprecated = false AND (
        (
          char_length(trim(:query)) >= 3
          AND similarity(
            lower(c.asset_name) || ' ' || lower(c.section_name) || ' ' || lower(c.quote_name),
            lower(:query)
          ) >= :similarity_threshold
        )
        OR EXISTS (
          SELECT 1 FROM tokens t
          WHERE lower(c.asset_name) = t.token
             OR lower(c.section_name) = t.token
             OR lower(c.quote_name) = t.token
             OR lower(c.asset_name) LIKE t.token || '%'
             OR lower(c.section_name) LIKE t.token || '%'
             OR lower(c.quote_name) LIKE t.token || '%'
             OR (
               char_length(t.token) >= 3
               AND (
                 lower(c.asset_name) LIKE '%' || t.token || '%'
                 OR lower(c.section_name) LIKE '%' || t.token || '%'
                 OR lower(c.quote_name) LIKE '%' || t.token || '%'
               )
             )
        )
      )
    ),
    scored AS (
      SELECT
        c.*,
        (
          SELECT COALESCE(SUM(match_quality(c.asset_name, t.token)), 0)
          FROM tokens t
        ) AS asset_score,
        (
          SELECT COALESCE(SUM(match_quality(c.section_name, t.token)), 0)
          FROM tokens t
        ) AS section_score,
        (
          SELECT COALESCE(SUM(match_quality(c.quote_name, t.token)), 0)
          FROM tokens t
        ) AS quote_score,
        similarity(
          lower(c.asset_name) || ' ' || lower(c.section_name) || ' ' || lower(c.quote_name),
          lower(:query)
        ) * 1000 AS fuzzy_score
      FROM candidates c
    )
    SELECT
      id,
      asset_name,
      section_name,
      quote_name,
      funding_interval,
      (
        asset_score * 3
        + section_score * 2
        + quote_score * 1
        + fuzzy_score
      )::INTEGER AS relevance_score,
      asset_score,
      section_score,
      quote_score,
      fuzzy_score::INTEGER
    FROM scored
    WHERE asset_score > 0
      OR section_score > 0
      OR quote_score > 0
      OR fuzzy_score > :fuzzy_min_score
    ORDER BY relevance_score DESC
    LIMIT :limit;
    """
)


async def search_contracts(
    session: SessionDep,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)],
    debug: Annotated[bool, Query(False)],
) -> list[ContractSearchResult]:
    """Search contracts by query with prefix-aware scoring and fuzzy fallback."""
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    result = await session.execute(
        SEARCH_CONTRACTS_SQL,
        {
            "query": cleaned_query,
            "limit": limit,
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "fuzzy_min_score": FUZZY_MIN_SCORE,
        },
    )
    rows = result.mappings().all()
    contracts: list[ContractSearchResult] = []
    for row in rows:
        contracts.append(
            ContractSearchResult(
                id=row["id"],
                asset_name=row["asset_name"],
                section_name=row["section_name"],
                quote_name=row["quote_name"],
                funding_interval=row["funding_interval"],
                relevance_score=row["relevance_score"],
                asset_score=row["asset_score"] if debug else None,
                section_score=row["section_score"] if debug else None,
                quote_score=row["quote_score"] if debug else None,
                fuzzy_score=row["fuzzy_score"] if debug else None,
            )
        )

    return contracts


SearchContractsDep = Annotated[list[ContractSearchResult], Depends(search_contracts)]

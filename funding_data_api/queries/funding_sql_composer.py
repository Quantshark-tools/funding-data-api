"""SQL composer for funding data diff and wall queries."""

from funding_data_api.dto.enums import NormalizeToInterval


def process_filter_list(
    filter_list: list[str] | None,
    compare_for_section: str | None = None,
    is_section_filter: bool = False,
) -> list[str]:
    processed = ["all"] if not filter_list or "all" in filter_list else filter_list

    if (
        is_section_filter
        and compare_for_section
        and "all" not in processed
        and compare_for_section not in processed
    ):
        processed = processed + [compare_for_section]

    return processed


class ProcessedFilters:
    def __init__(
        self,
        asset_names: list[str],
        section_names: list[str],
        quote_names: list[str],
        compare_for_section: str | None = None,
    ):
        self.asset_names = asset_names
        self.section_names = section_names
        self.quote_names = quote_names
        self.compare_for_section = compare_for_section

    def to_dict(self) -> dict[str, list[str] | str | None]:
        return {
            "asset_names": self.asset_names,
            "section_names": self.section_names,
            "quote_names": self.quote_names,
            "compare_for_section": self.compare_for_section,
        }


class FundingQueryComposer:
    @staticmethod
    def process_filters(
        asset_names: list[str] | None,
        section_names: list[str] | None,
        quote_names: list[str] | None,
        compare_for_section: str | None = None,
    ) -> ProcessedFilters:
        return ProcessedFilters(
            asset_names=process_filter_list(asset_names),
            section_names=process_filter_list(
                section_names, compare_for_section, is_section_filter=True
            ),
            quote_names=process_filter_list(quote_names),
            compare_for_section=compare_for_section,
        )

    @staticmethod
    def extract_hours_from_interval(normalize_to_interval: NormalizeToInterval) -> float:
        if normalize_to_interval == NormalizeToInterval.RAW:
            raise ValueError("RAW normalization is not supported for this operation.")

        interval_value = normalize_to_interval.value
        unit = interval_value[-1]
        amount = float(interval_value[:-1])
        return amount if unit == "h" else amount * 24

    @staticmethod
    def calculate_target_hours(normalize_to_interval: NormalizeToInterval) -> float:
        if normalize_to_interval == NormalizeToInterval.RAW:
            return 1.0

        interval_value = normalize_to_interval.value
        unit = interval_value[-1]
        amount = float(interval_value[:-1])
        return amount if unit == "h" else amount * 24

    @staticmethod
    def get_pairing_condition(compare_for_section: str | None) -> str:
        if compare_for_section:
            return """
                contract1.section_name = :compare_for_section
                AND contract2.section_name != :compare_for_section
            """

        return "contract1.contract_id < contract2.contract_id"

    @staticmethod
    def build_filtered_contracts_cte() -> str:
        return """
        filtered_contracts AS (
            SELECT
                contracts.id AS contract_id,
                contracts.asset_name,
                contracts.quote_name,
                contracts.section_name,
                contracts.funding_interval
            FROM contract_enriched contracts
            WHERE ('all' = ANY(:asset_names) OR contracts.asset_name = ANY(:asset_names))
              AND ('all' = ANY(:section_names) OR contracts.section_name = ANY(:section_names))
              AND ('all' = ANY(:quote_names) OR contracts.quote_name = ANY(:quote_names))
        )"""

    @staticmethod
    def build_contract_pairs_cte(
        compare_for_section: str | None = None, include_max_interval: bool = False
    ) -> str:
        pairing_condition = FundingQueryComposer.get_pairing_condition(compare_for_section)

        max_interval_column = ""
        if include_max_interval:
            max_interval_column = ",\n                GREATEST(contract1.funding_interval, contract2.funding_interval) as max_interval_hours"

        return f"""
        contract_pairs AS (
            SELECT
                contract1.contract_id as contract_1_id,
                contract1.asset_name,
                contract1.section_name as contract_1_section,
                contract1.quote_name as contract_1_quote,
                contract2.contract_id as contract_2_id,
                contract2.section_name as contract_2_section,
                contract2.quote_name as contract_2_quote{max_interval_column}
            FROM filtered_contracts contract1
            JOIN filtered_contracts contract2 ON contract1.asset_name = contract2.asset_name
            WHERE {pairing_condition.strip()}
        )"""

    @classmethod
    def build_funding_rate_differences_query(
        cls, normalize_to_interval: NormalizeToInterval, compare_for_section: str | None = None
    ) -> str:
        if normalize_to_interval == NormalizeToInterval.RAW:
            hours_per_period = 1.0
            multiplier_expr = "1.0"
        else:
            hours_per_period = cls.extract_hours_from_interval(normalize_to_interval)
            multiplier_expr = f"{hours_per_period} / fc.funding_interval"

        filtered_contracts_cte = cls.build_filtered_contracts_cte()
        contract_pairs_cte = cls.build_contract_pairs_cte(
            compare_for_section, include_max_interval=False
        )

        return f"""
        WITH
        {filtered_contracts_cte},

        {contract_pairs_cte},

        latest_data AS (
            SELECT
                contract_id,
                last(timestamp, timestamp) AS timestamp,
                last(funding_rate, timestamp) AS funding_rate
            FROM live_funding_point
            WHERE timestamp >= NOW() - INTERVAL '10 minutes'
              AND contract_id IN (SELECT contract_id FROM filtered_contracts)
            GROUP BY contract_id
        ),

        contracts_with_rates AS (
            SELECT
                fc.contract_id,
                fc.asset_name,
                fc.quote_name,
                fc.section_name,
                (ld.funding_rate * {multiplier_expr}) AS normalized_rate
            FROM filtered_contracts fc
            JOIN latest_data ld ON fc.contract_id = ld.contract_id
        ),

        comparison_results AS (
            SELECT
                cp.asset_name,
                cp.contract_1_id,
                cp.contract_1_section,
                cp.contract_1_quote,
                c1.normalized_rate AS contract_1_funding_rate,
                cp.contract_2_id,
                cp.contract_2_section,
                cp.contract_2_quote,
                c2.normalized_rate AS contract_2_funding_rate,
                (c1.normalized_rate - c2.normalized_rate) AS difference,
                ABS(c1.normalized_rate - c2.normalized_rate) AS abs_difference
            FROM contract_pairs cp
            JOIN contracts_with_rates c1 ON cp.contract_1_id = c1.contract_id
            JOIN contracts_with_rates c2 ON cp.contract_2_id = c2.contract_id
        )

        SELECT comparison_results.*,
               COUNT(*) OVER() AS total_count
        FROM comparison_results
        WHERE (:min_diff < 0 OR comparison_results.abs_difference >= :min_diff)
        ORDER BY abs_difference DESC
        LIMIT :limit OFFSET :offset;
        """

    @classmethod
    def build_cumulative_funding_differences_query(
        cls, compare_for_section: str | None = None
    ) -> str:
        filtered_contracts_cte = cls.build_filtered_contracts_cte()
        contract_pairs_cte = cls.build_contract_pairs_cte(
            compare_for_section, include_max_interval=True
        )

        return f"""
        WITH
        {filtered_contracts_cte},

        {contract_pairs_cte},

        distinct_windows AS (
            SELECT DISTINCT
                max_interval_hours,
                time_bucket(make_interval(hours => max_interval_hours), :from_time) AS aligned_from,
                time_bucket(make_interval(hours => max_interval_hours), :to_time) AS aligned_to
            FROM contract_pairs
        ),

        funding_in_window AS (
            SELECT
                distinct_windows.aligned_from,
                distinct_windows.aligned_to,
                funding_records.contract_id,
                SUM(funding_records.funding_rate) AS total_funding
            FROM distinct_windows
            JOIN historical_funding_point funding_records ON
                funding_records.timestamp >= (distinct_windows.aligned_from - make_interval(mins => :buffer_minutes))
                AND funding_records.timestamp < distinct_windows.aligned_to
                AND funding_records.contract_id IN (SELECT contract_id FROM filtered_contracts)
            GROUP BY distinct_windows.aligned_from, distinct_windows.aligned_to, funding_records.contract_id
        ),

        comparison_results AS (
            SELECT
                contract_pairs.asset_name,
                contract_pairs.contract_1_id AS contract_1_id,
                contract_pairs.contract_1_section AS contract_1_section,
                contract_pairs.contract_1_quote AS contract_1_quote,
                COALESCE(contract1_funding.total_funding, 0) AS contract_1_total_funding,
                contract_pairs.contract_2_id AS contract_2_id,
                contract_pairs.contract_2_section AS contract_2_section,
                contract_pairs.contract_2_quote AS contract_2_quote,
                COALESCE(contract2_funding.total_funding, 0) AS contract_2_total_funding,
                (COALESCE(contract1_funding.total_funding, 0) - COALESCE(contract2_funding.total_funding, 0)) AS difference,
                ABS(COALESCE(contract1_funding.total_funding, 0) - COALESCE(contract2_funding.total_funding, 0)) AS abs_difference,
                EXTRACT(EPOCH FROM aligned_windows.aligned_from)::bigint AS aligned_from,
                EXTRACT(EPOCH FROM aligned_windows.aligned_to)::bigint AS aligned_to
            FROM contract_pairs
            JOIN distinct_windows aligned_windows ON contract_pairs.max_interval_hours = aligned_windows.max_interval_hours
            LEFT JOIN funding_in_window contract1_funding ON
                contract_pairs.contract_1_id = contract1_funding.contract_id
                AND aligned_windows.aligned_from = contract1_funding.aligned_from
                AND aligned_windows.aligned_to = contract1_funding.aligned_to
            LEFT JOIN funding_in_window contract2_funding ON
                contract_pairs.contract_2_id = contract2_funding.contract_id
                AND aligned_windows.aligned_from = contract2_funding.aligned_from
                AND aligned_windows.aligned_to = contract2_funding.aligned_to
        )

        SELECT comparison_results.*,
               COUNT(*) OVER() AS total_count
        FROM comparison_results
        WHERE (:min_diff < 0 OR comparison_results.abs_difference >= :min_diff)
        ORDER BY abs_difference DESC
        LIMIT :limit OFFSET :offset;
        """

    @staticmethod
    def build_funding_wall_live_raw_query() -> str:
        return """
        WITH latest_rates AS (
            SELECT DISTINCT ON (c.asset_name, c.section_name)
                c.asset_name,
                c.section_name,
                lfp.funding_rate,
                lfp.timestamp,
                a.market_cap_rank
            FROM contract c
            JOIN live_funding_point lfp ON c.id = lfp.contract_id
            JOIN asset a ON c.asset_name = a.name
            WHERE
                c.deprecated = false
                AND c.asset_name = ANY(:asset_names)
                AND c.section_name = ANY(:section_names)
                AND lfp.timestamp >= NOW() - INTERVAL '10 minutes'
            ORDER BY c.asset_name, c.section_name, lfp.timestamp DESC
        ),
        max_timestamp AS (
            SELECT MAX(timestamp) as max_ts FROM latest_rates
        )
        SELECT
            lr.asset_name,
            lr.market_cap_rank,
            lr.section_name,
            lr.funding_rate,
            EXTRACT(epoch FROM (SELECT max_ts FROM max_timestamp))::bigint as timestamp
        FROM latest_rates lr
        ORDER BY lr.asset_name, lr.section_name
        """

    @staticmethod
    def build_funding_wall_live_normalized_query() -> str:
        return """
        WITH latest_rates AS (
            SELECT DISTINCT ON (c.asset_name, c.section_name)
                c.asset_name,
                c.section_name,
                lfp.funding_rate,
                lfp.timestamp,
                a.market_cap_rank,
                CASE
                    WHEN :is_raw THEN 1.0
                    WHEN c.funding_interval > 0 THEN :target_hours / c.funding_interval
                    ELSE 1.0
                END as multiplier
            FROM contract c
            JOIN live_funding_point lfp ON c.id = lfp.contract_id
            JOIN asset a ON c.asset_name = a.name
            WHERE
                c.deprecated = false
                AND c.asset_name = ANY(:asset_names)
                AND c.section_name = ANY(:section_names)
                AND lfp.timestamp >= NOW() - INTERVAL '10 minutes'
            ORDER BY c.asset_name, c.section_name, lfp.timestamp DESC
        ),
        max_timestamp AS (
            SELECT MAX(timestamp) as max_ts FROM latest_rates
        )
        SELECT
            lr.asset_name,
            lr.market_cap_rank,
            lr.section_name,
            lr.funding_rate * lr.multiplier as funding_rate,
            EXTRACT(epoch FROM (SELECT max_ts FROM max_timestamp))::bigint as timestamp
        FROM latest_rates lr
        ORDER BY lr.asset_name, lr.section_name
        """

    @staticmethod
    def build_funding_wall_historical_raw_query() -> str:
        return """
        SELECT
            c.asset_name,
            a.market_cap_rank,
            c.section_name,
            SUM(hfp.funding_rate) as funding_rate_sum,
            :to_ts as timestamp
        FROM contract c
        JOIN historical_funding_point hfp ON c.id = hfp.contract_id
        JOIN asset a ON c.asset_name = a.name
        WHERE
            c.deprecated = false
            AND c.asset_name = ANY(:asset_names)
            AND c.section_name = ANY(:section_names)
            AND hfp.timestamp >= :start_date
            AND hfp.timestamp <= :end_date
        GROUP BY c.asset_name, a.market_cap_rank, c.section_name
        ORDER BY c.asset_name, c.section_name
        """

    @staticmethod
    def build_funding_wall_historical_normalized_query() -> str:
        return """
        SELECT
            c.asset_name,
            a.market_cap_rank,
            c.section_name,
            AVG(hfp.funding_rate) *
            CASE
                WHEN :is_raw THEN 1.0
                WHEN c.funding_interval > 0 THEN :target_hours / c.funding_interval
                ELSE 1.0
            END as funding_rate_avg_normalized,
            :to_ts as timestamp
        FROM contract c
        JOIN historical_funding_point hfp ON c.id = hfp.contract_id
        JOIN asset a ON c.asset_name = a.name
        WHERE
            c.deprecated = false
            AND c.asset_name = ANY(:asset_names)
            AND c.section_name = ANY(:section_names)
            AND hfp.timestamp >= :start_date
            AND hfp.timestamp <= :end_date
        GROUP BY c.asset_name, a.market_cap_rank, c.section_name, c.funding_interval
        ORDER BY c.asset_name, c.section_name
        """

    @classmethod
    def build_historical_funding_differences_avg_query(
        cls, compare_for_section: str | None = None
    ) -> str:
        filtered_contracts_cte = cls.build_filtered_contracts_cte()
        contract_pairs_cte = cls.build_contract_pairs_cte(
            compare_for_section, include_max_interval=False
        )

        return f"""
        WITH
        {filtered_contracts_cte},

        {contract_pairs_cte},

        contract_avg_rates AS (
            SELECT
                fc.contract_id,
                fc.asset_name,
                fc.quote_name,
                fc.section_name,
                fc.funding_interval,
                AVG(hfp.funding_rate) as avg_funding_rate
            FROM filtered_contracts fc
            JOIN historical_funding_point hfp ON fc.contract_id = hfp.contract_id
            WHERE hfp.timestamp >= :start_date
              AND hfp.timestamp <= :end_date
            GROUP BY fc.contract_id, fc.asset_name, fc.quote_name, fc.section_name, fc.funding_interval
        ),

        contracts_with_normalized_rates AS (
            SELECT
                car.contract_id,
                car.asset_name,
                car.quote_name,
                car.section_name,
                car.avg_funding_rate *
                CASE
                    WHEN car.funding_interval > 0 THEN :target_hours / car.funding_interval
                    ELSE 1.0
                END as normalized_avg_rate
            FROM contract_avg_rates car
        ),

        comparison_results AS (
            SELECT
                cp.asset_name,
                cp.contract_1_id,
                cp.contract_1_section,
                cp.contract_1_quote,
                COALESCE(c1.normalized_avg_rate, 0) AS contract_1_total_funding,
                cp.contract_2_id,
                cp.contract_2_section,
                cp.contract_2_quote,
                COALESCE(c2.normalized_avg_rate, 0) AS contract_2_total_funding,
                (COALESCE(c1.normalized_avg_rate, 0) - COALESCE(c2.normalized_avg_rate, 0)) AS difference,
                ABS(COALESCE(c1.normalized_avg_rate, 0) - COALESCE(c2.normalized_avg_rate, 0)) AS abs_difference,
                :from_ts as aligned_from,
                :to_ts as aligned_to
            FROM contract_pairs cp
            LEFT JOIN contracts_with_normalized_rates c1 ON cp.contract_1_id = c1.contract_id
            LEFT JOIN contracts_with_normalized_rates c2 ON cp.contract_2_id = c2.contract_id
        )

        SELECT comparison_results.*,
               COUNT(*) OVER() AS total_count
        FROM comparison_results
        WHERE (:min_diff < 0 OR comparison_results.abs_difference >= :min_diff)
        ORDER BY abs_difference DESC
        LIMIT :limit OFFSET :offset;
        """

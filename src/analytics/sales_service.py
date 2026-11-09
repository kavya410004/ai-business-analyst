"""Domain analytics service for sales effectiveness (Category 2).

Covers Opportunity Win Rate (Count & Value) and Win Rate Change Diagnostics (Two-Component Kitagawa Decomposition).
Answers Question 2 (Lowest win rate region) and Question 3 (Why win rate dropped in Q3).
"""

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CohortShiftShare,
    CohortWinRate,
    MetricCategory,
    MetricMetadata,
    MetricResult,
    ShiftShareDecomposition,
    WinRateSummary,
)


class SalesEffectivenessService:
    """Service providing deterministic sales effectiveness and conversion diagnostics."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @staticmethod
    def _parse_quarter(quarter_str: str) -> Tuple[str, str]:
        """Convert quarter string (e.g. '2026Q3') to (start_date, end_date)."""
        m = re.match(r"^(\d{4})[-_]?[Qq]([1-4])$", quarter_str.strip())
        if not m:
            raise ValueError(f"Invalid quarter format: '{quarter_str}'. Expected format like '2026Q3'.")
        year, qtr = int(m.group(1)), int(m.group(2))
        ranges = {
            1: (f"{year}-01-01", f"{year}-03-31"),
            2: (f"{year}-04-01", f"{year}-06-30"),
            3: (f"{year}-07-01", f"{year}-09-30"),
            4: (f"{year}-10-01", f"{year}-12-31"),
        }
        return ranges[qtr]

    def get_win_rates(
        self,
        dimension: str = "region",
        quarter: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        currency: Optional[str] = None,
        segment: Optional[str] = None,
        region: Optional[str] = None,
    ) -> MetricResult:
        """Calculate opportunity win rate across cohorts for a specified dimension.
        
        Answers Question 2: Which region has the lowest win rate?
        Open deals are strictly excluded from the win rate denominator.
        """
        valid_dimensions = {"region", "segment", "owner", "owner_id"}
        dim = dimension.strip().lower()
        if dim not in valid_dimensions:
            raise ValueError(f"Invalid dimension '{dimension}'. Valid options: {valid_dimensions}")

        dim_col = f"o.owner_name" if dim == "owner" else f"d.{dim}"

        conditions = ["d.stage IN ('won', 'lost')"]
        params: List[Any] = []

        if quarter:
            q_start, q_end = self._parse_quarter(quarter)
            conditions.append("d.close_date BETWEEN ? AND ?")
            params.extend([q_start, q_end])
        elif start_date and end_date:
            conditions.append("d.close_date BETWEEN ? AND ?")
            params.extend([start_date, end_date])

        if currency:
            conditions.append("d.currency = ?")
            params.append(currency.upper())
        if segment:
            conditions.append("d.segment = ?")
            params.append(segment)
        if region and dim != "region":
            conditions.append("d.region = ?")
            params.append(region)

        where_clause = " AND ".join(conditions)
        join_clause = "LEFT JOIN owners o ON d.owner_id = o.owner_id" if dim == "owner" else ""

        sql = f"""
            SELECT 
                {dim_col} AS cohort_value,
                SUM(CASE WHEN d.stage = 'won' THEN 1 ELSE 0 END) AS won_count,
                SUM(CASE WHEN d.stage = 'lost' THEN 1 ELSE 0 END) AS lost_count,
                COUNT(*) AS closed_count,
                COALESCE(SUM(CASE WHEN d.stage = 'won' THEN d.amount ELSE 0 END), 0.0) AS won_amount,
                COALESCE(SUM(CASE WHEN d.stage = 'lost' THEN d.amount ELSE 0 END), 0.0) AS lost_amount,
                SUM(CASE WHEN d.amount IS NULL THEN 1 ELSE 0 END) AS missing_amount_count
            FROM deals d
            {join_clause}
            WHERE {where_clause}
            GROUP BY {dim_col}
            ORDER BY closed_count DESC
        """

        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        total_won = 0
        total_lost = 0
        total_closed = 0
        total_missing = 0
        cohort_models: List[CohortWinRate] = []
        breakdown: List[Dict[str, Any]] = []

        data_quality_notes = [
            "Open deals (stage = 'open') are excluded from win rate denominator per Salesforce standard."
        ]

        for r in rows:
            c_val = str(r["cohort_value"]) if r["cohort_value"] is not None else "Unknown"
            w_cnt = int(r["won_count"])
            l_cnt = int(r["lost_count"])
            cl_cnt = int(r["closed_count"])
            w_amt = float(r["won_amount"])
            l_amt = float(r["lost_amount"])
            miss_cnt = int(r["missing_amount_count"])

            total_won += w_cnt
            total_lost += l_cnt
            total_closed += cl_cnt
            total_missing += miss_cnt

            rate_pct = round((w_cnt / cl_cnt) * 100.0, 2) if cl_cnt > 0 else None
            tot_amt = w_amt + l_amt
            val_pct = round((w_amt / tot_amt) * 100.0, 2) if tot_amt > 0 else None
            insufficient = cl_cnt < 10

            c_model = CohortWinRate(
                dimension_value=c_val,
                won_count=w_cnt,
                lost_count=l_cnt,
                closed_count=cl_cnt,
                win_rate_pct=rate_pct,
                won_amount=round(w_amt, 2) if w_amt > 0 else None,
                lost_amount=round(l_amt, 2) if l_amt > 0 else None,
                win_rate_value_pct=val_pct,
                currency=currency.upper() if currency else None,
                insufficient_data=insufficient,
            )
            cohort_models.append(c_model)
            breakdown.append(c_model.model_dump())

        # Determine lowest and highest win rate cohorts (only among cohorts with closed deals)
        valid_cohorts = [c for c in cohort_models if c.win_rate_pct is not None]
        lowest_cohort = min(valid_cohorts, key=lambda c: c.win_rate_pct) if valid_cohorts else None
        highest_cohort = max(valid_cohorts, key=lambda c: c.win_rate_pct) if valid_cohorts else None
        overall_rate = round((total_won / total_closed) * 100.0, 2) if total_closed > 0 else None

        if total_missing > 0:
            data_quality_notes.append(f"{total_missing} closed deal(s) had NULL amount; omitted from value-based win rate.")

        summary_model = WinRateSummary(
            dimension=dim,
            overall_win_rate_pct=overall_rate,
            lowest_win_rate_cohort=lowest_cohort.dimension_value if lowest_cohort else None,
            lowest_win_rate_pct=lowest_cohort.win_rate_pct if lowest_cohort else None,
            highest_win_rate_cohort=highest_cohort.dimension_value if highest_cohort else None,
            highest_win_rate_pct=highest_cohort.win_rate_pct if highest_cohort else None,
            total_closed_deals=total_closed,
            cohorts=cohort_models,
        )

        metadata = MetricMetadata(
            metric_name=f"Opportunity Win Rate by {dim.capitalize()}",
            category=MetricCategory.SALES,
            definition="Proportion of closed opportunities won: Won / (Won + Lost).",
            formula="SUM(stage = 'won') / COUNT(stage IN ('won', 'lost')) * 100",
            time_period=quarter or (f"{start_date} to {end_date}" if start_date else "All Time"),
            currency=currency.upper() if currency else "ALL (Segregated)",
            filters_applied={
                "dimension": dim,
                "quarter": quarter,
                "currency": currency,
                "segment": segment,
                "region": region,
            },
            supporting_records_count=total_closed,
            sample_size_evaluable=total_closed,
            records_missing_data_count=total_missing,
            data_quality_notes=data_quality_notes,
        )

        return MetricResult(
            metadata=metadata,
            summary=summary_model.model_dump(),
            breakdown=breakdown,
        )

    def diagnose_win_rate_change(
        self,
        base_quarter: str = "2026Q2",
        target_quarter: str = "2026Q3",
        dimension: str = "segment",
    ) -> MetricResult:
        """Decompose period-over-period win rate change using the Two-Component Kitagawa Formula.
        
        Answers Question 3: Why did win rate drop in Q3?
        Decomposes total change into Within-Cohort Rate Effect and Pipeline Mix Shift.
        """
        valid_dimensions = {"segment", "region", "owner"}
        dim = dimension.strip().lower()
        if dim not in valid_dimensions:
            raise ValueError(f"Invalid dimension '{dimension}'. Valid options: {valid_dimensions}")

        base_res = self.get_win_rates(dimension=dim, quarter=base_quarter)
        target_res = self.get_win_rates(dimension=dim, quarter=target_quarter)

        base_closed = base_res.summary.get("total_closed_deals", 0)
        target_closed = target_res.summary.get("total_closed_deals", 0)

        if base_closed == 0 or target_closed == 0:
            raise ValueError(f"Insufficient data to decompose: {base_quarter} closed={base_closed}, {target_quarter} closed={target_closed}")

        base_cohorts = {c["dimension_value"]: c for c in base_res.summary.get("cohorts", [])}
        target_cohorts = {c["dimension_value"]: c for c in target_res.summary.get("cohorts", [])}

        all_keys = sorted(set(base_cohorts.keys()).union(set(target_cohorts.keys())))

        total_rate_effect = 0.0
        total_mix_effect = 0.0
        cohort_details: List[CohortShiftShare] = []

        for key in all_keys:
            b_item = base_cohorts.get(key, {"closed_count": 0, "win_rate_pct": 0.0})
            t_item = target_cohorts.get(key, {"closed_count": 0, "win_rate_pct": 0.0})

            n_b = b_item["closed_count"]
            n_t = t_item["closed_count"]
            r_b = b_item["win_rate_pct"] or 0.0
            r_t = t_item["win_rate_pct"] or 0.0

            w_b = (n_b / base_closed) if base_closed > 0 else 0.0
            w_t = (n_t / target_closed) if target_closed > 0 else 0.0

            # Two-component Kitagawa formula with midpoint weights:
            # Rate Effect = ((w_b + w_t) / 2) * (r_t - r_b)
            # Mix Effect = ((r_b + r_t) / 2) * (w_t - w_b)
            # Since r is in percentage (0-100) and w is in proportion (0-1), both yield percentage points directly.
            rate_eff = ((w_b + w_t) / 2.0) * (r_t - r_b)
            mix_eff = ((r_b + r_t) / 2.0) * (w_t - w_b)

            total_rate_effect += rate_eff
            total_mix_effect += mix_eff

            cohort_details.append(
                CohortShiftShare(
                    cohort_name=key,
                    base_deal_count=n_b,
                    base_deal_share_pct=round(w_b * 100.0, 2),
                    base_win_rate_pct=round(r_b, 2),
                    target_deal_count=n_t,
                    target_deal_share_pct=round(w_t * 100.0, 2),
                    target_win_rate_pct=round(r_t, 2),
                    rate_effect_pct_points=round(rate_eff, 4),
                    mix_effect_pct_points=round(mix_eff, 4),
                )
            )

        w_base = base_res.summary.get("overall_win_rate_pct", 0.0) or 0.0
        w_target = target_res.summary.get("overall_win_rate_pct", 0.0) or 0.0
        total_change = round(w_target - w_base, 2)

        # Determine primary driver
        if abs(total_mix_effect) > abs(total_rate_effect):
            driver = "Pipeline Mix Shift (Composition Effect)"
        else:
            driver = "Within-Cohort Performance Variance (Rate Effect)"

        decomposition = ShiftShareDecomposition(
            base_period=base_quarter,
            target_period=target_quarter,
            dimension=dim,
            base_overall_win_rate_pct=round(w_base, 2),
            target_overall_win_rate_pct=round(w_target, 2),
            total_change_pct_points=total_change,
            rate_effect_pct_points=round(total_rate_effect, 2),
            mix_effect_pct_points=round(total_mix_effect, 2),
            primary_driver=driver,
            cohort_details=cohort_details,
        )

        metadata = MetricMetadata(
            metric_name=f"Win Rate Decomposition by {dim.capitalize()} (Kitagawa Two-Component)",
            category=MetricCategory.SALES,
            definition="Decomposition of win rate variance into within-cohort rate effect vs pipeline mix shift.",
            formula="Delta_W = SUM( (w_b + w_t)/2 * Delta_r ) + SUM( (r_b + r_t)/2 * Delta_w )",
            time_period=f"{base_quarter} to {target_quarter}",
            filters_applied={
                "base_quarter": base_quarter,
                "target_quarter": target_quarter,
                "dimension": dim,
            },
            supporting_records_count=base_closed + target_closed,
            sample_size_evaluable=base_closed + target_closed,
            data_quality_notes=[
                f"Two-component Kitagawa formula: Rate Effect ({total_rate_effect:+.2f} pp) + Mix Effect ({total_mix_effect:+.2f} pp) = Total Change ({total_change:+.2f} pp)."
            ],
        )

        return MetricResult(
            metadata=metadata,
            summary=decomposition.model_dump(),
            breakdown=[c.model_dump() for c in cohort_details],
        )

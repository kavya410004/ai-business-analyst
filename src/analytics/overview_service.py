"""Domain analytics service for business overview and supporting indicators (Category 4).

Synthesizes commercial growth, sales efficiency, pipeline health, and collections risk.
Answers Question 5: How are we doing?
"""

import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

from .models import (
    ExecutiveScorecard,
    MetricCategory,
    MetricMetadata,
    MetricResult,
    RevenueType,
)
from .payment_service import PaymentAnalyticsService
from .revenue_service import RevenueAnalyticsService
from .sales_service import SalesEffectivenessService


class ExecutiveOverviewService:
    """Service providing integrated multi-dimensional business health scorecards."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection
        self.revenue_service = RevenueAnalyticsService(connection)
        self.sales_service = SalesEffectivenessService(connection)
        self.payment_service = PaymentAnalyticsService(connection)

    def get_executive_scorecard(
        self,
        quarter: str = "2026Q3",
        previous_quarter: str = "2026Q2",
        as_of_date: Optional[date] = None,
    ) -> MetricResult:
        """Generate a comprehensive executive business scorecard.
        
        Answers Question 5: How are we doing?
        Synthesizes growth momentum, win rate trends, pipeline health, and collections aging.
        """
        eval_date = as_of_date or date(2026, 9, 30)
        eval_str = eval_date.strftime("%Y-%m-%d")

        # 1. Commercial Growth (Revenue & Bookings)
        rev_comparison = self.revenue_service.compare_quarterly_revenue(
            current_quarter=quarter,
            previous_quarter=previous_quarter,
            revenue_type=RevenueType.CLOSED_WON_BOOKINGS,
        )
        billings_comparison = self.revenue_service.compare_quarterly_revenue(
            current_quarter=quarter,
            previous_quarter=previous_quarter,
            revenue_type=RevenueType.INVOICED_AMOUNT,
        )

        commercial_growth = {
            "evaluation_quarter": quarter,
            "comparison_quarter": previous_quarter,
            "closed_won_bookings": rev_comparison.summary.get("by_currency", {}),
            "invoiced_amount": billings_comparison.summary.get("by_currency", {}),
        }

        # 2. Sales Effectiveness & Conversion
        win_rates_region = self.sales_service.get_win_rates(
            dimension="region",
            quarter=quarter,
        )
        decomp = self.sales_service.diagnose_win_rate_change(
            base_quarter=previous_quarter,
            target_quarter=quarter,
            dimension="segment",
        )

        sales_efficiency = {
            "quarter_win_rate_pct": win_rates_region.summary.get("overall_win_rate_pct"),
            "lowest_win_rate_region": win_rates_region.summary.get("lowest_win_rate_cohort"),
            "lowest_win_rate_pct": win_rates_region.summary.get("lowest_win_rate_pct"),
            "highest_win_rate_region": win_rates_region.summary.get("highest_win_rate_cohort"),
            "highest_win_rate_pct": win_rates_region.summary.get("highest_win_rate_pct"),
            "qoq_win_rate_change_pp": decomp.summary.get("total_change_pct_points"),
            "shift_share_primary_driver": decomp.summary.get("primary_driver"),
            "shift_share_rate_effect_pp": decomp.summary.get("rate_effect_pct_points"),
            "shift_share_mix_effect_pp": decomp.summary.get("mix_effect_pct_points"),
        }

        # 3. Pipeline Health (Open Opportunities)
        cur = self.conn.cursor()
        cur.execute("""
            SELECT 
                currency,
                COUNT(*) as open_deals_count,
                COALESCE(SUM(amount), 0.0) as open_pipeline_value,
                SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) as missing_amount_count
            FROM deals
            WHERE stage = 'open'
            GROUP BY currency
        """)
        open_rows = cur.fetchall()
        open_pipeline_by_currency = {}
        total_open_deals = 0
        for r in open_rows:
            curr, count, val, miss = r["currency"], r["open_deals_count"], r["open_pipeline_value"], r["missing_amount_count"]
            total_open_deals += count
            open_pipeline_by_currency[curr] = {
                "open_deals_count": count,
                "open_pipeline_value": round(float(val), 2),
                "missing_amount_count": miss,
            }

        pipeline_health = {
            "total_open_deals": total_open_deals,
            "by_currency": open_pipeline_by_currency,
        }

        # 4. Collection Efficiency & Cash Risk
        payment_speed = self.payment_service.get_payment_speed_by_dimension(dimension="segment")
        receivables = self.payment_service.get_outstanding_receivables(as_of_date=eval_date)

        collection_efficiency = {
            "slowest_paying_cohort": payment_speed.summary.get("slowest_cohort"),
            "slowest_cohort_median_days_to_pay": payment_speed.summary.get("slowest_cohort_median_days_to_pay"),
            "slowest_cohort_median_days_past_due": payment_speed.summary.get("slowest_cohort_median_days_past_due"),
            "total_unpaid_invoices": receivables.summary.get("unpaid_invoices_count"),
            "current_unpaid_invoices": receivables.summary.get("current_unpaid_invoices_count"),
            "overdue_invoices": receivables.summary.get("overdue_invoices_count"),
            "overdue_amount_by_currency": receivables.summary.get("overdue_amount_by_currency"),
        }

        # 5. Data Quality & Audit Summary
        cur.execute("SELECT COUNT(*) FROM deals")
        total_deals_db = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM deals WHERE stage = 'won' AND amount IS NULL")
        won_missing_amt = cur.fetchone()[0]

        data_quality_summary = {
            "deduplicated_deals_count": total_deals_db,
            "won_deals_missing_amount_count": won_missing_amt,
            "invalid_payment_dates_excluded_count": payment_speed.summary.get("invalid_payment_dates_excluded_count", 0),
        }

        scorecard = ExecutiveScorecard(
            evaluation_quarter=quarter,
            as_of_date=eval_date,
            commercial_growth=commercial_growth,
            sales_efficiency=sales_efficiency,
            pipeline_health=pipeline_health,
            collection_efficiency=collection_efficiency,
            data_quality_summary=data_quality_summary,
        )

        metadata = MetricMetadata(
            metric_name="Executive Business Health Scorecard",
            category=MetricCategory.OVERVIEW,
            definition="Multi-dimensional executive summary evaluating commercial growth, sales effectiveness, pipeline health, and collections efficiency.",
            formula="Multi-service deterministic synthesis",
            time_period=f"{quarter} (As of {eval_str})",
            filters_applied={
                "quarter": quarter,
                "previous_quarter": previous_quarter,
                "as_of_date": eval_str,
            },
            supporting_records_count=total_deals_db,
            sample_size_evaluable=total_deals_db,
            data_quality_notes=[
                f"Evaluation quarter: {quarter}. Comparison base: {previous_quarter}. Receivables anchor: {eval_str}.",
                "All monetary metrics are strictly segregated by currency without synthetic FX assumptions.",
            ],
        )

        return MetricResult(
            metadata=metadata,
            summary=scorecard.model_dump(mode="json"),
            breakdown=[
                {"category": "Commercial Growth", **commercial_growth},
                {"category": "Sales Effectiveness", **sales_efficiency},
                {"category": "Pipeline Health", **pipeline_health},
                {"category": "Collection Efficiency", **collection_efficiency},
            ],
        )


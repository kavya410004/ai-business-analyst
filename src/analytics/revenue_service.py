"""Domain analytics service for revenue and commercial performance (Category 1).

Covers Closed-Won Bookings, Invoiced Amount (Billings), and Collections Proxy.
Answers Question 1: Total revenue last quarter and comparison to quarter before.
"""

import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CurrencyMetricSummary,
    MetricCategory,
    MetricMetadata,
    MetricResult,
    QuarterlyRevenueComparisonSummary,
    RevenueType,
)


class RevenueAnalyticsService:
    """Service providing deterministic revenue, bookings, and billing calculations."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @staticmethod
    def _parse_quarter(quarter_str: str) -> Tuple[str, str]:
        """Convert quarter string (e.g., '2026Q3', '2026-Q3') to (start_date, end_date)."""
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

    def get_revenue_for_period(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        quarter: Optional[str] = None,
        currency: Optional[str] = None,
        revenue_type: RevenueType = RevenueType.CLOSED_WON_BOOKINGS,
        region: Optional[str] = None,
        segment: Optional[str] = None,
    ) -> MetricResult:
        """Calculate commercial performance for a given period with currency segregation."""
        if quarter:
            start_date, end_date = self._parse_quarter(quarter)
        elif not start_date or not end_date:
            raise ValueError("Either 'quarter' or both 'start_date' and 'end_date' must be provided.")

        filters_applied = {
            "start_date": start_date,
            "end_date": end_date,
            "revenue_type": revenue_type.value,
        }
        if quarter:
            filters_applied["quarter"] = quarter
        if currency:
            filters_applied["currency"] = currency.upper()
        if region:
            filters_applied["region"] = region
        if segment:
            filters_applied["segment"] = segment

        data_quality_notes: List[str] = []

        if revenue_type == RevenueType.CLOSED_WON_BOOKINGS:
            # Query deals table for closed-won opportunities
            conditions = ["stage = 'won'", "close_date BETWEEN ? AND ?"]
            params: List[Any] = [start_date, end_date]

            if currency:
                conditions.append("currency = ?")
                params.append(currency.upper())
            if region:
                conditions.append("region = ?")
                params.append(region)
            if segment:
                conditions.append("segment = ?")
                params.append(segment)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT 
                    currency,
                    COUNT(*) as total_won_deals,
                    SUM(CASE WHEN amount IS NOT NULL THEN 1 ELSE 0 END) as evaluable_count,
                    SUM(CASE WHEN amount IS NULL THEN 1 ELSE 0 END) as missing_amount_count,
                    COALESCE(SUM(amount), 0.0) as total_amount
                FROM deals
                WHERE {where_clause}
                GROUP BY currency
                ORDER BY currency DESC
            """
            cur = self.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

            total_records = 0
            evaluable_records = 0
            missing_records = 0
            by_currency: Dict[str, Dict[str, Any]] = {}

            for r in rows:
                c_curr, c_total, c_eval, c_miss, c_amt = r["currency"], r["total_won_deals"], r["evaluable_count"], r["missing_amount_count"], r["total_amount"]
                total_records += c_total
                evaluable_records += c_eval
                missing_records += c_miss
                by_currency[c_curr] = {
                    "currency": c_curr,
                    "total_amount": round(float(c_amt), 2),
                    "won_deals_count": c_total,
                    "evaluable_deals_count": c_eval,
                    "missing_amount_count": c_miss,
                }

            if missing_records > 0:
                data_quality_notes.append(
                    f"{missing_records} won deal(s) have NULL amount in source data; excluded from monetary sum."
                )

            metadata = MetricMetadata(
                metric_name="Closed-Won Bookings",
                category=MetricCategory.REVENUE,
                definition="Total contracted deal value for closed-won opportunities within period.",
                formula="SUM(deals.amount) WHERE stage = 'won' AND close_date BETWEEN start AND end",
                time_period=quarter or f"{start_date} to {end_date}",
                currency=currency.upper() if currency else "ALL (Segregated)",
                filters_applied=filters_applied,
                supporting_records_count=total_records,
                sample_size_evaluable=evaluable_records,
                records_missing_data_count=missing_records,
                data_quality_notes=data_quality_notes,
            )

        elif revenue_type == RevenueType.INVOICED_AMOUNT:
            # Query invoices table for customer billings
            conditions = ["i.issued_date BETWEEN ? AND ?"]
            params = [start_date, end_date]

            if currency:
                conditions.append("d.currency = ?")
                params.append(currency.upper())
            if region:
                conditions.append("d.region = ?")
                params.append(region)
            if segment:
                conditions.append("d.segment = ?")
                params.append(segment)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT 
                    d.currency,
                    COUNT(i.invoice_id) as total_invoices,
                    COALESCE(SUM(i.amount), 0.0) as total_amount
                FROM invoices i
                JOIN deals d ON i.deal_id = d.deal_id
                WHERE {where_clause}
                GROUP BY d.currency
                ORDER BY d.currency DESC
            """
            cur = self.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

            total_records = 0
            by_currency = {}
            for r in rows:
                c_curr, c_total, c_amt = r["currency"], r["total_invoices"], r["total_amount"]
                total_records += c_total
                by_currency[c_curr] = {
                    "currency": c_curr,
                    "total_amount": round(float(c_amt), 2),
                    "invoices_count": c_total,
                }

            metadata = MetricMetadata(
                metric_name="Invoiced Amount (Customer Billings)",
                category=MetricCategory.REVENUE,
                definition="Total gross amount for which invoices were issued within period.",
                formula="SUM(invoices.amount) WHERE issued_date BETWEEN start AND end",
                time_period=quarter or f"{start_date} to {end_date}",
                currency=currency.upper() if currency else "ALL (Segregated)",
                filters_applied=filters_applied,
                supporting_records_count=total_records,
                sample_size_evaluable=total_records,
                data_quality_notes=data_quality_notes,
            )

        elif revenue_type == RevenueType.COLLECTIONS_PROXY:
            # Query paid invoices for cash collections
            conditions = ["i.paid_date IS NOT NULL", "i.paid_date BETWEEN ? AND ?"]
            params = [start_date, end_date]

            if currency:
                conditions.append("d.currency = ?")
                params.append(currency.upper())
            if region:
                conditions.append("d.region = ?")
                params.append(region)
            if segment:
                conditions.append("d.segment = ?")
                params.append(segment)

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT 
                    d.currency,
                    COUNT(i.invoice_id) as paid_invoices,
                    COALESCE(SUM(i.amount), 0.0) as total_amount
                FROM invoices i
                JOIN deals d ON i.deal_id = d.deal_id
                WHERE {where_clause}
                GROUP BY d.currency
                ORDER BY d.currency DESC
            """
            cur = self.conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

            total_records = 0
            by_currency = {}
            for r in rows:
                c_curr, c_total, c_amt = r["currency"], r["total_invoices"], r["total_amount"]
                total_records += c_total
                by_currency[c_curr] = {
                    "currency": c_curr,
                    "total_amount": round(float(c_amt), 2),
                    "paid_invoices_count": c_total,
                }

            metadata = MetricMetadata(
                metric_name="Collections Proxy (Cash-Flow Indicator)",
                category=MetricCategory.REVENUE,
                definition="Total cash collected from paid invoices within period.",
                formula="SUM(invoices.amount) WHERE paid_date BETWEEN start AND end",
                time_period=quarter or f"{start_date} to {end_date}",
                currency=currency.upper() if currency else "ALL (Segregated)",
                filters_applied=filters_applied,
                supporting_records_count=total_records,
                sample_size_evaluable=total_records,
                data_quality_notes=data_quality_notes,
            )
        else:
            raise ValueError(f"Unsupported revenue type: {revenue_type}")

        return MetricResult(
            metadata=metadata,
            summary={"by_currency": by_currency},
            breakdown=[{"currency": k, **v} for k, v in by_currency.items()],
        )

    def compare_quarterly_revenue(
        self,
        current_quarter: str = "2026Q3",
        previous_quarter: str = "2026Q2",
        currency: Optional[str] = None,
        revenue_type: RevenueType = RevenueType.CLOSED_WON_BOOKINGS,
        region: Optional[str] = None,
        segment: Optional[str] = None,
    ) -> MetricResult:
        """Compare commercial metrics between two quarters.
        
        Answers Question 1: What was total revenue last quarter, and how does it compare to the quarter before?
        """
        curr_res = self.get_revenue_for_period(
            quarter=current_quarter,
            currency=currency,
            revenue_type=revenue_type,
            region=region,
            segment=segment,
        )
        prev_res = self.get_revenue_for_period(
            quarter=previous_quarter,
            currency=currency,
            revenue_type=revenue_type,
            region=region,
            segment=segment,
        )

        curr_data = curr_res.summary.get("by_currency", {})
        prev_data = prev_res.summary.get("by_currency", {})

        all_currencies = sorted(set(curr_data.keys()).union(set(prev_data.keys())))
        by_currency_summary: Dict[str, CurrencyMetricSummary] = {}
        breakdown: List[Dict[str, Any]] = []

        total_supporting = curr_res.metadata.supporting_records_count + prev_res.metadata.supporting_records_count
        evaluable_supporting = curr_res.metadata.sample_size_evaluable + prev_res.metadata.sample_size_evaluable
        missing_supporting = curr_res.metadata.records_missing_data_count + prev_res.metadata.records_missing_data_count

        data_quality_notes = list(set(curr_res.metadata.data_quality_notes + prev_res.metadata.data_quality_notes))

        for curr_code in all_currencies:
            c_val = curr_data.get(curr_code, {}).get("total_amount", 0.0)
            p_val = prev_data.get(curr_code, {}).get("total_amount", 0.0)
            c_cnt = curr_data.get(curr_code, {}).get("won_deals_count", curr_data.get(curr_code, {}).get("invoices_count", curr_data.get(curr_code, {}).get("paid_invoices_count", 0)))
            p_cnt = prev_data.get(curr_code, {}).get("won_deals_count", prev_data.get(curr_code, {}).get("invoices_count", prev_data.get(curr_code, {}).get("paid_invoices_count", 0)))

            change_val = round(c_val - p_val, 2)
            growth_pct = round((change_val / p_val) * 100.0, 2) if p_val > 0 else None

            summary_item = CurrencyMetricSummary(
                currency=curr_code,
                current_value=c_val,
                previous_value=p_val,
                change_value=change_val,
                growth_pct=growth_pct,
                current_count=c_cnt,
                previous_count=p_cnt,
            )
            by_currency_summary[curr_code] = summary_item
            breakdown.append({
                "currency": curr_code,
                f"{current_quarter}_value": c_val,
                f"{previous_quarter}_value": p_val,
                "change_value": change_val,
                "growth_pct": growth_pct,
                f"{current_quarter}_count": c_cnt,
                f"{previous_quarter}_count": p_cnt,
            })

        comparison_summary = QuarterlyRevenueComparisonSummary(
            current_quarter=current_quarter,
            previous_quarter=previous_quarter,
            revenue_type=revenue_type.value,
            by_currency=by_currency_summary,
        )

        metadata = MetricMetadata(
            metric_name=f"Quarterly Comparison: {curr_res.metadata.metric_name}",
            category=MetricCategory.REVENUE,
            definition=f"Comparison of {revenue_type.value} between {current_quarter} and {previous_quarter} segregated by currency.",
            formula="(Current_Value - Previous_Value) / Previous_Value * 100",
            time_period=f"{previous_quarter} vs {current_quarter}",
            currency=currency.upper() if currency else "ALL (Segregated)",
            filters_applied={
                "current_quarter": current_quarter,
                "previous_quarter": previous_quarter,
                "revenue_type": revenue_type.value,
                "currency": currency,
                "region": region,
                "segment": segment,
            },
            supporting_records_count=total_supporting,
            sample_size_evaluable=evaluable_supporting,
            records_missing_data_count=missing_supporting,
            data_quality_notes=data_quality_notes,
        )

        return MetricResult(
            metadata=metadata,
            summary=comparison_summary.model_dump(),
            breakdown=breakdown,
        )


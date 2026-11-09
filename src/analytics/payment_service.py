"""Domain analytics service for payment and collections (Category 3).

Covers Payment Turnaround (Days to Pay), Delinquency (Days Past Due), and Receivables Aging.
Answers Question 4: Which segment pays us slowest?
"""

import sqlite3
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import statistics

from .models import (
    CohortPaymentSpeed,
    MetricCategory,
    MetricMetadata,
    MetricResult,
    PaymentSpeedSummary,
    ReceivablesSummary,
)


class PaymentAnalyticsService:
    """Service providing deterministic payment speed, delinquency, and A/R aging calculations."""

    def __init__(self, connection: sqlite3.Connection):
        self.conn = connection

    @staticmethod
    def _parse_date(date_str: str) -> date:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()

    def get_payment_speed_by_dimension(
        self,
        dimension: str = "segment",
        quarter: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> MetricResult:
        """Calculate payment turnaround and delinquency metrics across cohorts.
        
        Answers Question 4: Which segment pays us slowest?
        Excludes records where paid_date < issued_date and flags them.
        """
        valid_dimensions = {"segment", "region"}
        dim = dimension.strip().lower()
        if dim not in valid_dimensions:
            raise ValueError(f"Invalid dimension '{dimension}'. Valid options: {valid_dimensions}")

        conditions = []
        params: List[Any] = []

        if currency:
            conditions.append("d.currency = ?")
            params.append(currency.upper())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Fetch all invoices joined with deals to calculate turnaround and track anomalies
        sql = f"""
            SELECT 
                i.invoice_id,
                i.issued_date,
                i.due_date,
                i.paid_date,
                i.amount,
                d.{dim} AS cohort_value,
                d.currency
            FROM invoices i
            JOIN deals d ON i.deal_id = d.deal_id
            {where_clause}
        """

        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        total_invoices = len(rows)
        paid_invoices_count = 0
        unpaid_invoices_count = 0
        invalid_dates_count = 0

        # Cohort accumulator: cohort -> {days_to_pay: [], days_past_due: [], paid_late: int, paid_ontime: int, unpaid: int}
        cohort_data: Dict[str, Dict[str, Any]] = {}

        for r in rows:
            c_val = str(r["cohort_value"]) if r["cohort_value"] is not None else "Unknown"
            if c_val not in cohort_data:
                cohort_data[c_val] = {
                    "days_to_pay": [],
                    "days_past_due": [],
                    "paid_late": 0,
                    "paid_ontime": 0,
                    "unpaid": 0,
                    "invalid_dates": 0,
                }

            paid_str = r["paid_date"]
            if not paid_str:
                unpaid_invoices_count += 1
                cohort_data[c_val]["unpaid"] += 1
                continue

            paid_invoices_count += 1
            iss_dt = self._parse_date(r["issued_date"])
            due_dt = self._parse_date(r["due_date"])
            paid_dt = self._parse_date(paid_str)

            # Check for date inversion anomaly: paid_date < issued_date
            if paid_dt < iss_dt:
                invalid_dates_count += 1
                cohort_data[c_val]["invalid_dates"] += 1
                continue

            days_ttp = (paid_dt - iss_dt).days
            days_dpd = (paid_dt - due_dt).days

            cohort_data[c_val]["days_to_pay"].append(days_ttp)
            cohort_data[c_val]["days_past_due"].append(days_dpd)

            if paid_dt > due_dt:
                cohort_data[c_val]["paid_late"] += 1
            else:
                cohort_data[c_val]["paid_ontime"] += 1

        cohort_models: List[CohortPaymentSpeed] = []
        breakdown: List[Dict[str, Any]] = []

        for c_val, data in sorted(cohort_data.items()):
            valid_ttp = data["days_to_pay"]
            valid_dpd = data["days_past_due"]
            n_paid = len(valid_ttp)

            mean_ttp = round(statistics.mean(valid_ttp), 2) if n_paid > 0 else None
            med_ttp = round(float(statistics.median(valid_ttp)), 2) if n_paid > 0 else None
            mean_dpd = round(statistics.mean(valid_dpd), 2) if n_paid > 0 else None
            med_dpd = round(float(statistics.median(valid_dpd)), 2) if n_paid > 0 else None

            late_cnt = data["paid_late"]
            ontime_cnt = data["paid_ontime"]
            late_rate = round((late_cnt / n_paid) * 100.0, 2) if n_paid > 0 else None

            c_model = CohortPaymentSpeed(
                dimension_value=c_val,
                paid_invoices_count=n_paid,
                mean_days_to_pay=mean_ttp,
                median_days_to_pay=med_ttp,
                mean_days_past_due=mean_dpd,
                median_days_past_due=med_dpd,
                paid_late_count=late_cnt,
                paid_on_time_count=ontime_cnt,
                late_payment_rate_pct=late_rate,
                unpaid_invoices_count=data["unpaid"],
                insufficient_data=(n_paid < 10),
            )
            cohort_models.append(c_model)
            breakdown.append(c_model.model_dump())

        # Determine slowest cohort by highest median days to pay
        evaluable_cohorts = [c for c in cohort_models if c.median_days_to_pay is not None]
        slowest = max(evaluable_cohorts, key=lambda c: (c.median_days_to_pay or 0, c.mean_days_to_pay or 0)) if evaluable_cohorts else None

        summary_model = PaymentSpeedSummary(
            dimension=dim,
            slowest_cohort=slowest.dimension_value if slowest else None,
            slowest_cohort_mean_days_to_pay=slowest.mean_days_to_pay if slowest else None,
            slowest_cohort_median_days_to_pay=slowest.median_days_to_pay if slowest else None,
            slowest_cohort_mean_days_past_due=slowest.mean_days_past_due if slowest else None,
            slowest_cohort_median_days_past_due=slowest.median_days_past_due if slowest else None,
            total_paid_invoices=paid_invoices_count - invalid_dates_count,
            total_unpaid_invoices=unpaid_invoices_count,
            invalid_payment_dates_excluded_count=invalid_dates_count,
            cohorts=cohort_models,
        )

        data_quality_notes = [
            "Payment turnaround (Days to Pay) calculated strictly for paid invoices with valid date chronologies (paid_date >= issued_date).",
        ]
        if invalid_dates_count > 0:
            data_quality_notes.append(
                f"{invalid_dates_count} invoice(s) had paid_date preceding issued_date; excluded from turnaround statistics."
            )

        metadata = MetricMetadata(
            metric_name=f"Payment Turnaround & Delinquency by {dim.capitalize()}",
            category=MetricCategory.PAYMENTS,
            definition="Elapsed calendar days between invoice issuance and payment (Days to Pay) and delinquency past due date.",
            formula="Days to Pay = paid_date - issued_date (where paid_date >= issued_date)",
            time_period="All Invoices",
            currency=currency.upper() if currency else "ALL (Segregated)",
            filters_applied={"dimension": dim, "currency": currency},
            supporting_records_count=total_invoices,
            sample_size_evaluable=paid_invoices_count - invalid_dates_count,
            records_missing_data_count=unpaid_invoices_count,
            records_excluded_anomalies_count=invalid_dates_count,
            data_quality_notes=data_quality_notes,
        )

        return MetricResult(
            metadata=metadata,
            summary=summary_model.model_dump(),
            breakdown=breakdown,
        )

    def get_outstanding_receivables(
        self,
        as_of_date: Optional[date] = None,
        dimension: str = "segment",
    ) -> MetricResult:
        """Calculate accounts receivable aging as of a specific date, distinguishing current unpaid vs overdue.
        
        If as_of_date is omitted, defaults to 2026-09-30 (end of data period).
        """
        eval_date = as_of_date or date(2026, 9, 30)
        eval_str = eval_date.strftime("%Y-%m-%d")

        sql = """
            SELECT 
                i.invoice_id,
                i.issued_date,
                i.due_date,
                i.paid_date,
                i.amount,
                d.currency,
                d.segment,
                d.region
            FROM invoices i
            JOIN deals d ON i.deal_id = d.deal_id
        """
        cur = self.conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()

        total_invoices = len(rows)
        paid_count = 0
        unpaid_count = 0
        current_unpaid_count = 0
        overdue_unpaid_count = 0

        unpaid_by_currency: Dict[str, float] = {}
        current_by_currency: Dict[str, float] = {}
        overdue_by_currency: Dict[str, float] = {}

        cohort_aging: Dict[str, Dict[str, Any]] = {}

        for r in rows:
            c_val = str(r[dimension]) if r[dimension] is not None else "Unknown"
            if c_val not in cohort_aging:
                cohort_aging[c_val] = {
                    "unpaid_count": 0,
                    "current_unpaid_count": 0,
                    "overdue_unpaid_count": 0,
                    "unpaid_amounts": {},
                }

            paid_str = r["paid_date"]
            curr = str(r["currency"])
            amt = float(r["amount"])

            if paid_str is not None:
                paid_count += 1
                continue

            # Unpaid invoice
            unpaid_count += 1
            cohort_aging[c_val]["unpaid_count"] += 1
            unpaid_by_currency[curr] = round(unpaid_by_currency.get(curr, 0.0) + amt, 2)
            cohort_aging[c_val]["unpaid_amounts"][curr] = round(cohort_aging[c_val]["unpaid_amounts"].get(curr, 0.0) + amt, 2)

            due_dt = self._parse_date(r["due_date"])
            if due_dt < eval_date:
                overdue_unpaid_count += 1
                cohort_aging[c_val]["overdue_unpaid_count"] += 1
                overdue_by_currency[curr] = round(overdue_by_currency.get(curr, 0.0) + amt, 2)
            else:
                current_unpaid_count += 1
                cohort_aging[c_val]["current_unpaid_count"] += 1
                current_by_currency[curr] = round(current_by_currency.get(curr, 0.0) + amt, 2)

        summary_model = ReceivablesSummary(
            as_of_date=eval_date,
            total_invoices_count=total_invoices,
            paid_invoices_count=paid_count,
            unpaid_invoices_count=unpaid_count,
            current_unpaid_invoices_count=current_unpaid_count,
            overdue_invoices_count=overdue_unpaid_count,
            unpaid_amount_by_currency=unpaid_by_currency,
            current_unpaid_amount_by_currency=current_by_currency,
            overdue_amount_by_currency=overdue_by_currency,
        )

        metadata = MetricMetadata(
            metric_name="Outstanding Receivables & Overdue Exposure",
            category=MetricCategory.PAYMENTS,
            definition=f"Unpaid invoices and overdue balance evaluated as of {eval_str}.",
            formula="Overdue if paid_date IS NULL AND due_date < as_of_date",
            time_period=f"As of {eval_str}",
            filters_applied={"as_of_date": eval_str, "dimension": dimension},
            supporting_records_count=total_invoices,
            sample_size_evaluable=total_invoices,
            records_missing_data_count=0,
            data_quality_notes=[
                f"Evaluation anchor date is {eval_str}. Unpaid invoices with due_date >= as_of_date are classified as Current within terms, not Overdue."
            ],
        )

        breakdown = [
            {"cohort": k, **v}
            for k, v in cohort_aging.items()
        ]

        # Use model_dump with mode='json' or convert date to str for JSON serialization
        summary_dict = summary_model.model_dump(mode="json")

        return MetricResult(
            metadata=metadata,
            summary=summary_dict,
            breakdown=breakdown,
        )


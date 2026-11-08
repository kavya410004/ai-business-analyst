"""Pydantic data models for analytics service results, metadata envelopes, and domain types.

Conforms strictly to the Business Metrics & Definitions Catalogue in docs/metrics-definitions.md.
"""

from datetime import date
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class MetricCategory(str, Enum):
    """Four official metric categories defined in docs/metrics-definitions.md."""
    REVENUE = "Revenue and commercial performance"
    SALES = "Sales effectiveness"
    PAYMENTS = "Payment and collections"
    OVERVIEW = "Business overview and supporting indicators"


class RevenueType(str, Enum):
    """Commercial revenue/booking metric classifications."""
    CLOSED_WON_BOOKINGS = "closed_won_bookings"
    INVOICED_AMOUNT = "invoiced_amount"
    COLLECTIONS_PROXY = "collections_proxy"


class MetricMetadata(BaseModel):
    """Standard metadata envelope attached to all analytics results.
    
    Guarantees full explainability, audit trail, sample size transparency, and data quality tracking.
    """
    metric_name: str
    category: MetricCategory
    definition: str
    formula: str
    time_period: Optional[str] = None
    currency: Optional[str] = None
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    supporting_records_count: int = Field(ge=0, description="Total records in scope")
    sample_size_evaluable: int = Field(ge=0, description="Records with valid complete data evaluated")
    records_missing_data_count: int = Field(default=0, ge=0, description="Records excluded due to missing attributes")
    records_excluded_anomalies_count: int = Field(default=0, ge=0, description="Records excluded due to date anomalies")
    insufficient_data_warning: bool = Field(default=False, description="True if evaluable sample size < 10")
    data_quality_notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def evaluate_sample_size_and_quality(self) -> "MetricMetadata":
        """Strictly recalculate sample size warning and format quality advisories."""
        # Fix (1): Strictly recalculate as True or False based on sample_size_evaluable < 10
        self.insufficient_data_warning = (self.sample_size_evaluable < 10)
        
        insufficient_prefix = "Insufficient sample size (N="
        if self.insufficient_data_warning:
            advisory = f"Insufficient sample size (N={self.sample_size_evaluable} < 10); statistical variance is elevated."
            if not any(note.startswith(insufficient_prefix) for note in self.data_quality_notes):
                self.data_quality_notes.append(advisory)
        else:
            # Purge any stale advisory note if sample size is sufficient (>= 10)
            self.data_quality_notes = [
                note for note in self.data_quality_notes
                if not note.startswith(insufficient_prefix)
            ]

        # Missing data tracking
        missing_suffix = "record(s) excluded due to missing attributes."
        if self.records_missing_data_count > 0:
            missing_note = f"{self.records_missing_data_count} record(s) excluded due to missing attributes."
            if not any(note.endswith(missing_suffix) for note in self.data_quality_notes):
                self.data_quality_notes.append(missing_note)

        # Date anomaly tracking (e.g. paid_date < issued_date)
        anomaly_suffix = "record(s) excluded due to invalid date chronologies."
        if self.records_excluded_anomalies_count > 0:
            anomaly_note = f"{self.records_excluded_anomalies_count} record(s) excluded due to invalid date chronologies."
            if not any(note.endswith(anomaly_suffix) for note in self.data_quality_notes):
                self.data_quality_notes.append(anomaly_note)

        return self


class MetricResult(BaseModel):
    """Universal return envelope for all analytics functions.
    
    Contains the metadata audit envelope, a primary summary object,
    and structured cohort/row breakdown records.
    """
    metadata: MetricMetadata
    summary: Dict[str, Any] = Field(default_factory=dict)
    breakdown: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Specific Domain Breakdown Models (for strong typing & serialization)
# ---------------------------------------------------------------------------

class CurrencyMetricSummary(BaseModel):
    """Metric values strictly segregated by currency (never aggregated without FX rate)."""
    currency: str
    current_value: float
    previous_value: Optional[float] = None
    change_value: Optional[float] = None
    growth_pct: Optional[float] = None
    current_count: int = Field(ge=0, description="Count of current records")
    previous_count: Optional[int] = Field(default=None, ge=0, description="Count of prior period records")


class QuarterlyRevenueComparisonSummary(BaseModel):
    """Structured summary for Question 1: QoQ Revenue Comparison."""
    current_quarter: str
    previous_quarter: str
    revenue_type: str
    by_currency: Dict[str, CurrencyMetricSummary]


class CohortWinRate(BaseModel):
    """Win rate breakdown for a specific dimension cohort (region, segment, or owner).
    
    When closed_count == 0, rates are Optional (None) rather than misleading zeros.
    """
    dimension_value: str
    won_count: int = Field(ge=0)
    lost_count: int = Field(ge=0)
    closed_count: int = Field(ge=0)
    win_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    won_amount: Optional[float] = None
    lost_amount: Optional[float] = None
    win_rate_value_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    currency: Optional[str] = None
    insufficient_data: bool = False


class WinRateSummary(BaseModel):
    """Structured summary for Question 2: Win Rate by Dimension."""
    dimension: str
    overall_win_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    lowest_win_rate_cohort: Optional[str] = None
    lowest_win_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    highest_win_rate_cohort: Optional[str] = None
    highest_win_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    total_closed_deals: int = Field(ge=0)
    cohorts: List[CohortWinRate]


class CohortShiftShare(BaseModel):
    """Shift-share decomposition details for an individual cohort using two-component Kitagawa formula."""
    cohort_name: str
    base_deal_count: int = Field(ge=0)
    base_deal_share_pct: float
    base_win_rate_pct: Optional[float] = None
    target_deal_count: int = Field(ge=0)
    target_deal_share_pct: float
    target_win_rate_pct: Optional[float] = None
    rate_effect_pct_points: float
    mix_effect_pct_points: float


class ShiftShareDecomposition(BaseModel):
    """Structured summary for Question 3: Two-Component Kitagawa Win Rate Decomposition."""
    base_period: str
    target_period: str
    dimension: str
    base_overall_win_rate_pct: Optional[float] = None
    target_overall_win_rate_pct: Optional[float] = None
    total_change_pct_points: Optional[float] = None
    rate_effect_pct_points: float
    mix_effect_pct_points: float
    primary_driver: str
    cohort_details: List[CohortShiftShare]


class CohortPaymentSpeed(BaseModel):
    """Payment turnaround and delinquency metrics for a customer segment or region.
    
    When paid_invoices_count == 0, turnaround metrics are Optional (None) rather than 0.
    """
    dimension_value: str
    paid_invoices_count: int = Field(ge=0)
    mean_days_to_pay: Optional[float] = None
    median_days_to_pay: Optional[float] = None
    mean_days_past_due: Optional[float] = None
    median_days_past_due: Optional[float] = None
    paid_late_count: int = Field(default=0, ge=0)
    paid_on_time_count: int = Field(default=0, ge=0)
    late_payment_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    unpaid_invoices_count: int = Field(default=0, ge=0)
    overdue_invoices_count: Optional[int] = Field(default=None, ge=0)
    insufficient_data: bool = False


class PaymentSpeedSummary(BaseModel):
    """Structured summary for Question 4: Payment Turnaround by Dimension.
    
    Uses slowest_cohort rather than slowest_segment to support arbitrary dimensions.
    """
    dimension: str
    slowest_cohort: Optional[str] = None
    slowest_cohort_mean_days_to_pay: Optional[float] = None
    slowest_cohort_median_days_to_pay: Optional[float] = None
    slowest_cohort_mean_days_past_due: Optional[float] = None
    slowest_cohort_median_days_past_due: Optional[float] = None
    total_paid_invoices: int = Field(ge=0)
    total_unpaid_invoices: int = Field(ge=0)
    invalid_payment_dates_excluded_count: int = Field(default=0, ge=0)
    cohorts: List[CohortPaymentSpeed]


class ReceivablesSummary(BaseModel):
    """Accounts receivable aging and open invoice exposure as of a specific evaluation date.
    
    Strictly distinguishes between unpaid-within-terms and unpaid-overdue.
    as_of_date is typed as a Python date.
    """
    as_of_date: date
    total_invoices_count: int = Field(ge=0)
    paid_invoices_count: int = Field(ge=0)
    unpaid_invoices_count: int = Field(ge=0)
    current_unpaid_invoices_count: int = Field(ge=0, description="Unpaid with due_date >= as_of_date")
    overdue_invoices_count: int = Field(ge=0, description="Unpaid with due_date < as_of_date")
    unpaid_amount_by_currency: Dict[str, float] = Field(default_factory=dict)
    current_unpaid_amount_by_currency: Dict[str, float] = Field(default_factory=dict)
    overdue_amount_by_currency: Dict[str, float] = Field(default_factory=dict)


class ExecutiveScorecard(BaseModel):
    """Structured summary for Question 5: Executive Business Health Scorecard."""
    evaluation_quarter: str
    as_of_date: date
    commercial_growth: Dict[str, Any]
    sales_efficiency: Dict[str, Any]
    pipeline_health: Dict[str, Any]
    collection_efficiency: Dict[str, Any]
    data_quality_summary: Dict[str, Any]

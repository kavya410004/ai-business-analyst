"""Unit tests for analytics Pydantic data models."""

import unittest
from datetime import date
from pydantic import ValidationError

from src.analytics.models import (
    CohortPaymentSpeed,
    CohortShiftShare,
    CohortWinRate,
    CurrencyMetricSummary,
    ExecutiveScorecard,
    MetricCategory,
    MetricMetadata,
    MetricResult,
    PaymentSpeedSummary,
    QuarterlyRevenueComparisonSummary,
    ReceivablesSummary,
    RevenueType,
    ShiftShareDecomposition,
    WinRateSummary,
)


class TestAnalyticsModels(unittest.TestCase):
    """Test validation, constraints, and serialization of analytics models."""

    def test_metric_metadata_valid(self):
        meta = MetricMetadata(
            metric_name="Closed-Won Bookings",
            category=MetricCategory.REVENUE,
            definition="Total contracted deal value",
            formula="SUM(amount) WHERE stage = 'won'",
            time_period="2026Q3",
            currency="USD",
            filters_applied={"region": "North"},
            supporting_records_count=100,
            sample_size_evaluable=98,
            records_missing_data_count=2,
        )
        self.assertEqual(meta.metric_name, "Closed-Won Bookings")
        self.assertEqual(meta.category, MetricCategory.REVENUE)
        self.assertEqual(meta.supporting_records_count, 100)
        self.assertFalse(meta.insufficient_data_warning)
        self.assertTrue(any("2 record(s) excluded" in note for note in meta.data_quality_notes))

    def test_metric_metadata_recalculated_both_true_and_false(self):
        """Fix (1): insufficient_data_warning is recalculated strictly on validation."""
        # Case A: Sample size < 10 with explicit False passed -> must recalculate to True
        meta_small = MetricMetadata(
            metric_name="INR Quarterly Bookings",
            category=MetricCategory.REVENUE,
            definition="Test definition",
            formula="N/A",
            supporting_records_count=3,
            sample_size_evaluable=3,
            insufficient_data_warning=False,  # Explicitly passed False
        )
        self.assertTrue(meta_small.insufficient_data_warning)
        self.assertTrue(any("Insufficient sample size (N=3 < 10)" in note for note in meta_small.data_quality_notes))

        # Case B: Sample size >= 10 with explicit True passed -> must recalculate to False
        meta_large = MetricMetadata(
            metric_name="USD Quarterly Bookings",
            category=MetricCategory.REVENUE,
            definition="Test definition",
            formula="N/A",
            supporting_records_count=100,
            sample_size_evaluable=95,
            insufficient_data_warning=True,  # Explicitly passed True when sample is sufficient
            data_quality_notes=["Insufficient sample size (N=5 < 10); statistical variance is elevated."],
        )
        self.assertFalse(meta_large.insufficient_data_warning)
        # Stale note must also be purged
        self.assertFalse(any("Insufficient sample size" in note for note in meta_large.data_quality_notes))

    def test_non_negative_count_constraints(self):
        """Fix (2): All count fields enforce ge=0."""
        # CurrencyMetricSummary current_count < 0
        with self.assertRaises(ValidationError):
            CurrencyMetricSummary(
                currency="USD",
                current_value=100.0,
                current_count=-1,
            )

        # CurrencyMetricSummary previous_count < 0
        with self.assertRaises(ValidationError):
            CurrencyMetricSummary(
                currency="USD",
                current_value=100.0,
                current_count=10,
                previous_count=-2,
            )

        # CohortShiftShare base_deal_count < 0
        with self.assertRaises(ValidationError):
            CohortShiftShare(
                cohort_name="Enterprise",
                base_deal_count=-5,
                base_deal_share_pct=10.0,
                target_deal_count=20,
                target_deal_share_pct=20.0,
                rate_effect_pct_points=0.0,
                mix_effect_pct_points=0.0,
            )

    def test_payment_speed_summary_slowest_cohort(self):
        """Fix (3): Rename slowest_segment fields to slowest_cohort."""
        summary = PaymentSpeedSummary(
            dimension="region",
            slowest_cohort="East",
            slowest_cohort_mean_days_to_pay=45.2,
            slowest_cohort_median_days_to_pay=44.0,
            slowest_cohort_mean_days_past_due=15.1,
            slowest_cohort_median_days_past_due=14.0,
            total_paid_invoices=279,
            total_unpaid_invoices=29,
            cohorts=[],
        )
        self.assertEqual(summary.slowest_cohort, "East")
        self.assertEqual(summary.slowest_cohort_median_days_to_pay, 44.0)

    def test_as_of_date_typed_as_python_date(self):
        """Fix (4): as_of_date is typed as a Python date object."""
        # Initializing with datetime.date
        summary = ReceivablesSummary(
            as_of_date=date(2026, 9, 30),
            total_invoices_count=308,
            paid_invoices_count=279,
            unpaid_invoices_count=29,
            current_unpaid_invoices_count=10,
            overdue_invoices_count=19,
        )
        self.assertIsInstance(summary.as_of_date, date)
        self.assertEqual(summary.as_of_date, date(2026, 9, 30))

        # Initializing with ISO string (Pydantic coerces to date)
        summary_from_str = ReceivablesSummary(
            as_of_date="2026-09-30",
            total_invoices_count=308,
            paid_invoices_count=279,
            unpaid_invoices_count=29,
            current_unpaid_invoices_count=10,
            overdue_invoices_count=19,
        )
        self.assertIsInstance(summary_from_str.as_of_date, date)
        self.assertEqual(summary_from_str.as_of_date, date(2026, 9, 30))

        # Invalid date format fails
        with self.assertRaises(ValidationError):
            ReceivablesSummary(
                as_of_date="not-a-valid-date",
                total_invoices_count=10,
                paid_invoices_count=10,
                unpaid_invoices_count=0,
                current_unpaid_invoices_count=0,
                overdue_invoices_count=0,
            )

    def test_metric_metadata_negative_counts_fail(self):
        with self.assertRaises(ValidationError):
            MetricMetadata(
                metric_name="Invalid Test",
                category=MetricCategory.SALES,
                definition="Test",
                formula="Test",
                supporting_records_count=-5,
                sample_size_evaluable=0,
            )

    def test_undefined_metrics_optional(self):
        """When count is zero, metric must be Optional (None), NOT 0.0."""
        empty_cohort = CohortWinRate(
            dimension_value="Antarctica",
            won_count=0,
            lost_count=0,
            closed_count=0,
            win_rate_pct=None,
        )
        self.assertIsNone(empty_cohort.win_rate_pct)

        empty_payment_cohort = CohortPaymentSpeed(
            dimension_value="Government",
            paid_invoices_count=0,
            mean_days_to_pay=None,
            median_days_to_pay=None,
            mean_days_past_due=None,
            median_days_past_due=None,
        )
        self.assertIsNone(empty_payment_cohort.mean_days_to_pay)
        self.assertIsNone(empty_payment_cohort.median_days_to_pay)

    def test_two_component_kitagawa_shift_share(self):
        """Two-component Kitagawa formula fields."""
        cohort_detail = CohortShiftShare(
            cohort_name="Enterprise",
            base_deal_count=70,
            base_deal_share_pct=21.21,
            base_win_rate_pct=15.71,
            target_deal_count=166,
            target_deal_share_pct=46.11,
            target_win_rate_pct=16.87,
            rate_effect_pct_points=0.39,
            mix_effect_pct_points=-4.05,
        )
        decomp = ShiftShareDecomposition(
            base_period="2026Q2",
            target_period="2026Q3",
            dimension="segment",
            base_overall_win_rate_pct=32.73,
            target_overall_win_rate_pct=27.78,
            total_change_pct_points=-4.95,
            rate_effect_pct_points=0.65,
            mix_effect_pct_points=-5.60,
            primary_driver="Pipeline Mix Shift (Composition Effect)",
            cohort_details=[cohort_detail],
        )
        self.assertEqual(decomp.primary_driver, "Pipeline Mix Shift (Composition Effect)")
        self.assertAlmostEqual(decomp.rate_effect_pct_points + decomp.mix_effect_pct_points, -4.95, places=2)

    def test_revenue_type_enum(self):
        self.assertEqual(RevenueType.COLLECTIONS_PROXY.value, "collections_proxy")
        self.assertEqual(RevenueType.CLOSED_WON_BOOKINGS.value, "closed_won_bookings")
        self.assertEqual(RevenueType.INVOICED_AMOUNT.value, "invoiced_amount")


if __name__ == "__main__":
    unittest.main()

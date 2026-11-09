"""Comprehensive integration tests for all four domain analytics services.

Verifies mathematical correctness, currency separation, missing data handling,
and exact answers to the 5 assignment questions against SQLite crm.db.
"""

import sqlite3
import unittest
from datetime import date
from pathlib import Path

from src.db.connection import get_connection
from src.analytics import (
    ExecutiveOverviewService,
    PaymentAnalyticsService,
    RevenueAnalyticsService,
    RevenueType,
    SalesEffectivenessService,
)


class TestAnalyticsServices(unittest.TestCase):
    """End-to-end tests for domain analytics services on local crm.db."""

    @classmethod
    def setUpClass(cls):
        cls.conn = get_connection()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    # -----------------------------------------------------------------------
    # Question 1: Total Revenue Last Quarter vs Quarter Before
    # -----------------------------------------------------------------------
    def test_question_1_quarterly_revenue_comparison(self):
        """Verify Q1: Total revenue last quarter (Q3 2026) vs quarter before (Q2 2026)."""
        service = RevenueAnalyticsService(self.conn)
        result = service.compare_quarterly_revenue(
            current_quarter="2026Q3",
            previous_quarter="2026Q2",
            revenue_type=RevenueType.CLOSED_WON_BOOKINGS,
        )

        # Check metadata
        self.assertEqual(result.metadata.metric_name, "Quarterly Comparison: Closed-Won Bookings")
        self.assertEqual(result.metadata.time_period, "2026Q2 vs 2026Q3")
        self.assertFalse(result.metadata.insufficient_data_warning)

        # Check currency-segregated summary
        by_curr = result.summary["by_currency"]
        self.assertIn("USD", by_curr)
        self.assertIn("INR", by_curr)

        # USD Bookings: Q2 = $3,193,100; Q3 = $5,619,100; Growth = +75.98%
        usd = by_curr["USD"]
        self.assertEqual(usd["current_value"], 5619100.0)
        self.assertEqual(usd["previous_value"], 3193100.0)
        self.assertEqual(usd["change_value"], 2426000.0)
        self.assertEqual(usd["growth_pct"], 75.98)
        self.assertEqual(usd["current_count"], 94)  # 92 with amount + 2 missing amount
        self.assertEqual(usd["previous_count"], 104)  # 101 with amount + 3 missing amount

        # INR Bookings: Q2 = ₹8,640,300; Q3 = ₹26,460,400; Growth = +206.24%
        inr = by_curr["INR"]
        self.assertEqual(inr["current_value"], 26460400.0)
        self.assertEqual(inr["previous_value"], 8640300.0)
        self.assertEqual(inr["change_value"], 17820100.0)
        self.assertEqual(inr["growth_pct"], 206.24)
        self.assertEqual(inr["current_count"], 6)

        # Missing data notes tracking
        self.assertTrue(any("missing" in note.lower() for note in result.metadata.data_quality_notes))

    def test_invoiced_amount_comparison(self):
        """Verify billings / invoiced amount comparison."""
        service = RevenueAnalyticsService(self.conn)
        result = service.compare_quarterly_revenue(
            current_quarter="2026Q3",
            previous_quarter="2026Q2",
            revenue_type=RevenueType.INVOICED_AMOUNT,
        )
        by_curr = result.summary["by_currency"]
        self.assertIn("USD", by_curr)
        self.assertIn("INR", by_curr)
        self.assertEqual(by_curr["USD"]["current_value"], 5505400.0)
        self.assertEqual(by_curr["USD"]["previous_value"], 3216600.0)
        self.assertEqual(by_curr["USD"]["growth_pct"], 71.16)

    # -----------------------------------------------------------------------
    # Question 2: Which Region Has the Lowest Win Rate?
    # -----------------------------------------------------------------------
    def test_question_2_lowest_win_rate_region(self):
        """Verify Q2: Which region has the lowest win rate? (North at 19.51%)."""
        service = SalesEffectivenessService(self.conn)
        result = service.get_win_rates(dimension="region")

        summary = result.summary
        self.assertEqual(summary["dimension"], "region")
        self.assertEqual(summary["lowest_win_rate_cohort"], "North")
        self.assertEqual(summary["lowest_win_rate_pct"], 19.51)

        # Check ranking across all four regions
        cohorts = {c["dimension_value"]: c for c in summary["cohorts"]}
        self.assertEqual(cohorts["North"]["win_rate_pct"], 19.51)
        self.assertEqual(cohorts["North"]["won_count"], 48)
        self.assertEqual(cohorts["North"]["closed_count"], 246)

        self.assertEqual(cohorts["East"]["win_rate_pct"], 31.93)
        self.assertEqual(cohorts["South"]["win_rate_pct"], 35.12)
        self.assertEqual(cohorts["West"]["win_rate_pct"], 37.50)

        # Open deals must be excluded from denominator (total closed = 990 deals)
        self.assertEqual(summary["total_closed_deals"], 990)

    # -----------------------------------------------------------------------
    # Question 3: Why Did Win Rate Drop in Q3?
    # -----------------------------------------------------------------------
    def test_question_3_win_rate_change_diagnostics(self):
        """Verify Q3: Two-component Kitagawa shift-share decomposition by segment."""
        service = SalesEffectivenessService(self.conn)
        result = service.diagnose_win_rate_change(
            base_quarter="2026Q2",
            target_quarter="2026Q3",
            dimension="segment",
        )

        summary = result.summary
        self.assertEqual(summary["base_period"], "2026Q2")
        self.assertEqual(summary["target_period"], "2026Q3")
        self.assertEqual(summary["base_overall_win_rate_pct"], 32.73)
        self.assertEqual(summary["target_overall_win_rate_pct"], 27.78)
        self.assertEqual(summary["total_change_pct_points"], -4.95)

        # Primary driver is Pipeline Mix Shift (Composition Effect)
        self.assertEqual(summary["primary_driver"], "Pipeline Mix Shift (Composition Effect)")

        # Two-component identity: Rate Effect (+1.01 pp) + Mix Effect (-5.96 pp) = -4.95 pp
        rate_eff = summary["rate_effect_pct_points"]
        mix_eff = summary["mix_effect_pct_points"]
        self.assertEqual(rate_eff, 1.01)
        self.assertEqual(mix_eff, -5.96)
        self.assertAlmostEqual(rate_eff + mix_eff, -4.95, places=2)

        # Check cohort surge: Enterprise volume surged from 70 to 166 deals
        details = {c["cohort_name"]: c for c in summary["cohort_details"]}
        self.assertEqual(details["Enterprise"]["base_deal_count"], 70)
        self.assertEqual(details["Enterprise"]["target_deal_count"], 166)
        self.assertEqual(details["Enterprise"]["target_deal_share_pct"], 46.11)

    # -----------------------------------------------------------------------
    # Question 4: Which Segment Pays Us Slowest?
    # -----------------------------------------------------------------------
    def test_question_4_slowest_paying_segment(self):
        """Verify Q4: Which segment pays slowest? (Mid-Market at 49 days median / 49.54 days mean)."""
        service = PaymentAnalyticsService(self.conn)
        result = service.get_payment_speed_by_dimension(dimension="segment")

        summary = result.summary
        self.assertEqual(summary["dimension"], "segment")
        self.assertEqual(summary["slowest_cohort"], "Mid-Market")
        self.assertEqual(summary["slowest_cohort_median_days_to_pay"], 49.0)
        self.assertEqual(summary["slowest_cohort_mean_days_to_pay"], 49.54)
        self.assertEqual(summary["slowest_cohort_median_days_past_due"], 19.0)
        self.assertEqual(summary["slowest_cohort_mean_days_past_due"], 19.54)

        # Verify exclusion of the 6 anomalous payment dates (paid_date < issued_date)
        self.assertEqual(summary["invalid_payment_dates_excluded_count"], 6)
        self.assertEqual(summary["total_paid_invoices"], 273)  # 279 total paid - 6 invalid = 273
        self.assertEqual(summary["total_unpaid_invoices"], 29)

        # Check cohorts
        cohorts = {c["dimension_value"]: c for c in summary["cohorts"]}
        self.assertEqual(cohorts["SMB"]["median_days_to_pay"], 22.0)
        self.assertEqual(cohorts["Enterprise"]["median_days_to_pay"], 34.0)
        self.assertEqual(cohorts["Mid-Market"]["median_days_to_pay"], 49.0)

    def test_receivables_aging_distinguishes_current_and_overdue(self):
        """Verify receivables aging distinguishes current unpaid from overdue unpaid."""
        service = PaymentAnalyticsService(self.conn)
        result = service.get_outstanding_receivables(as_of_date=date(2026, 9, 30))

        summary = result.summary
        self.assertEqual(summary["total_invoices_count"], 308)
        self.assertEqual(summary["paid_invoices_count"], 279)
        self.assertEqual(summary["unpaid_invoices_count"], 29)

        # Invoices with due_date < 2026-09-30 are overdue; due_date >= 2026-09-30 are current
        cur_cnt = summary["current_unpaid_invoices_count"]
        od_cnt = summary["overdue_invoices_count"]
        self.assertEqual(cur_cnt + od_cnt, 29)
        self.assertGreater(od_cnt, 0)
        self.assertGreater(cur_cnt, 0)

    # -----------------------------------------------------------------------
    # Question 5: How Are We Doing? (Executive Scorecard)
    # -----------------------------------------------------------------------
    def test_question_5_executive_scorecard(self):
        """Verify Q5: Executive Scorecard generates integrated performance snapshot."""
        service = ExecutiveOverviewService(self.conn)
        result = service.get_executive_scorecard(
            quarter="2026Q3",
            previous_quarter="2026Q2",
            as_of_date=date(2026, 9, 30),
        )

        summary = result.summary
        self.assertEqual(summary["evaluation_quarter"], "2026Q3")
        self.assertEqual(summary["as_of_date"], "2026-09-30")

        # Verify all four pillars are present
        self.assertIn("commercial_growth", summary)
        self.assertIn("sales_efficiency", summary)
        self.assertIn("pipeline_health", summary)
        self.assertIn("collection_efficiency", summary)
        self.assertIn("data_quality_summary", summary)

        # Commercial growth
        comm = summary["commercial_growth"]
        self.assertEqual(comm["closed_won_bookings"]["USD"]["growth_pct"], 75.98)
        self.assertEqual(comm["closed_won_bookings"]["INR"]["growth_pct"], 206.24)

        # Sales efficiency
        sales = summary["sales_efficiency"]
        self.assertEqual(sales["lowest_win_rate_region"], "North")
        self.assertEqual(sales["lowest_win_rate_pct"], 14.67)  # in Q3 specifically
        self.assertEqual(sales["shift_share_primary_driver"], "Pipeline Mix Shift (Composition Effect)")

        # Collection efficiency
        coll = summary["collection_efficiency"]
        self.assertEqual(coll["slowest_paying_cohort"], "Mid-Market")
        self.assertEqual(coll["slowest_cohort_median_days_to_pay"], 49.0)

    # -----------------------------------------------------------------------
    # Edge Cases & Validation Rules
    # -----------------------------------------------------------------------
    def test_invalid_quarter_raises_error(self):
        service = RevenueAnalyticsService(self.conn)
        with self.assertRaises(ValueError):
            service.get_revenue_for_period(quarter="invalid-quarter")

    def test_invalid_dimension_raises_error(self):
        service = SalesEffectivenessService(self.conn)
        with self.assertRaises(ValueError):
            service.get_win_rates(dimension="unsupported_dimension")


if __name__ == "__main__":
    unittest.main()


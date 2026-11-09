"""Analytics module: domain-oriented business analytics services and models."""

from .models import (
    MetricCategory,
    RevenueType,
    MetricMetadata,
    MetricResult,
    CurrencyMetricSummary,
    QuarterlyRevenueComparisonSummary,
    CohortWinRate,
    WinRateSummary,
    CohortShiftShare,
    ShiftShareDecomposition,
    CohortPaymentSpeed,
    PaymentSpeedSummary,
    ReceivablesSummary,
    ExecutiveScorecard,
)
from .revenue_service import RevenueAnalyticsService
from .sales_service import SalesEffectivenessService
from .payment_service import PaymentAnalyticsService
from .overview_service import ExecutiveOverviewService

__all__ = [
    "MetricCategory",
    "RevenueType",
    "MetricMetadata",
    "MetricResult",
    "CurrencyMetricSummary",
    "QuarterlyRevenueComparisonSummary",
    "CohortWinRate",
    "WinRateSummary",
    "CohortShiftShare",
    "ShiftShareDecomposition",
    "CohortPaymentSpeed",
    "PaymentSpeedSummary",
    "ReceivablesSummary",
    "ExecutiveScorecard",
    "RevenueAnalyticsService",
    "SalesEffectivenessService",
    "PaymentAnalyticsService",
    "ExecutiveOverviewService",
]

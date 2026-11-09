"""Defensive MCP tool definitions and parameter validators for analytics services.

Follows defensive programming:
- Strict validation of all inputs before passing to domain services.
- Dedicated custom exception hierarchy.
- Validation and domain errors are propagated as MCP ToolError, which the SDK converts
  to is_error=True tool results so the agent always knows a tool call failed.
- Database details are logged to stderr only; sanitised messages are returned to the agent.
- Guaranteed stdio stream safety (no prints to stdout).
"""

import logging
import re
import sqlite3
from datetime import date, datetime
from typing import Any, Dict, Optional, Set

from mcp.server.mcpserver.exceptions import ToolError

from src.analytics import (
    ExecutiveOverviewService,
    PaymentAnalyticsService,
    RevenueAnalyticsService,
    RevenueType,
    SalesEffectivenessService,
)
from src.db.connection import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal Validation Exceptions
# ---------------------------------------------------------------------------

class _ValidationError(Exception):
    """Internal validation failure.  Always converted to ToolError before escaping."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


# ---------------------------------------------------------------------------
# Defensive Input Validators
# ---------------------------------------------------------------------------

def validate_quarter(quarter_str: Any, arg_name: str = "quarter") -> str:
    """Defensively validate quarter format (e.g., '2026Q3', '2026-Q3')."""
    if not isinstance(quarter_str, str) or not quarter_str:
        raise _ValidationError(
            f"Argument '{arg_name}' must be a non-empty string, got {type(quarter_str).__name__!r}.",
            details={"arg_name": arg_name, "value": repr(quarter_str)},
        )
    val = quarter_str.strip().upper()
    if not re.match(r"^\d{4}[-_]?[Q][1-4]$", val):
        raise _ValidationError(
            f"Invalid quarter '{quarter_str}' for argument '{arg_name}'. Expected format like '2026Q3' or '2026-Q3'.",
            details={"allowed_examples": ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]},
        )
    return val


def validate_currency(currency_str: Any) -> Optional[str]:
    """Defensively validate currency against supported dataset currencies."""
    if currency_str is None or currency_str == "":
        return None
    if not isinstance(currency_str, str):
        raise _ValidationError(
            f"Argument 'currency' must be a string, got {type(currency_str).__name__!r}.",
        )
    val = currency_str.strip().upper()
    supported = {"USD", "INR"}
    if val not in supported:
        raise _ValidationError(
            f"Unsupported currency '{currency_str}'. Data supports only: {sorted(list(supported))}.",
            details={"supported_currencies": sorted(list(supported))},
        )
    return val


def validate_dimension(dimension_str: Any, allowed: Set[str], arg_name: str = "dimension") -> str:
    """Defensively validate group-by dimension against a whitelist."""
    if not isinstance(dimension_str, str) or not dimension_str:
        raise _ValidationError(
            f"Argument '{arg_name}' must be a non-empty string, got {type(dimension_str).__name__!r}.",
            details={"arg_name": arg_name, "allowed_dimensions": sorted(list(allowed))},
        )
    dim = dimension_str.strip().lower()
    if dim not in allowed:
        raise _ValidationError(
            f"Invalid dimension '{dimension_str}'. Allowed options: {sorted(list(allowed))}.",
            details={"allowed_dimensions": sorted(list(allowed))},
        )
    return dim


def validate_revenue_type(rev_type_str: Any) -> RevenueType:
    """Defensively validate and convert revenue type string to RevenueType enum."""
    if not isinstance(rev_type_str, str) or not rev_type_str:
        raise _ValidationError(
            f"Argument 'revenue_type' must be a non-empty string, got {type(rev_type_str).__name__!r}.",
        )
    val = rev_type_str.strip().lower()
    valid_types = {t.value: t for t in RevenueType}
    if val not in valid_types:
        raise _ValidationError(
            f"Invalid revenue_type '{rev_type_str}'. Allowed: {sorted(list(valid_types.keys()))}.",
            details={"allowed_types": sorted(list(valid_types.keys()))},
        )
    return valid_types[val]


def validate_iso_date(date_str: Any, arg_name: str = "as_of_date") -> Optional[date]:
    """Defensively validate ISO-8601 date string (YYYY-MM-DD)."""
    if date_str is None or date_str == "":
        return None
    if not isinstance(date_str, str):
        raise _ValidationError(
            f"Argument '{arg_name}' must be a string in YYYY-MM-DD format, got {type(date_str).__name__!r}.",
            details={"expected_format": "YYYY-MM-DD"},
        )
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise _ValidationError(
            f"Invalid date format '{date_str}' for '{arg_name}'. Expected ISO format 'YYYY-MM-DD'.",
            details={"expected_format": "YYYY-MM-DD"},
        )


def validate_segment(segment_str: Any) -> Optional[str]:
    """Defensively validate customer segment."""
    if segment_str is None or segment_str == "":
        return None
    if not isinstance(segment_str, str):
        raise _ValidationError(
            f"Argument 'segment' must be a string, got {type(segment_str).__name__!r}.",
        )
    val = segment_str.strip()
    valid_segments = {"SMB", "Mid-Market", "Enterprise"}
    # Case-insensitive match to canonical segment name
    lookup = {s.lower(): s for s in valid_segments}
    if val.lower() not in lookup:
        raise _ValidationError(
            f"Invalid customer segment '{segment_str}'. Allowed: {sorted(list(valid_segments))}.",
            details={"allowed_segments": sorted(list(valid_segments))},
        )
    return lookup[val.lower()]


def validate_region(region_str: Any) -> Optional[str]:
    """Defensively validate geographical region."""
    if region_str is None or region_str == "":
        return None
    if not isinstance(region_str, str):
        raise _ValidationError(
            f"Argument 'region' must be a string, got {type(region_str).__name__!r}.",
        )
    val = region_str.strip()
    valid_regions = {"North", "South", "East", "West"}
    lookup = {r.lower(): r for r in valid_regions}
    if val.lower() not in lookup:
        raise _ValidationError(
            f"Invalid region '{region_str}'. Allowed: {sorted(list(valid_regions))}.",
            details={"allowed_regions": sorted(list(valid_regions))},
        )
    return lookup[val.lower()]



# ---------------------------------------------------------------------------
# Error Boundary Helper
# ---------------------------------------------------------------------------

def _wrap_tool_call(tool_name: str, func, *args, **kwargs) -> Dict[str, Any]:
    """Execute a tool function, converting internal exceptions to ToolError.

    Strategy:
    - _ValidationError  → ToolError with safe, user-readable message  (SDK: is_error=True, logged at INFO)
    - sqlite3.Error     → ToolError with sanitised message; full detail logged to stderr only
    - Any other Exception → re-raised so SDK wraps it as UnexpectedToolError
                           (safe generic message to agent, full traceback to server stderr)
    """
    try:
        return func(*args, **kwargs)
    except _ValidationError as e:
        logger.info("Validation error in '%s': %s", tool_name, str(e))
        raise ToolError(str(e)) from e
    except sqlite3.Error as e:
        logger.error("Database error in '%s': %s", tool_name, str(e), exc_info=True)
        raise ToolError(
            f"A database error occurred while executing '{tool_name}'. "
            "Please check server logs for details."
        ) from e
    # All other exceptions propagate; SDK logs traceback and returns generic is_error=True message.



# ---------------------------------------------------------------------------
# MCP Tool Implementations
# ---------------------------------------------------------------------------

def get_quarterly_revenue_comparison(
    current_quarter: str = "2026Q3",
    previous_quarter: str = "2026Q2",
    revenue_type: str = "invoiced_amount",
    currency: Optional[str] = None,
    region: Optional[str] = None,
    segment: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare commercial revenue between two quarters (e.g. Q3 vs Q2 2026).

    Answers Question 1: What was total revenue last quarter, and how does it compare to the quarter before?
    Amounts are segregated by currency (USD and INR) without synthetic conversion.

    The default revenue_type is 'invoiced_amount' (billed revenue), which is the
    primary metric for the assignment's revenue question. 'closed_won_bookings' reflects
    deal bookings before invoicing; 'collections_proxy' reflects collected payments.

    Args:
        current_quarter: Evaluation quarter (e.g. '2026Q3').
        previous_quarter: Baseline comparison quarter (e.g. '2026Q2').
        revenue_type: 'invoiced_amount' (default), 'closed_won_bookings', or 'collections_proxy'.
        currency: Optional filter for 'USD' or 'INR' (returns both if None).
        region: Optional filter ('North', 'South', 'East', 'West').
        segment: Optional filter ('SMB', 'Mid-Market', 'Enterprise').
    """
    def _run():
        c_qtr = validate_quarter(current_quarter, "current_quarter")
        p_qtr = validate_quarter(previous_quarter, "previous_quarter")
        r_type = validate_revenue_type(revenue_type)
        curr = validate_currency(currency)
        reg = validate_region(region)
        seg = validate_segment(segment)

        conn = get_connection()
        try:
            service = RevenueAnalyticsService(conn)
            result = service.compare_quarterly_revenue(
                current_quarter=c_qtr,
                previous_quarter=p_qtr,
                currency=curr,
                revenue_type=r_type,
                region=reg,
                segment=seg,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("get_quarterly_revenue_comparison", _run)


def get_win_rate_analysis(
    dimension: str = "region",
    quarter: Optional[str] = None,
    currency: Optional[str] = None,
    segment: Optional[str] = None,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate opportunity win rates across cohorts for a specified dimension.

    Answers Question 2: Which region has the lowest win rate?
    Open deals are strictly excluded from the win rate denominator.

    Args:
        dimension: Group-by dimension ('region', 'segment', or 'owner').
        quarter: Optional quarter filter (e.g. '2026Q3'). All-time if None.
        currency: Optional filter ('USD' or 'INR').
        segment: Optional segment filter ('SMB', 'Mid-Market', 'Enterprise').
        region: Optional region filter ('North', 'South', 'East', 'West').
    """
    def _run():
        dim = validate_dimension(dimension, {"region", "segment", "owner"})
        qtr = validate_quarter(quarter, "quarter") if quarter else None
        curr = validate_currency(currency)
        seg = validate_segment(segment)
        reg = validate_region(region)

        conn = get_connection()
        try:
            service = SalesEffectivenessService(conn)
            result = service.get_win_rates(
                dimension=dim,
                quarter=qtr,
                currency=curr,
                segment=seg,
                region=reg,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("get_win_rate_analysis", _run)


def diagnose_win_rate_change(
    base_quarter: str = "2026Q2",
    target_quarter: str = "2026Q3",
    dimension: str = "segment",
) -> Dict[str, Any]:
    """Decompose win rate variance using the Two-Component Kitagawa Shift-Share formula.

    Answers Question 3: Why did win rate drop in Q3?
    Isolates within-cohort conversion variance (Rate Effect) from pipeline deal mix shifts (Mix Effect).

    Args:
        base_quarter: Baseline prior quarter (e.g. '2026Q2').
        target_quarter: Evaluation target quarter (e.g. '2026Q3').
        dimension: Cohort dimension ('segment', 'region', or 'owner').
    """
    def _run():
        b_qtr = validate_quarter(base_quarter, "base_quarter")
        t_qtr = validate_quarter(target_quarter, "target_quarter")
        dim = validate_dimension(dimension, {"segment", "region", "owner"})

        conn = get_connection()
        try:
            service = SalesEffectivenessService(conn)
            result = service.diagnose_win_rate_change(
                base_quarter=b_qtr,
                target_quarter=t_qtr,
                dimension=dim,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("diagnose_win_rate_change", _run)


def get_payment_speed_analysis(
    dimension: str = "segment",
    currency: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze invoice payment turnaround (Days to Pay) and delinquency (Days Past Due).

    Answers Question 4: Which segment pays us slowest?
    Excludes records with invalid chronologies (paid_date < issued_date) and reports sample sizes.

    Args:
        dimension: Group-by dimension ('segment' or 'region').
        currency: Optional filter ('USD' or 'INR').
    """
    def _run():
        dim = validate_dimension(dimension, {"segment", "region"})
        curr = validate_currency(currency)

        conn = get_connection()
        try:
            service = PaymentAnalyticsService(conn)
            result = service.get_payment_speed_by_dimension(
                dimension=dim,
                currency=curr,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("get_payment_speed_analysis", _run)


def get_outstanding_receivables(
    as_of_date: Optional[str] = "2026-09-30",
    dimension: str = "segment",
) -> Dict[str, Any]:
    """Analyze accounts receivable aging and open invoice exposure as of an anchor date.

    Strictly distinguishes current unpaid invoices within terms from overdue unpaid invoices.

    IMPORTANT – Evaluation date: The default as_of_date is '2026-09-30', which is the end
    of the most recent quarter in the dataset (2026-Q3). This is the intentional dataset
    snapshot date. When presenting results, always communicate this evaluation date to the
    user so figures are not mistaken for current-day outstanding balances.

    Args:
        as_of_date: Evaluation anchor date in ISO format 'YYYY-MM-DD'.
                    Defaults to '2026-09-30' (end of Q3 2026, the dataset snapshot date).
        dimension: Group-by dimension ('segment' or 'region').
    """
    def _run():
        eval_dt = validate_iso_date(as_of_date, "as_of_date")
        dim = validate_dimension(dimension, {"segment", "region"})

        conn = get_connection()
        try:
            service = PaymentAnalyticsService(conn)
            result = service.get_outstanding_receivables(
                as_of_date=eval_dt,
                dimension=dim,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("get_outstanding_receivables", _run)


def get_executive_scorecard(
    quarter: str = "2026Q3",
    previous_quarter: str = "2026Q2",
    as_of_date: Optional[str] = "2026-09-30",
) -> Dict[str, Any]:
    """Generate a multi-dimensional executive scorecard synthesizing company health.

    Answers Question 5: How are we doing?
    Synthesizes Commercial Growth, Sales Efficiency, Pipeline Health, and Collection Risk.

    IMPORTANT – Evaluation date: The default as_of_date is '2026-09-30', which is the
    end of Q3 2026 (the most recent complete quarter in the dataset). This is the
    intentional snapshot date for receivables evaluation. Always communicate this date
    when presenting collection risk figures.

    Args:
        quarter: Primary evaluation quarter (e.g. '2026Q3').
        previous_quarter: Comparison baseline quarter (e.g. '2026Q2').
        as_of_date: Receivables evaluation date in ISO format 'YYYY-MM-DD'.
                    Defaults to '2026-09-30' (end of Q3 2026, the dataset snapshot date).
    """
    def _run():
        qtr = validate_quarter(quarter, "quarter")
        prev_qtr = validate_quarter(previous_quarter, "previous_quarter")
        eval_dt = validate_iso_date(as_of_date, "as_of_date")

        conn = get_connection()
        try:
            service = ExecutiveOverviewService(conn)
            result = service.get_executive_scorecard(
                quarter=qtr,
                previous_quarter=prev_qtr,
                as_of_date=eval_dt,
            )
            return result.model_dump(mode="json")
        finally:
            conn.close()

    return _wrap_tool_call("get_executive_scorecard", _run)

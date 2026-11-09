"""Defensive MCP tool definitions and parameter validators for analytics services.

Follows defensive programming:
- Strict validation of all inputs before passing to domain services.
- Dedicated custom exception hierarchy.
- Graceful exception interception with structured, informative error dictionaries.
- Guaranteed stdio stream safety (no prints to stdout).
"""

import functools
import logging
import re
import sqlite3
import sys
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Set

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
# Defensive Custom Exceptions
# ---------------------------------------------------------------------------

class MCPToolError(Exception):
    """Base exception for all MCP analytics tool execution failures."""

    def __init__(self, message: str, error_code: str = "TOOL_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": True,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ToolValidationError(MCPToolError):
    """Raised when an argument fails validation checks."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="INVALID_ARGUMENT", details=details)


class ToolDatabaseError(MCPToolError):
    """Raised when database query execution fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="DATABASE_ERROR", details=details)


# ---------------------------------------------------------------------------
# Defensive Input Validators
# ---------------------------------------------------------------------------

def validate_quarter(quarter_str: str, arg_name: str = "quarter") -> str:
    """Defensively validate quarter format (e.g., '2026Q3', '2026-Q3')."""
    if not quarter_str or not isinstance(quarter_str, str):
        raise ToolValidationError(
            f"Argument '{arg_name}' must be a non-empty string.",
            details={"arg_name": arg_name, "value": quarter_str},
        )
    val = quarter_str.strip().upper()
    if not re.match(r"^\d{4}[-_]?[Q][1-4]$", val):
        raise ToolValidationError(
            f"Invalid quarter '{quarter_str}' for argument '{arg_name}'. Expected format like '2026Q3' or '2026-Q3'.",
            details={"allowed_examples": ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]},
        )
    return val


def validate_currency(currency_str: Optional[str]) -> Optional[str]:
    """Defensively validate currency against supported dataset currencies."""
    if currency_str is None or currency_str == "":
        return None
    val = currency_str.strip().upper()
    supported = {"USD", "INR"}
    if val not in supported:
        raise ToolValidationError(
            f"Unsupported currency '{currency_str}'. Data supports only: {sorted(list(supported))}.",
            details={"supported_currencies": sorted(list(supported))},
        )
    return val


def validate_dimension(dimension_str: str, allowed: Set[str], arg_name: str = "dimension") -> str:
    """Defensively validate group-by dimension against a whitelist."""
    if not dimension_str or not isinstance(dimension_str, str):
        raise ToolValidationError(
            f"Argument '{arg_name}' must be a non-empty string.",
            details={"arg_name": arg_name, "allowed_dimensions": sorted(list(allowed))},
        )
    dim = dimension_str.strip().lower()
    if dim not in allowed:
        raise ToolValidationError(
            f"Invalid dimension '{dimension_str}'. Allowed options: {sorted(list(allowed))}.",
            details={"allowed_dimensions": sorted(list(allowed))},
        )
    return dim


def validate_revenue_type(rev_type_str: str) -> RevenueType:
    """Defensively validate and convert revenue type string to RevenueType enum."""
    if not rev_type_str or not isinstance(rev_type_str, str):
        raise ToolValidationError("revenue_type must be a non-empty string.")
    val = rev_type_str.strip().lower()
    valid_types = {t.value: t for t in RevenueType}
    if val not in valid_types:
        raise ToolValidationError(
            f"Invalid revenue_type '{rev_type_str}'. Allowed: {sorted(list(valid_types.keys()))}.",
            details={"allowed_types": sorted(list(valid_types.keys()))},
        )
    return valid_types[val]


def validate_iso_date(date_str: Optional[str], arg_name: str = "as_of_date") -> Optional[date]:
    """Defensively validate ISO-8601 date string (YYYY-MM-DD)."""
    if date_str is None or date_str == "":
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ToolValidationError(
            f"Invalid date format '{date_str}' for '{arg_name}'. Expected ISO format 'YYYY-MM-DD'.",
            details={"expected_format": "YYYY-MM-DD"},
        )


def validate_segment(segment_str: Optional[str]) -> Optional[str]:
    """Defensively validate customer segment."""
    if not segment_str:
        return None
    val = segment_str.strip()
    valid_segments = {"SMB", "Mid-Market", "Enterprise"}
    # Case-insensitive match to canonical segment name
    lookup = {s.lower(): s for s in valid_segments}
    if val.lower() not in lookup:
        raise ToolValidationError(
            f"Invalid customer segment '{segment_str}'. Allowed: {sorted(list(valid_segments))}.",
            details={"allowed_segments": sorted(list(valid_segments))},
        )
    return lookup[val.lower()]


def validate_region(region_str: Optional[str]) -> Optional[str]:
    """Defensively validate geographical region."""
    if not region_str:
        return None
    val = region_str.strip()
    valid_regions = {"North", "South", "East", "West"}
    lookup = {r.lower(): r for r in valid_regions}
    if val.lower() not in lookup:
        raise ToolValidationError(
            f"Invalid region '{region_str}'. Allowed: {sorted(list(valid_regions))}.",
            details={"allowed_regions": sorted(list(valid_regions))},
        )
    return lookup[val.lower()]


# ---------------------------------------------------------------------------
# Defensive Error Boundary Decorator
# ---------------------------------------------------------------------------

def defensive_tool(func: Callable) -> Callable:
    """Decorator ensuring that all exceptions are intercepted gracefully and converted to structured payloads."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except MCPToolError as e:
            logger.warning(f"Validation/tool error in '{func.__name__}': {e.message}")
            return e.to_dict()
        except ValueError as e:
            logger.warning(f"ValueError in '{func.__name__}': {str(e)}")
            return {
                "error": True,
                "error_code": "INVALID_ARGUMENT",
                "message": str(e),
            }
        except sqlite3.Error as e:
            logger.error(f"Database error in '{func.__name__}': {str(e)}", exc_info=True)
            return {
                "error": True,
                "error_code": "DATABASE_ERROR",
                "message": f"Underlying database operation failed: {str(e)}",
            }
        except Exception as e:
            logger.critical(f"Unexpected error in '{func.__name__}': {str(e)}", exc_info=True)
            return {
                "error": True,
                "error_code": "INTERNAL_ERROR",
                "message": f"An unexpected error occurred while executing '{func.__name__}': {str(e)}",
            }

    return wrapper


# ---------------------------------------------------------------------------
# MCP Tool Implementations
# ---------------------------------------------------------------------------

@defensive_tool
def get_quarterly_revenue_comparison(
    current_quarter: str = "2026Q3",
    previous_quarter: str = "2026Q2",
    revenue_type: str = "closed_won_bookings",
    currency: Optional[str] = None,
    region: Optional[str] = None,
    segment: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare commercial performance between two quarters (e.g. Q3 vs Q2 2026).
    
    Answers Question 1: What was total revenue last quarter, and how does it compare to the quarter before?
    Amounts are segregated by currency (USD and INR) without synthetic conversion.
    
    Args:
        current_quarter: Evaluation quarter (e.g. '2026Q3').
        previous_quarter: Baseline comparison quarter (e.g. '2026Q2').
        revenue_type: 'closed_won_bookings', 'invoiced_amount', or 'collections_proxy'.
        currency: Optional filter for 'USD' or 'INR' (returns both if None).
        region: Optional filter ('North', 'South', 'East', 'West').
        segment: Optional filter ('SMB', 'Mid-Market', 'Enterprise').
    """
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


@defensive_tool
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


@defensive_tool
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


@defensive_tool
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


@defensive_tool
def get_outstanding_receivables(
    as_of_date: Optional[str] = "2026-09-30",
    dimension: str = "segment",
) -> Dict[str, Any]:
    """Analyze accounts receivable aging and open invoice exposure as of an anchor date.
    
    Strictly distinguishes current unpaid invoices within terms from overdue unpaid invoices.
    
    Args:
        as_of_date: Evaluation anchor date in ISO format 'YYYY-MM-DD' (defaults to '2026-09-30').
        dimension: Group-by dimension ('segment' or 'region').
    """
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


@defensive_tool
def get_executive_scorecard(
    quarter: str = "2026Q3",
    previous_quarter: str = "2026Q2",
    as_of_date: Optional[str] = "2026-09-30",
) -> Dict[str, Any]:
    """Generate a multi-dimensional executive scorecard synthesizing company health.
    
    Answers Question 5: How are we doing?
    Synthesizes Commercial Growth, Sales Efficiency, Pipeline Health, and Collection Risk.
    
    Args:
        quarter: Primary evaluation quarter (e.g. '2026Q3').
        previous_quarter: Comparison baseline quarter (e.g. '2026Q2').
        as_of_date: Receivables evaluation date in ISO format 'YYYY-MM-DD' (defaults to '2026-09-30').
    """
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

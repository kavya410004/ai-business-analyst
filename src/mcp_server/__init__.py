"""Python MCP Server package exposing deterministic business analytics tools over stdio."""

from .server import create_server, run_server
from .tools import (
    _ValidationError,
    get_quarterly_revenue_comparison,
    get_win_rate_analysis,
    diagnose_win_rate_change,
    get_payment_speed_analysis,
    get_outstanding_receivables,
    get_executive_scorecard,
)

__all__ = [
    "create_server",
    "run_server",
    "_ValidationError",
    "get_quarterly_revenue_comparison",
    "get_win_rate_analysis",
    "diagnose_win_rate_change",
    "get_payment_speed_analysis",
    "get_outstanding_receivables",
    "get_executive_scorecard",
]


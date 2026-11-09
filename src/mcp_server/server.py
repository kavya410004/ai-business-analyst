"""Python MCP Server exposing business analytics tools over the stdio protocol.

Complies strictly with MCP standards:
- Logging is directed strictly to sys.stderr to protect stdout protocol integrity.
- Tools provide defensive argument validation and structured error boundaries.
"""

import asyncio
import logging
import os
import sys
from typing import Optional

from mcp.server.mcpserver import MCPServer

from .tools import (
    diagnose_win_rate_change,
    get_executive_scorecard,
    get_outstanding_receivables,
    get_payment_speed_analysis,
    get_quarterly_revenue_comparison,
    get_win_rate_analysis,
)

# Configure logging strictly to sys.stderr to avoid corrupting MCP stdio JSON-RPC protocol
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level_name, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_server")


def create_server(name: str = "ai-business-analyst-mcp") -> MCPServer:
    """Create and configure the MCPServer instance with all analytics tools registered."""
    server = MCPServer(name=name, version="1.0.0")

    # Register all 6 analytics tools with descriptions matching question capabilities
    server.tool(
        name="get_quarterly_revenue_comparison",
        description=(
            "Compare commercial revenue/bookings between two quarters (e.g. Q3 vs Q2 2026). "
            "Answers: 'What was total revenue last quarter, and how does it compare to the quarter before?' "
            "Reports separate totals for USD and INR without synthetic conversion."
        ),
    )(get_quarterly_revenue_comparison)

    server.tool(
        name="get_win_rate_analysis",
        description=(
            "Analyze opportunity win rates across regions, segments, or sales owners. "
            "Answers: 'Which region has the lowest win rate?' "
            "Open deals are strictly excluded from the win rate denominator."
        ),
    )(get_win_rate_analysis)

    server.tool(
        name="diagnose_win_rate_change",
        description=(
            "Decompose period-over-period win rate changes using the Two-Component Kitagawa Shift-Share formula. "
            "Answers: 'Why did win rate drop in Q3?' "
            "Isolates sales performance changes (Rate Effect) from deal volume mix shifts (Mix Effect / Simpson's Paradox)."
        ),
    )(diagnose_win_rate_change)

    server.tool(
        name="get_payment_speed_analysis",
        description=(
            "Evaluate customer invoice turnaround (Days to Pay) and delinquency (Days Past Due). "
            "Answers: 'Which segment pays us slowest?' "
            "Calculated on valid paid records, reporting mean and median turnaround and sample sizes."
        ),
    )(get_payment_speed_analysis)

    server.tool(
        name="get_outstanding_receivables",
        description=(
            "Analyze accounts receivable aging and open invoice balance evaluated as of an anchor date. "
            "Strictly distinguishes current unpaid invoices within terms from overdue unpaid invoices."
        ),
    )(get_outstanding_receivables)

    server.tool(
        name="get_executive_scorecard",
        description=(
            "Generate an integrated multi-dimensional executive performance scorecard. "
            "Answers: 'How are we doing?' "
            "Synthesizes Commercial Growth, Sales Efficiency, Pipeline Health, and Collection Risk."
        ),
    )(get_executive_scorecard)

    logger.info("MCPServer initialized and 6 analytics tools successfully registered.")
    return server


async def run_server() -> None:
    """Run the MCP server over stdio protocol."""
    server = create_server()
    logger.info("Starting MCP server listening on stdio...")
    await server.run_stdio_async()


def main() -> None:
    """Entry point for running the MCP server."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("MCP server terminated by user.")
    except Exception as e:
        logger.critical(f"Fatal error running MCP server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

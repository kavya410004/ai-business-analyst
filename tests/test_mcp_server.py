"""Comprehensive asynchronous integration tests for the Python MCP Server.

Verifies:
1. Tool discovery (all 6 tools listed with complete schemas).
2. End-to-end tool execution solving the 5 core assignment questions.
3. Defensive error handling: invalid inputs produce is_error=True MCP results,
   never silently returning error dicts as valid analytical data.
"""

import asyncio
import json
import unittest

from mcp.server.mcpserver.exceptions import ToolError
from src.mcp_server.server import create_server
from src.mcp_server.tools import (
    _ValidationError,
    diagnose_win_rate_change,
    get_executive_scorecard,
    get_outstanding_receivables,
    get_payment_speed_analysis,
    get_quarterly_revenue_comparison,
    get_win_rate_analysis,
    validate_currency,
    validate_dimension,
    validate_iso_date,
    validate_quarter,
    validate_region,
    validate_revenue_type,
    validate_segment,
)


class TestMCPServer(unittest.IsolatedAsyncioTestCase):
    """Test suite for MCPServer tool listing, execution, and defensive error boundaries."""

    async def asyncSetUp(self):
        self.server = create_server("test-mcp-server")

    # -----------------------------------------------------------------------
    # 1. Tool Discovery Tests
    # -----------------------------------------------------------------------
    async def test_tool_discovery_lists_all_tools(self):
        """Verify that server.list_tools() advertises all 6 required analytics tools."""
        tools = await self.server.list_tools()
        tool_names = {t.name for t in tools}

        expected_tools = {
            "get_quarterly_revenue_comparison",
            "get_win_rate_analysis",
            "diagnose_win_rate_change",
            "get_payment_speed_analysis",
            "get_outstanding_receivables",
            "get_executive_scorecard",
        }
        self.assertTrue(expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}")

        # Check that descriptions are meaningful and populated
        for t in tools:
            self.assertTrue(len(t.description) > 20, f"Tool {t.name} description too short")

    # -----------------------------------------------------------------------
    # 2. End-to-End Tool Execution (Assignment Questions 1 - 5)
    # -----------------------------------------------------------------------
    async def test_tool_q1_revenue_comparison(self):
        """Verify get_quarterly_revenue_comparison returns invoiced_amount by default (primary revenue metric)."""
        call_res = await self.server.call_tool(
            "get_quarterly_revenue_comparison",
            {
                "current_quarter": "2026Q3",
                "previous_quarter": "2026Q2",
                # revenue_type omitted: default is "invoiced_amount" (primary assignment metric)
            },
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        self.assertNotIn("error", payload)
        self.assertIn("summary", payload)
        by_curr = payload["summary"]["by_currency"]

        # USD Invoiced Amount Q3: $5,505,400 (+71.16%)
        self.assertEqual(by_curr["USD"]["current_value"], 5505400.0)
        self.assertAlmostEqual(by_curr["USD"]["growth_pct"], 71.16, places=1)

    async def test_tool_q1_bookings_comparison(self):
        """Verify closed_won_bookings revenue_type works correctly and matches ground truth."""
        call_res = await self.server.call_tool(
            "get_quarterly_revenue_comparison",
            {
                "current_quarter": "2026Q3",
                "previous_quarter": "2026Q2",
                "revenue_type": "closed_won_bookings",
            },
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        self.assertNotIn("error", payload)
        by_curr = payload["summary"]["by_currency"]

        # USD Bookings Q3: $5,619,100 (+75.98%)
        self.assertEqual(by_curr["USD"]["current_value"], 5619100.0)
        self.assertEqual(by_curr["USD"]["growth_pct"], 75.98)

        # INR Bookings Q3: ₹26,460,400 (+206.24%)
        self.assertEqual(by_curr["INR"]["current_value"], 26460400.0)
        self.assertEqual(by_curr["INR"]["growth_pct"], 206.24)

    async def test_tool_q2_lowest_win_rate_region(self):
        """Verify get_win_rate_analysis via MCP call_tool."""
        call_res = await self.server.call_tool(
            "get_win_rate_analysis",
            {"dimension": "region"},
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        summary = payload["summary"]
        self.assertEqual(summary["dimension"], "region")
        self.assertEqual(summary["lowest_win_rate_cohort"], "North")
        self.assertEqual(summary["lowest_win_rate_pct"], 19.51)

    async def test_tool_q3_win_rate_diagnostics(self):
        """Verify diagnose_win_rate_change via MCP call_tool."""
        call_res = await self.server.call_tool(
            "diagnose_win_rate_change",
            {
                "base_quarter": "2026Q2",
                "target_quarter": "2026Q3",
                "dimension": "segment",
            },
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        summary = payload["summary"]
        self.assertEqual(summary["total_change_pct_points"], -4.95)
        self.assertEqual(summary["rate_effect_pct_points"], 1.01)
        self.assertEqual(summary["mix_effect_pct_points"], -5.96)
        self.assertEqual(summary["primary_driver"], "Pipeline Mix Shift (Composition Effect)")

    async def test_tool_q4_slowest_paying_segment(self):
        """Verify get_payment_speed_analysis via MCP call_tool."""
        call_res = await self.server.call_tool(
            "get_payment_speed_analysis",
            {"dimension": "segment"},
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        summary = payload["summary"]
        self.assertEqual(summary["dimension"], "segment")
        self.assertEqual(summary["slowest_cohort"], "Mid-Market")
        self.assertEqual(summary["slowest_cohort_median_days_to_pay"], 49.0)
        self.assertEqual(summary["invalid_payment_dates_excluded_count"], 6)

    async def test_tool_receivables_aging(self):
        """Verify get_outstanding_receivables via MCP call_tool."""
        call_res = await self.server.call_tool(
            "get_outstanding_receivables",
            {"as_of_date": "2026-09-30", "dimension": "segment"},
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        summary = payload["summary"]
        self.assertEqual(summary["as_of_date"], "2026-09-30")
        self.assertEqual(summary["unpaid_invoices_count"], 29)
        self.assertEqual(
            summary["current_unpaid_invoices_count"] + summary["overdue_invoices_count"],
            29,
        )

    async def test_tool_q5_executive_scorecard(self):
        """Verify get_executive_scorecard via MCP call_tool."""
        call_res = await self.server.call_tool(
            "get_executive_scorecard",
            {"quarter": "2026Q3", "previous_quarter": "2026Q2"},
        )
        self.assertFalse(call_res.is_error)
        payload = json.loads(call_res.content[0].text)

        summary = payload["summary"]
        self.assertEqual(summary["evaluation_quarter"], "2026Q3")
        self.assertIn("commercial_growth", summary)
        self.assertIn("sales_efficiency", summary)
        self.assertIn("pipeline_health", summary)
        self.assertIn("collection_efficiency", summary)

    # -----------------------------------------------------------------------
    # 3. Defensive Programming & Error Boundary Tests
    #    Invalid inputs must raise ToolError (which the MCP protocol layer converts
    #    to is_error=True). Never silently returns error metadata as valid data.
    # -----------------------------------------------------------------------
    async def test_defensive_invalid_quarter_handling(self):
        """Verify invalid quarter string raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_quarterly_revenue_comparison",
                {"current_quarter": "2026-X", "previous_quarter": "2026Q2"},
            )
        self.assertIn("Invalid quarter", str(ctx.exception))

    async def test_defensive_invalid_currency_handling(self):
        """Verify unsupported currency raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_quarterly_revenue_comparison",
                {"current_quarter": "2026Q3", "previous_quarter": "2026Q2", "currency": "EUR"},
            )
        self.assertIn("Unsupported currency", str(ctx.exception))

    async def test_defensive_invalid_dimension_handling(self):
        """Verify unsupported dimension raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_win_rate_analysis",
                {"dimension": "extraterrestrial"},
            )
        self.assertIn("Invalid dimension", str(ctx.exception))

    async def test_defensive_invalid_revenue_type(self):
        """Verify unsupported revenue_type raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_quarterly_revenue_comparison",
                {"current_quarter": "2026Q3", "previous_quarter": "2026Q2", "revenue_type": "magic_money"},
            )
        self.assertIn("Invalid revenue_type", str(ctx.exception))

    async def test_defensive_invalid_date_format(self):
        """Verify non-ISO date string raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_outstanding_receivables",
                {"as_of_date": "30/09/2026", "dimension": "segment"},
            )
        self.assertIn("Invalid date format", str(ctx.exception))

    async def test_defensive_invalid_segment_filter(self):
        """Verify invalid customer segment raises ToolError with informative message."""
        with self.assertRaises(ToolError) as ctx:
            await self.server.call_tool(
                "get_win_rate_analysis",
                {"dimension": "region", "segment": "MegaEnterprise"},
            )
        self.assertIn("Invalid customer segment", str(ctx.exception))

    # -----------------------------------------------------------------------
    # 4. Validator Type-Guard Unit Tests
    #    Non-string inputs must produce _ValidationError, not unexpected exceptions.
    # -----------------------------------------------------------------------
    def test_validate_currency_non_string_raises(self):
        """Non-string currency must raise _ValidationError, not AttributeError."""
        with self.assertRaises(_ValidationError) as ctx:
            validate_currency(123)
        self.assertIn("string", str(ctx.exception))

    def test_validate_segment_non_string_raises(self):
        """Non-string segment must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_segment(42)

    def test_validate_region_non_string_raises(self):
        """Non-string region must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_region(["North"])

    def test_validate_iso_date_non_string_raises(self):
        """Non-string as_of_date must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_iso_date(20260930, "as_of_date")

    def test_validate_quarter_non_string_raises(self):
        """Non-string quarter must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_quarter(20263, "quarter")

    def test_validate_revenue_type_non_string_raises(self):
        """Non-string revenue_type must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_revenue_type(None)

    def test_validate_dimension_non_string_raises(self):
        """Non-string dimension must raise _ValidationError."""
        with self.assertRaises(_ValidationError):
            validate_dimension(42, {"region", "segment"}, "dimension")


if __name__ == "__main__":
    unittest.main()


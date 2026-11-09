"""Comprehensive asynchronous integration tests for the Python MCP Server.

Verifies:
1. Tool discovery (all 6 tools listed with complete schemas).
2. End-to-end tool execution solving the 5 core assignment questions.
3. Defensive error handling (graceful handling of invalid inputs without crashing).
"""

import asyncio
import json
import unittest

from src.mcp_server.server import create_server
from src.mcp_server.tools import (
    diagnose_win_rate_change,
    get_executive_scorecard,
    get_outstanding_receivables,
    get_payment_speed_analysis,
    get_quarterly_revenue_comparison,
    get_win_rate_analysis,
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
        """Verify get_quarterly_revenue_comparison via MCP call_tool."""
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
        self.assertIn("summary", payload)
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
    # -----------------------------------------------------------------------
    def test_defensive_invalid_quarter_handling(self):
        """Verify invalid quarter string returns structured error payload."""
        res = get_quarterly_revenue_comparison(current_quarter="2026-X")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Invalid quarter", res.get("message", ""))

    def test_defensive_invalid_currency_handling(self):
        """Verify unsupported currency returns structured error payload."""
        res = get_quarterly_revenue_comparison(currency="EUR")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Unsupported currency", res.get("message", ""))

    def test_defensive_invalid_dimension_handling(self):
        """Verify unsupported dimension returns structured error payload."""
        res = get_win_rate_analysis(dimension="extraterrestrial")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Invalid dimension", res.get("message", ""))

    def test_defensive_invalid_revenue_type(self):
        """Verify unsupported revenue_type returns structured error payload."""
        res = get_quarterly_revenue_comparison(revenue_type="magic_money")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Invalid revenue_type", res.get("message", ""))

    def test_defensive_invalid_date_format(self):
        """Verify non-ISO date string returns structured error payload."""
        res = get_outstanding_receivables(as_of_date="30/09/2026")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Invalid date format", res.get("message", ""))

    def test_defensive_invalid_segment_filter(self):
        """Verify invalid customer segment returns structured error payload."""
        res = get_win_rate_analysis(segment="MegaEnterprise")
        self.assertTrue(res.get("error"))
        self.assertEqual(res.get("error_code"), "INVALID_ARGUMENT")
        self.assertIn("Invalid customer segment", res.get("message", ""))


if __name__ == "__main__":
    unittest.main()

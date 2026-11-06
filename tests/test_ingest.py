"""Unit and integration tests for data ingestion, schema constraints, and normalization."""

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.db.connection import get_connection, init_db
from src.db.ingest import ingest_data, normalize_date_str


class TestDateNormalization(unittest.TestCase):
    """Test date parsing and regex normalization."""

    def test_iso_format_preserved(self):
        self.assertEqual(normalize_date_str("2026-01-04"), "2026-01-04")
        self.assertEqual(normalize_date_str("2025-12-31"), "2025-12-31")

    def test_dd_mm_yyyy_normalized_to_iso(self):
        self.assertEqual(normalize_date_str("08-01-2026"), "2026-01-08")
        self.assertEqual(normalize_date_str("20-06-2026"), "2026-06-20")
        self.assertEqual(normalize_date_str("31-03-2026"), "2026-03-31")

    def test_empty_and_none_handling(self):
        self.assertIsNone(normalize_date_str(None))
        self.assertIsNone(normalize_date_str(""))
        self.assertIsNone(normalize_date_str("   "))

    def test_invalid_format_raises_error(self):
        with self.assertRaises(ValueError):
            normalize_date_str("2026/01/04")
        with self.assertRaises(ValueError):
            normalize_date_str("invalid-date")


class TestDatabaseIngestion(unittest.TestCase):
    """Integration test for full dataset ingestion into SQLite."""

    @classmethod
    def setUpClass(cls):
        # Create a temporary file database for isolated testing
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_crm.db"
        cls.counts = ingest_data(db_path=cls.db_path, reinit=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp_dir.cleanup()

    def test_record_counts(self):
        """Verify deduplication and correct table record counts."""
        self.assertEqual(self.counts["leads"], 3720)
        self.assertEqual(self.counts["owners"], 12)
        self.assertEqual(self.counts["deals"], 1120)  # 1142 total - 22 duplicates
        self.assertEqual(self.counts["invoices"], 308)
        self.assertEqual(self.counts["deals_missing_amount"], 7)
        self.assertEqual(self.counts["deals_duplicates_removed"], 22)

    def test_referential_integrity(self):
        """Verify all foreign keys point to valid parent records."""
        conn = get_connection(self.db_path)
        try:
            # Check deals -> leads
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM deals d
                LEFT JOIN leads l ON d.lead_id = l.lead_id
                WHERE l.lead_id IS NULL
            """)
            orphan_deals_lead = cur.fetchone()[0]
            self.assertEqual(orphan_deals_lead, 0)

            # Check deals -> owners
            cur.execute("""
                SELECT COUNT(*) FROM deals d
                LEFT JOIN owners o ON d.owner_id = o.owner_id
                WHERE o.owner_id IS NULL
            """)
            orphan_deals_owner = cur.fetchone()[0]
            self.assertEqual(orphan_deals_owner, 0)

            # Check invoices -> deals
            cur.execute("""
                SELECT COUNT(*) FROM invoices i
                LEFT JOIN deals d ON i.deal_id = d.deal_id
                WHERE d.deal_id IS NULL
            """)
            orphan_invoices = cur.fetchone()[0]
            self.assertEqual(orphan_invoices, 0)
        finally:
            conn.close()

    def test_date_column_formats_in_db(self):
        """Verify all stored dates strictly follow YYYY-MM-DD pattern."""
        conn = get_connection(self.db_path)
        try:
            iso_regex = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            cur = conn.cursor()

            # Leads
            for (dt,) in cur.execute("SELECT created_date FROM leads"):
                self.assertTrue(iso_regex.match(dt), f"Invalid date: {dt}")

            # Deals
            for c_dt, cl_dt in cur.execute("SELECT created_date, close_date FROM deals"):
                self.assertTrue(iso_regex.match(c_dt), f"Invalid created_date: {c_dt}")
                if cl_dt is not None:
                    self.assertTrue(iso_regex.match(cl_dt), f"Invalid close_date: {cl_dt}")

            # Invoices
            for iss, due, paid in cur.execute("SELECT issued_date, due_date, paid_date FROM invoices"):
                self.assertTrue(iso_regex.match(iss), f"Invalid issued_date: {iss}")
                self.assertTrue(iso_regex.match(due), f"Invalid due_date: {due}")
                if paid is not None:
                    self.assertTrue(iso_regex.match(paid), f"Invalid paid_date: {paid}")
        finally:
            conn.close()

    def test_foreign_key_enforcement(self):
        """Verify SQLite raises IntegrityError on foreign key violation."""
        conn = get_connection(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO deals (
                        deal_id, lead_id, owner_id, created_date, close_date,
                        stage, amount, currency, region, segment
                    )
                    VALUES ('DX9999', 'NONEXISTENT_LEAD', 'OWN001', '2026-01-01', NULL, 'open', 1000, 'USD', 'North', 'SMB')
                """)
        finally:
            conn.close()

    def test_check_constraints_enforced(self):
        """Verify SQLite check constraints prevent invalid stages or negative amounts."""
        conn = get_connection(self.db_path)
        try:
            # Invalid stage
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO deals (
                        deal_id, lead_id, owner_id, created_date, close_date,
                        stage, amount, currency, region, segment
                    )
                    VALUES ('DX9998', 'L00001', 'OWN001', '2026-01-01', NULL, 'invalid_stage', 1000, 'USD', 'North', 'SMB')
                """)

            # Negative deal amount
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO deals (
                        deal_id, lead_id, owner_id, created_date, close_date,
                        stage, amount, currency, region, segment
                    )
                    VALUES ('DX9997', 'L00001', 'OWN001', '2026-01-01', NULL, 'open', -500, 'USD', 'North', 'SMB')
                """)

            # Invoice due_date < issued_date
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("""
                    INSERT INTO invoices (invoice_id, deal_id, issued_date, due_date, paid_date, amount)
                    VALUES ('IX9999', 'D00001', '2026-02-01', '2026-01-01', NULL, 1000)
                """)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()


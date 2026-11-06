"""ETL pipeline to ingest CRM CSV data into SQLite database.

Handles deduplication, owner normalization, regex date normalization,
and relational integrity constraints.
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

from .connection import get_connection, init_db, DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# Default CSV source directory
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "round2_data"


def normalize_date_str(date_str: Optional[str]) -> Optional[str]:
    """Normalize date strings from mixed formats (YYYY-MM-DD or DD-MM-YYYY) to ISO 8601 (YYYY-MM-DD).
    
    Args:
        date_str: Raw date string or None/NaN.
        
    Returns:
        ISO 8601 formatted date string 'YYYY-MM-DD' or None.
    """
    if date_str is None or pd.isna(date_str):
        return None
    val = str(date_str).strip()
    if not val:
        return None
        
    # Match YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        return val
        
    # Match DD-MM-YYYY
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", val)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
        
    raise ValueError(f"Unsupported date format: '{date_str}'")


def ingest_data(
    data_dir: Optional[Path] = None,
    db_path: Optional[Path] = None,
    reinit: bool = True
) -> Dict[str, int]:
    """Ingest leads, owners, deals, and invoices into SQLite with data normalization.
    
    Args:
        data_dir: Path to directory containing leads.csv, deals.csv, invoices.csv.
        db_path: Path to target SQLite database.
        reinit: If True, recreates tables and indexes from schema.sql.
        
    Returns:
        Dictionary mapping table name to inserted record count.
    """
    csv_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    leads_path = csv_dir / "leads.csv"
    deals_path = csv_dir / "deals.csv"
    invoices_path = csv_dir / "invoices.csv"
    
    for path in (leads_path, deals_path, invoices_path):
        if not path.exists():
            raise FileNotFoundError(f"Required CSV file missing: {path}")
            
    if reinit:
        init_db(db_path, drop_existing=True)
        
    conn = get_connection(db_path)
    
    try:
        # 1. Ingest Leads
        leads_df = pd.read_csv(leads_path)
        leads_df["created_date"] = leads_df["created_date"].apply(normalize_date_str)
        leads_records = [
            (
                row["lead_id"].strip(),
                row["created_date"],
                row["source"].strip(),
                row["region"].strip(),
                row["segment"].strip(),
            )
            for _, row in leads_df.iterrows()
        ]
        
        conn.executemany(
            """
            INSERT OR REPLACE INTO leads (lead_id, created_date, source, region, segment)
            VALUES (?, ?, ?, ?, ?)
            """,
            leads_records
        )
        
        # 2. Extract and Ingest Owners from Deals
        raw_deals_df = pd.read_csv(deals_path)
        # Deduplicate deals by deal_id
        deals_df = raw_deals_df.drop_duplicates(subset=["deal_id"]).copy()
        
        unique_owners = sorted(deals_df["owner"].dropna().str.strip().unique())
        owner_id_map: Dict[str, str] = {
            owner_name: f"OWN{idx + 1:03d}"
            for idx, owner_name in enumerate(unique_owners)
        }
        
        owners_records = [
            (owner_id, owner_name)
            for owner_name, owner_id in owner_id_map.items()
        ]
        
        conn.executemany(
            """
            INSERT OR REPLACE INTO owners (owner_id, owner_name)
            VALUES (?, ?)
            """,
            owners_records
        )
        
        # 3. Ingest Deals
        deals_df["created_date"] = deals_df["created_date"].apply(normalize_date_str)
        deals_df["close_date"] = deals_df["close_date"].apply(normalize_date_str)
        deals_df["stage"] = deals_df["stage"].str.strip().str.lower()
        deals_df["currency"] = deals_df["currency"].str.strip().str.upper()
        deals_df["region"] = deals_df["region"].str.strip()
        deals_df["segment"] = deals_df["segment"].str.strip()
        
        deals_records = []
        missing_amount_count = 0
        for _, row in deals_df.iterrows():
            amt = float(row["amount"]) if pd.notnull(row["amount"]) else None
            if amt is None:
                missing_amount_count += 1
            owner_name = row["owner"].strip() if pd.notnull(row["owner"]) else None
            owner_id = owner_id_map.get(owner_name)
            
            deals_records.append((
                row["deal_id"].strip(),
                row["lead_id"].strip(),
                owner_id,
                row["created_date"],
                row["close_date"],
                row["stage"],
                amt,
                row["currency"],
                row["region"],
                row["segment"]
            ))
            
        conn.executemany(
            """
            INSERT OR REPLACE INTO deals (
                deal_id, lead_id, owner_id, created_date, close_date,
                stage, amount, currency, region, segment
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            deals_records
        )
        
        # 4. Ingest Invoices with Normalized Dates
        invoices_df = pd.read_csv(invoices_path)
        invoices_df["issued_date"] = invoices_df["issued_date"].apply(normalize_date_str)
        invoices_df["due_date"] = invoices_df["due_date"].apply(normalize_date_str)
        invoices_df["paid_date"] = invoices_df["paid_date"].apply(normalize_date_str)
        
        invoices_records = [
            (
                row["invoice_id"].strip(),
                row["deal_id"].strip(),
                row["issued_date"],
                row["due_date"],
                row["paid_date"],
                float(row["amount"])
            )
            for _, row in invoices_df.iterrows()
        ]
        
        conn.executemany(
            """
            INSERT OR REPLACE INTO invoices (
                invoice_id, deal_id, issued_date, due_date, paid_date, amount
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            invoices_records
        )
        
        conn.commit()
        
        counts = {
            "leads": len(leads_records),
            "owners": len(owners_records),
            "deals": len(deals_records),
            "invoices": len(invoices_records),
            "deals_missing_amount": missing_amount_count,
            "deals_duplicates_removed": len(raw_deals_df) - len(deals_df)
        }
        
        logger.info(f"Ingestion successful: {counts}")
        return counts
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Ingestion failed with error: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ingest CRM CSV files into SQLite database.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Directory containing CSV files (default: ../round2_data)")
    parser.add_argument("--db-path", type=Path, default=None, help="Path to SQLite database file (default: data/crm.db)")
    parser.add_argument("--no-reinit", action="store_true", help="Do not drop and recreate tables")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = ingest_data(data_dir=args.data_dir, db_path=args.db_path, reinit=not args.no_reinit)
    print("\n" + "=" * 60)
    print("INGESTION COMPLETED SUCCESSFULLY")
    print("=" * 60)
    for k, v in result.items():
        print(f"  {k:30s}: {v}")
    print("=" * 60)


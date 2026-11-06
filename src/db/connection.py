"""Database connection and initialization management for SQLite."""

import os
import sqlite3
from pathlib import Path
from typing import Optional

# Default database location inside ai-business-analyst/data/crm.db
DEFAULT_DB_PATH = Path(os.getenv("CRM_DB_PATH", Path(__file__).resolve().parent.parent.parent / "data" / "crm.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create and return an SQLite connection with WAL mode and foreign keys enabled.
    
    Args:
        db_path: Optional path to SQLite file. If None, uses DEFAULT_DB_PATH.
        
    Returns:
        sqlite3.Connection configured with row_factory and foreign keys.
    """
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    
    # Enforce SQLite foreign key constraints and enable WAL mode for concurrent readers
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    
    return conn


def init_db(
    db_path: Optional[Path] = None,
    schema_file: Optional[Path] = None,
    drop_existing: bool = False
) -> None:
    """Initialize the SQLite database with the DDL schema.
    
    Args:
        db_path: Optional path to SQLite file.
        schema_file: Optional path to schema.sql file.
        drop_existing: If True, drops existing tables in reverse dependency order.
    """
    target_schema = Path(schema_file) if schema_file else SCHEMA_PATH
    if not target_schema.exists():
        raise FileNotFoundError(f"Schema file not found at: {target_schema}")
        
    with open(target_schema, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        
    conn = get_connection(db_path)
    try:
        if drop_existing:
            conn.executescript("""
                DROP TABLE IF EXISTS invoices;
                DROP TABLE IF EXISTS deals;
                DROP TABLE IF EXISTS owners;
                DROP TABLE IF EXISTS leads;
            """)
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


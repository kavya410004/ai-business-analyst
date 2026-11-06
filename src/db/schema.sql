-- Schema definition for AI Business Analyst Relational Database
-- SQLite 3 Relational DDL with Foreign Keys & Integrity Constraints

PRAGMA foreign_keys = ON;

-- 1. Leads Table
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    created_date TEXT NOT NULL,
    source TEXT NOT NULL,
    region TEXT NOT NULL,
    segment TEXT NOT NULL
);

-- 2. Owners Table
CREATE TABLE IF NOT EXISTS owners (
    owner_id TEXT PRIMARY KEY,
    owner_name TEXT NOT NULL UNIQUE
);

-- 3. Deals Table
CREATE TABLE IF NOT EXISTS deals (
    deal_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE RESTRICT,
    owner_id TEXT NOT NULL REFERENCES owners(owner_id) ON DELETE RESTRICT,
    created_date TEXT NOT NULL,
    close_date TEXT,
    stage TEXT NOT NULL CHECK (stage IN ('won', 'lost', 'open')),
    amount REAL CHECK (amount IS NULL OR amount >= 0),
    currency TEXT NOT NULL CHECK (currency IN ('USD', 'INR')),
    region TEXT NOT NULL,
    segment TEXT NOT NULL
);

-- 4. Invoices Table
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id TEXT PRIMARY KEY,
    deal_id TEXT NOT NULL REFERENCES deals(deal_id) ON DELETE RESTRICT,
    issued_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    paid_date TEXT,
    amount REAL NOT NULL CHECK (amount > 0),
    CHECK (due_date >= issued_date)
);

-- Indexes for performance and query optimization
CREATE INDEX IF NOT EXISTS idx_leads_region ON leads(region);
CREATE INDEX IF NOT EXISTS idx_leads_segment ON leads(segment);
CREATE INDEX IF NOT EXISTS idx_leads_created_date ON leads(created_date);

CREATE INDEX IF NOT EXISTS idx_deals_lead_id ON deals(lead_id);
CREATE INDEX IF NOT EXISTS idx_deals_owner_id ON deals(owner_id);
CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals(stage);
CREATE INDEX IF NOT EXISTS idx_deals_close_date ON deals(close_date);
CREATE INDEX IF NOT EXISTS idx_deals_region ON deals(region);
CREATE INDEX IF NOT EXISTS idx_deals_segment ON deals(segment);
CREATE INDEX IF NOT EXISTS idx_deals_currency ON deals(currency);

CREATE INDEX IF NOT EXISTS idx_invoices_deal_id ON invoices(deal_id);
CREATE INDEX IF NOT EXISTS idx_invoices_issued_date ON invoices(issued_date);
CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_invoices_paid_date ON invoices(paid_date);


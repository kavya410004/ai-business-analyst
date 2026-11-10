# Data Dictionary

## 1. `leads`

Stores information about potential customers.

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `lead_id` | VARCHAR(20) | PK, NOT NULL | Unique lead identifier |
| `created_date` | DATE | NOT NULL | Lead creation date |
| `source` | VARCHAR(50) | NOT NULL | Lead acquisition channel |
| `region` | VARCHAR(50) | NOT NULL | Geographical region |
| `segment` | VARCHAR(50) | NOT NULL | Customer segment (SMB, Mid-Market, Enterprise) |

## 2. `deals`

Stores sales opportunities associated with leads and assigned to owners.

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `deal_id` | VARCHAR(20) | PK, NOT NULL | Unique deal identifier |
| `lead_id` | VARCHAR(20) | FK, NOT NULL | References `leads.lead_id` |
| `owner_id` | VARCHAR(20) | FK, NOT NULL | References `owners.owner_id` |
| `created_date` | DATE | NOT NULL | Deal creation date |
| `close_date` | DATE | NULL | Deal closing date |
| `stage` | VARCHAR(30) | NOT NULL, CHECK | Deal stage (Open, Won, Lost) |
| `amount` | DECIMAL(15,2) | NULL* | Deal value |
| `currency` | VARCHAR(3) | NOT NULL | Deal currency (USD, INR) |
| `region` | VARCHAR(50) | NOT NULL | Region associated with the deal |
| `segment` | VARCHAR(50) | NOT NULL | Segment associated with the deal |

## 3. `owners`

Stores sales representatives responsible for managing deals.

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `owner_id` | VARCHAR(20) | PK, NOT NULL | Unique owner identifier |
| `owner_name` | VARCHAR(100) | NOT NULL | Owner's name |

## 4. `invoices`

Stores invoices generated against deals.

| Column | Data Type | Constraints | Description |
|---|---|---|---|
| `invoice_id` | VARCHAR(20) | PK, NOT NULL | Unique invoice identifier |
| `deal_id` | VARCHAR(20) | FK, NOT NULL | References `deals.deal_id` |
| `issued_date` | DATE | NOT NULL | Invoice issuance date |
| `due_date` | DATE | NOT NULL | Payment due date |
| `paid_date` | DATE | NULL | Payment date |
| `amount` | DECIMAL(15,2) | NOT NULL, CHECK | Invoice amount (positive) |

---

## 5. Relationships

| Parent | Child | Cardinality | Foreign Key |
|---|---|---|---|
| Leads | Deals | 1:N | `deals.lead_id` |
| Owners | Deals | 1:N | `deals.owner_id` |
| Deals | Invoices | 1:N | `invoices.deal_id` |

- A lead can have zero or multiple deals.
- An owner can manage zero or multiple deals.
- A deal can have zero or multiple invoices.
- Each deal belongs to exactly one lead and one owner.
- Each invoice belongs to exactly one deal.

## 6. Design Decisions & Assumptions

1. **Owner normalization:** Owner names are moved from `deals` into a separate `owners` table to avoid repeated values and maintain consistency.
2. **Historical snapshots:** `region` and `segment` are retained in both `leads` and `deals` to preserve deal-time classifications.
3. **Deal–invoice relationship:** Multiple invoices per deal are supported to accommodate partial or milestone-based billing.
4. **Currency:** Invoice currency is derived from the associated deal through `deal_id`; it is not stored separately in invoices.
5. **Categorical attributes:** `stage`, `source`, `region`, `segment`, and `currency` are stored as categorical values rather than separate lookup tables.
6. **Missing deal amounts:** `amount` is temporarily nullable because seven won deals have missing amounts in the source data. These require investigation before enforcing `NOT NULL`.

## 7. Data Integrity Rules

| Rule | Constraint |
|---|---|
| Unique record identifiers | Primary keys |
| Valid lead, owner and deal references | Foreign keys |
| Valid deal stages | CHECK (`stage IN ('Open', 'Won', 'Lost')`) |
| Non-negative deal amounts | CHECK (`amount >= 0`) |
| Positive invoice amounts | CHECK (`amount > 0`) |
| Valid invoice dates | `due_date >= issued_date` |
| Closed deals must have a closing date | Business rule |
| Open deals should have no closing date | Business rule |

**Note:** Primary keys are inherently UNIQUE and NOT NULL. Foreign keys such as `lead_id`, `owner_id`, and `deal_id` must not be UNIQUE, as their parent records can have multiple associated child records.
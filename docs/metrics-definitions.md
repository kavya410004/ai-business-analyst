# Business Metrics & Definitions Catalogue

This catalogue establishes the official business metrics, formulas, terminology, and governance rules for the AI Business Analyst POC. To ensure commercial credibility and consistency, terminology and methodology align with **Salesforce CRM & Analytics Cloud** standards while strictly respecting the realities and limitations of the provided dataset.

Every calculation performed by the analytics service must strictly follow the definitions, formulas, and data-handling rules specified in this document.

---

## 1. Governance & Correctness Principles

In accordance with [`AGENTS.md`](../../AGENTS.md):
1. **Deterministic Origin**: Every number reported must be computed deterministically by Python/SQL service functions—never estimated, extrapolated, or calculated by an LLM.
2. **Deduplication Prerequisite**: All deal-level metrics must operate on **deduplicated deal records** (deduplicating by `deal_id`). The raw `deals.csv` contains 22 duplicate rows (1,142 total rows reducing to 1,120 unique deals). Calculations must never double-count duplicate records.
3. **Zero Imputation**: Missing values (`NULL`) must **never** be treated as zero. Records with missing data must be excluded from numerical sums/averages and explicitly reported in the supporting metadata.
4. **Currency Separation**: Because transactions occur in both **USD** and **INR**, revenue and monetary metrics must be calculated and reported separately per currency. No synthetic or assumed exchange rate may be introduced.
5. **Audit Trail & Metadata**: Every metric output must accompany its definition, applied filters, evaluation period, supporting record counts, and data quality notes.
6. **Insufficient Data & Sample Size Thresholds**: Any cohort or segment with fewer than 10 supporting records ($N < 10$) must be explicitly flagged in metadata with an insufficient-data advisory due to high statistical variance.

---

## 2. Category 1: Revenue and Commercial Performance

Metrics evaluating commercial inflow, bookings velocity, and billing output.

### 2.1 Closed-Won Bookings (Contracted Deal Value)
*Salesforce Terminology: Closed Won Opportunity Amount / Bookings*
- **Definition**: The total monetary value of sales opportunities marked as `Closed Won` whose `close_date` falls within the specified evaluation period. Represents the total contracted value of new business signed.
- **Terminology Clarification**: This metric is strictly **Bookings** (contracted opportunity value). Because the dataset does not contain contract length, subscription terms, or start/end dates, this metric cannot and must not be referred to as Annual Contract Value (ACV) or Annual Recurring Revenue (ARR).
- **Business Purpose**: Measures sales momentum and aggregate deal production.
- **Formula**:
  $$\text{Closed-Won Bookings} = \sum \text{deals.amount} \quad \text{WHERE } \text{stage} = \text{'won'} \text{ AND } \text{close\_date} \in [\text{start\_date}, \text{end\_date}]$$
- **Parameters**:
  - `quarter`: e.g. `'2026Q3'`, `'2026Q2'`.
  - `currency`: `'USD'` or `'INR'` (if `None`, reports separate totals for each currency).
  - `segment`: Optional filter (`'SMB'`, `'Mid-Market'`, `'Enterprise'`).
  - `region`: Optional filter (`'North'`, `'South'`, `'East'`, `'West'`).
- **Missing Value Handling**: Exactly 7 won deals have `amount IS NULL`. In calculations:
  - These 7 deals are excluded from the monetary sum.
  - They are counted in the total won deal count.
  - The metadata explicitly reports `records_missing_amount_count = 7`.
  - Missing amounts are never treated as zero.

### 2.2 Invoiced Amount (Customer Billings)
*Salesforce Terminology: Billed Amount / Invoiced Total*
- **Definition**: The total gross amount for which invoices were formally issued to customers during the evaluation period.
- **Accounting Clarification**: Invoiced Amount represents **Billings**, not GAAP/accrual recognized accounting revenue. True accounting revenue recognizes value over the delivery period of a contract; because the CRM dataset provides invoice issue dates rather than revenue recognition schedules, Invoiced Amount serves as the operational billing metric.
- **Formula**:
  $$\text{Invoiced Amount} = \sum \text{invoices.amount} \quad \text{WHERE } \text{issued\_date} \in [\text{start\_date}, \text{end\_date}]$$
- **Parameters**: `quarter`, `currency` (derived from parent deal), `segment`, `region`.
- **Sample Size & Metadata**: Must report `invoices_count` and total monetary sum per currency.

### 2.3 Cash Collections (Cash-Flow Proxy)
*Salesforce Terminology: Realized / Paid Invoices*
- **Definition**: The total cash received on invoices paid during the evaluation period.
- **Accounting Clarification**: Cash collections measures actual customer remittances. It functions as a **cash-flow and working-capital proxy**, not recognized revenue.
- **Formula**:
  $$\text{Cash Collections} = \sum \text{invoices.amount} \quad \text{WHERE } \text{paid\_date} \in [\text{start\_date}, \text{end\_date}]$$
- **Parameters**: `quarter`, `currency`, `segment`, `region`.

### 2.4 Period-over-Period Variance (QoQ % Change)
*Salesforce Terminology: Period-over-Period Variance (%)*
- **Definition**: The relative percentage growth or contraction in commercial metrics between two consecutive quarters.
- **Formula**:
  $$\text{QoQ Growth (\%)} = \frac{\text{Metric}_{\text{Current}} - \text{Metric}_{\text{Prior}}}{\text{Metric}_{\text{Prior}}} \times 100\%$$
- **Edge Case**: If $\text{Metric}_{\text{Prior}}$ is zero or null, growth is undefined; reported as `NULL` with an explanation in metadata.
- **Assignment Mapping**: **Question 1** (*"What was total revenue last quarter, and how does it compare to the quarter before?"*).

---

## 3. Category 2: Sales Effectiveness

Metrics tracking deal progression, conversion efficiency, and pipeline dynamics.

### 3.1 Opportunity Win Rate (Count-Based)
*Salesforce Terminology: Opportunity Win Rate (%)*
- **Definition**: The proportion of finalized (closed) sales opportunities that resulted in a win.
- **Pipeline Truncation Rule**: Open opportunities (`stage = 'open'`) are **intentionally excluded** from the denominator. Including open deals in win rate introduces artificial deflation based on pipeline duration.
- **Formula**:
  $$\text{Win Rate}_{\text{Count}} = \frac{\text{Count of Won Deals}}{\text{Count of Won Deals} + \text{Count of Lost Deals}} \times 100\%$$
- **SQL Logic**:
  ```sql
  SELECT 
      CAST(SUM(CASE WHEN stage = 'won' THEN 1 ELSE 0 END) AS FLOAT) / 
      COUNT(*) * 100.0 AS win_rate_pct,
      SUM(CASE WHEN stage = 'won' THEN 1 ELSE 0 END) AS won_count,
      SUM(CASE WHEN stage = 'lost' THEN 1 ELSE 0 END) AS lost_count,
      COUNT(*) AS total_closed_deals
  FROM deals
  WHERE stage IN ('won', 'lost');
  ```
- **Assignment Mapping**: **Question 2** (*"Which region has the lowest win rate?"*).

### 3.2 Opportunity Win Rate (Value-Based)
*Salesforce Terminology: Win Rate by Amount*
- **Definition**: The proportion of closed deal value won versus total closed deal value attempted.
- **Formula**:
  $$\text{Win Rate}_{\text{Value}} = \frac{\sum \text{Won Deal Amount}}{\sum \text{Won Deal Amount} + \sum \text{Lost Deal Amount}} \times 100\%$$
- **Missing Value Handling**: Deals with `amount IS NULL` are excluded from both numerator and denominator; counts of included and excluded deals are reported.

### 3.3 Win Rate Change Diagnostics (Shift-Share Decomposition)
*Salesforce Terminology: Pipeline Mix vs. Conversion Variance Analysis*
- **Definition**: A mathematical decomposition that isolates whether a period-over-period change in aggregate win rate was driven by changes in sales effectiveness (rate effect) or by changes in pipeline composition (mix effect / Simpson's Paradox).
- **Mathematical Framework**:
  Let $W$ be the aggregate win rate, $r_i$ be the win rate in cohort $i$ (e.g. segment or region), and $w_i = \frac{N_i}{N}$ be cohort $i$'s proportion of total closed deals, such that:
  $$W = \sum_{i} w_i r_i$$
  Between base period $b$ (e.g., Q2) and target period $t$ (e.g., Q3), the total change $\Delta W = W_t - W_b$ is decomposed using the exact 3-factor Shift-Share (Kitagawa) decomposition:
  $$\Delta W = \underbrace{\sum_{i} w_{i, b} \cdot (r_{i, t} - r_{i, b})}_{\text{Within-Cohort Rate Effect}} + \underbrace{\sum_{i} r_{i, b} \cdot (w_{i, t} - w_{i, b})}_{\text{Pipeline Mix Effect}} + \underbrace{\sum_{i} (w_{i, t} - w_{i, b}) \cdot (r_{i, t} - r_{i, b})}_{\text{Interaction / Cross-Product Effect}}$$
  - **Within-Cohort Rate Effect**: The portion of win rate change caused by genuine increases or decreases in conversion efficiency within individual segments, holding pipeline mix constant at base-period levels.
  - **Pipeline Mix Effect**: The portion of win rate change caused by shifting deal volume toward inherently higher- or lower-converting segments, holding segment conversion rates constant at base-period levels.
  - **Interaction Effect**: The joint covariance between shifting proportions and changing rates.
- **Assignment Mapping**: **Question 3** (*"Why did win rate drop in Q3?"*).

---

## 4. Category 3: Payment and Collections

Metrics tracking payment turnaround, overdue delinquency, and accounts receivable exposure.

### 4.1 Payment Status Taxonomy
Invoices are strictly categorized into distinct states:
1. **Paid Invoices**: Invoices where `paid_date IS NOT NULL`.
   - *Paid On-Time / Early*: `paid_date <= due_date`
   - *Paid Late*: `paid_date > due_date`
2. **Unpaid / Open Invoices**: Invoices where `paid_date IS NULL`.
   - *Unpaid - Current (Within Terms)*: `paid_date IS NULL AND as_of_date <= due_date`
   - *Unpaid - Overdue (Delinquent)*: `paid_date IS NULL AND as_of_date > due_date`

> **Critical Distinction**: An unpaid invoice is **not** necessarily overdue. Invoices within their 30-day payment term are current receivables, not delinquent.

### 4.2 Days to Pay (Invoice Payment Turnaround)
*Salesforce Terminology: Payment Turnaround Time / Average Days to Pay*
- **Definition**: The elapsed calendar days between the date an invoice was issued and the date payment was received.
- **Scope Restriction**: Calculated **only** for paid invoices (`paid_date IS NOT NULL`). Unpaid invoices have undefined turnaround time and must never be assigned an arbitrary turnaround or zero.
- **Formula**:
  $$\text{Days to Pay} = \text{invoices.paid\_date} - \text{invoices.issued\_date}$$
- **Statistical Measures**:
  - **Mean Days to Pay**: $\frac{\sum \text{Days to Pay}}{N_{\text{paid}}}$
  - **Median Days to Pay**: 50th percentile of Days to Pay (primary operational metric to avoid outlier distortion).
- **Mandatory Sample Size Reporting**: Must explicitly report $N_{\text{paid}}$ (count of paid invoices evaluated) alongside mean and median.
- **Assignment Mapping**: **Question 4** (*"Which segment pays us slowest?"*).

### 4.3 Days Past Due (Payment Delinquency on Paid Invoices)
*Salesforce Terminology: Collection Delay / Days Past Due*
- **Definition**: The number of calendar days an invoice payment arrived past its contractually agreed due date.
- **Formula**:
  $$\text{Days Past Due} = \text{invoices.paid\_date} - \text{invoices.due\_date}$$
  - $\text{Days Past Due} > 0$: Payment was late.
  - $\text{Days Past Due} \le 0$: Payment was on time or early.
- **Mandatory Sample Size**: Must report $N_{\text{paid}}$ and distribution (mean, median).

### 4.4 Outstanding Receivables & Overdue Exposure
*Salesforce Terminology: Open Invoices / Overdue Aging*
- **Definition**: Monetary exposure and record counts of invoices that have not yet been settled (`paid_date IS NULL`).
- **Breakdown**:
  - `total_unpaid_count`: Total open invoices.
  - `total_unpaid_amount`: Total open monetary balance per currency.
  - `overdue_unpaid_count`: Invoices where `due_date < as_of_date`.
  - `overdue_unpaid_amount`: Balance past due date per currency.
  - `current_unpaid_count`: Invoices within payment terms (`due_date >= as_of_date`).

---

## 5. Category 4: Business Overview & Supporting Indicators

Holistic KPIs synthesizing commercial momentum, sales efficiency, and operational risk.

### 5.1 Executive Scorecard ("How are we doing?")
*Salesforce Terminology: Executive Pipeline & Commercial Health KPI Snapshot*
- **Definition**: A multi-dimensional executive synthesis designed for leadership to gauge overall company health across four operational pillars:
  1. **Commercial Growth**: Closed-Won Bookings and Invoiced Amount with QoQ growth trajectories.
  2. **Sales Efficiency**: Overall Win Rate (count and value) and regional win rate variance (identifying best and lagging regions).
  3. **Pipeline Health**: Total closed deal volume and open deal count.
  4. **Collection Risk**: Median Days to Pay and total outstanding/overdue receivables.
- **Assignment Mapping**: **Question 5** (*"How are we doing?"*).

### 5.2 Data Quality & Health Indicators
- **Deduplication Audit**: Reports raw rows vs unique deals (1,142 raw vs 1,120 deduplicated).
- **Missing Value Tracking**: Reports count and impact of missing fields (e.g. 7 won deals missing amount).
- **Date Anomaly Log**: Documents records with chronological inversions (e.g. 6 paid invoices where `paid_date < issued_date`).

---

## 6. Assumptions and Known Limitations

The following assumptions and constraints apply to all analytics services:

1. **Absence of Subscription Term / Recurring Revenue**: The CRM data contains only opportunity `amount` with no contract start date, end date, or renewal period. All revenue metrics represent **Bookings / Contracted Value**, not ARR or MRR.
2. **Absence of Revenue Recognition Schedules**: Invoices reflect billing events, not GAAP accrual revenue recognition.
3. **Cash Collections as a Proxy**: Paid invoices reflect customer cash receipts, serving as a working capital proxy without access to external banking ledger feeds.
4. **Owner Identification**: Deal ownership is assumed to be 1:1 based on sales representative name strings.
5. **Invoice Currency**: Invoices do not store currency directly; currency is derived from the parent deal via `deal_id`.
6. **Payment Date Inversions**: In `invoices.csv`, exactly 6 records have `paid_date` preceding `issued_date` by 3 to 13 days. These are retained as recorded in the source data and flagged in metadata notes.
7. **Missing Won Deal Amounts**: Exactly 7 won deals have NULL `amount` in `deals.csv`. Their amounts are present in `invoices.csv`, but per data governance rules, the `deals` table preserves the raw source state (`NULL`). They are omitted from deal amount sums and flagged in audit metadata.
8. **Snapshot Classifications**: Region and segment attributes on deals represent historical snapshots at deal creation.

---

## 7. Metric to Question Reference Matrix

| Assignment Question | Primary Service | Primary Function | Metric Category |
|---|---|---|---|
| **Q1: Total revenue last quarter vs quarter before?** | `RevenueAnalyticsService` | `compare_quarterly_revenue` | 1. Revenue & Commercial |
| **Q2: Which region has the lowest win rate?** | `SalesEffectivenessService` | `get_win_rates(dimension='region')` | 2. Sales Effectiveness |
| **Q3: Why did win rate drop in Q3?** | `SalesEffectivenessService` | `diagnose_win_rate_change(dimension='segment')` | 2. Sales Effectiveness |
| **Q4: Which segment pays us slowest?** | `PaymentAnalyticsService` | `get_payment_speed_by_dimension(dimension='segment')` | 3. Payment & Collections |
| **Q5: How are we doing?** | `ExecutiveOverviewService` | `get_executive_scorecard()` | 4. Business Overview |

# Usage-Based Revenue Recognition Model: Spec

A small, end-to-end model of one quarter of revenue accounting for a fictional usage-billed SaaS company. It covers usage, billing, revenue recognition under ASC 606, journal entries, AR and collections, reconciliations, close, and audit workpapers.

**All data is synthetic.** The company, customers, prices, and events are invented. Nothing comes from any real employer or customer. HM's business model is patterned on how product-led, usage-billed analytics companies publicly describe their pricing, so the accounting questions are realistic. The specific prices and terms are illustrative.

**Technical north star:** PwC, *Revenue from contracts with customers* (partially updated as of May 2026). Citations use the guide's section numbers (for example, RR 5.5.1.1) and the ASC paragraphs it quotes. The guide is copyrighted and is **not** committed to this repo. Cite it, don't copy it.

**Design goal:** Three customers, done thoroughly. Every dollar of revenue should be traceable: where it came from, how it was recognized, why, and when it was collected.

---

## 1. The fictional company

**Hedgehog Metrics, Inc.** ("HM") is a product-led analytics platform. Customers start on a free tier and pay monthly in arrears for usage above it. Larger customers prepay for annual credit at a discount.

### Usage products

| Product | Unit | Free tier / month | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|---|
| Event analytics | per event | first 1,000,000 | next 1M–5M: $0.00005 | next 5M–25M: $0.00003 | above 25M: $0.00002 |
| Session replay | per recording | first 5,000 | next 5k–50k: $0.005 | next 50k–250k: $0.003 | above 250k: $0.002 |
| Feature flags | per request | first 1,000,000 | next 1M–10M: $0.0001 | above 10M: $0.00005 | |

- Tiers are **graduated** (each unit is priced at its own tier's rate) and **reset every calendar month**.
- Customers may set a **billing limit**: a dollar cap per product per month. Each month, the price is the lower of what the usage costs (after the free tier and tier pricing) or the cap. Usage above the cap is never billed.
- Monthly invoices are issued on business day 2 for the prior month's usage, with Net 30 terms unless a customer's terms say otherwise (Tela is Net 15).
- Business days are weekdays, with no holidays in the model period. Business day 2 is January 2, February 3 and March 3. Business day 3, the close cutoff, is February 4 and March 4.

### Annual prepaid credit
- Credit is sold at a **20% discount**: $100,000 of credit costs $80,000. It's invoiced upfront, Net 30, and noncancellable, with a 12-month term.
- Usage draws down credit at standard list prices on any product, after the same monthly free tier every customer gets.
- Unused credit expires at term end.

**Model period:** January–March 2026 (three monthly closes). The fiscal year starts January 1.

---

## 2. Customers and what each one proves

| Customer | Plan | JD focus areas it proves |
|---|---|---|
| **Harry Hood** | Monthly, pay-as-you-go. Pays on time. | Core usage-based recognition: tiered pricing, month-end accrual and cutoff, lag estimate and true-up, customer-side delays, duplicate usage |
| **Famous Mockingbird** | Annual prepaid credit: $100,000 of credit for $80,000, term Jan 1 – Dec 31, 2026 | Deferrals and recognition schedules: contract liability, drawdown at the discounted rate, breakage judgment, liability rollforward |
| **Tela** | Monthly, pay-as-you-go, Net 15, with a $1,000 monthly billing limit on session replay | AR and collections: a billing question about the cap, a disputed January invoice partially credited in February, a late February payment, and AR aging and follow-up |

---

## 3. Accounting policies

Each policy states the treatment, the reasoning, and the guide reference. **These are the parts to defend in an interview.** The code implements these, not the other way around.

### 3.1 Usage billed monthly in arrears (all usage customers)
- **Treatment:** Each month's usage fee is recognized as revenue in the month the usage occurs.
- **Why:**
  - Access to the platform is a series of distinct monthly services accounted for as one performance obligation satisfied over time. RR 3.3.2 names SaaS as an example of a series, and applying the series guidance isn't optional when its criteria are met (ASC 606-10-25-15).
  - Variable consideration is allocated to each distinct month, not to the series as a whole (RR 3.3.2, RR 5.5.1.1).
  - The usage fee relates specifically to that month's service, and pricing is consistent across the term, so it's allocated entirely to that month (ASC 606-10-32-40; RR 5.5.1; **Example RR 5-9**, a per-transaction monthly fee allocated to the month of processing).
- **Also available:** the "right to invoice" practical expedient (ASC 606-10-55-18; RR 6.4.1.1), because the per-unit price corresponds directly with value transferred. Either path gives the same answer for pay-as-you-go usage. The memo states which one is elected and why.
- **Tiers resetting monthly** don't change this. Each month's fee is fully determined by that month's usage.

### 3.2 Month-end cutoff, accruals, and data quality (Harry Hood)
- **Three timestamps:** Every usage row carries `client_ts` (when the customer's device or server generated the event), `received_ts` (when HM's servers received it), and `processed_ts` (when HM's pipeline finished rating it). All are in UTC, and billing periods are calendar months in UTC.
- **Cutoff follows `received_ts`:**
  - HM's service is receiving, processing, and storing events, so it performs when it receives them. Usage is assigned to the month it was received, whatever its `client_ts`.
  - Customer-side delays (offline devices, client batching, backfills, retries) therefore fall into the month the events arrive. They aren't late, and they never reopen a closed month.
  - Billing uses the same clock: billable usage for a month is usage received in that month, so the invoice and revenue never follow different clocks. *In practice, confirm this matches how the customer terms define billable usage.*
  - This is a judgment HM makes and documents. The guide supports recognizing each month's usage fee in the month of service (section 3.1), but it doesn't address which timestamp defines the month. The memo defends the choice.
- **Accrual:** At month end, the month's usage is recognized and recorded as an **unbilled receivable**, since the invoice goes out on business day 2. The unbilled receivable moves to billed AR when the invoice is issued.
  - It's a receivable, not a contract asset, because HM's right to that consideration is unconditional: only the passage of time is needed before payment is due (ASC 606-10-45-4).
  - *This guide doesn't cover presentation. PwC addresses it in its separate Financial statement presentation guide (FSP 33), so the citation is to the ASC directly.*
- **HM-side lag (estimate, then true-up):**
  - Some usage received in a month isn't processed until after the close cutoff (business day 3), because of pipeline backlogs, failed metering jobs, or outage replays.
  - At close, HM accrues an estimate for it: the historical lag rate in `assumptions.csv` × the month's processed usage revenue, by customer. It's recorded as revenue and unbilled receivable. (Applying the lag rate to dollars rather than re-rating units through the tiers is a simplification, noted in the memo.)
  - The estimate applies only to customers whose usage history shows post-cutoff lag. In this model, that is Harry Hood only (`lag_estimate_customers` in `assumptions.csv`).
  - Each month-end estimate reverses on the 1st of the next month, and actual late usage is recognized when it's rated. The reversal plus the actual is the change in estimate for that month.
  - When the usage is processed, it's billed on a true-up line on the next invoice. The difference between actual and estimate is recognized in the current month as a change in estimate, not an error correction (ASC 250).
- **Unusual items and the close threshold:**
  - Items the estimate doesn't anticipate (for example, a bug fix that reprocesses a closed month) are measured in aggregate across all customers for the month, not item by item.
  - Below the close threshold in `assumptions.csv` (a percentage of the month's total revenue), they're recorded in the current month and logged in `passed_adjustments_log.csv`, so the cumulative effect stays visible.
  - Above the threshold, or if qualitatively significant (for example, it would change a reported growth metric), they're evaluated as a possible prior-period error under ASC 250. The model logs them as exceptions for review and doesn't record them automatically.
  - The threshold base is the month's total revenue, including the unusual items.
  - The model assumes the threshold was agreed with the auditors and written into the close policy, set below their "clearly trivial" level.
- **Duplicates:** Usage rows are deduplicated on `event_id` before pricing. Duplicates are logged as exceptions and never billed.

### 3.3 Discounted prepaid credit and deferral (Famous Mockingbird)
- **At invoicing (Jan 1):** HM records a receivable and a **contract liability** (deferred revenue) of $80,000. The order form is noncancellable and payment is due before HM performs (ASC 606-10-45-2; presentation guidance is in PwC's FSP guide, not this one). Cash arrives Jan 28.
- **Revenue per credit consumed:** Usage draws down credit at list price, but the customer paid $0.80 per $1.00 of credit, so revenue is recognized at **$0.80 per $1.00 of credit consumed**.
  - **Why:** The transaction price is the $80,000 paid, not the $100,000 of list-value credit.
  - **Why usage-based:** A promise of a fixed quantity that diminishes with customer usage is a promise to deliver that service, not a stand-ready obligation, so a usage-based measure of progress fits (RR 6.4.3; **Example RR 6-10**, 100 support hours recognized as used).
  - **Two balances side by side:** the **credit balance** (list value, what the customer sees) and the **contract liability** (cash value, what the books show). The contract liability always equals the remaining credit × 0.80.
  - **Rounding:** revenue to date = 0.80 × credit consumed to date, rounded to cents, less revenue already recognized. This keeps the contract liability equal to remaining credit × 0.80 to the cent.
- **Right to invoice doesn't apply.** The upfront payment means invoiced amounts don't track value transferred (RR 6.4.1.1 discusses upfront payments as an indicator against the expedient).
- **Breakage judgment:**
  - Unused credit at term end is breakage. If HM expects to be entitled to it, breakage is recognized in proportion to credit consumed. Otherwise, it's recognized when the likelihood of use becomes remote (ASC 606-10-55-48; RR 7.4; works like **Example RR 7-12**).
  - The estimate is subject to the variable consideration constraint: include it only to the extent a significant reversal of cumulative revenue is not probable (ASC 606-10-32-11; RR 4.3.2).
  - **Model decision:** HM has no history with credit contracts, which is a named factor pointing toward constraint (ASC 606-10-32-12(c)). So **expected breakage is constrained to $0** for now, and the estimate is reassessed each month. The revenue schedule shows a $0 breakage row each month to make the reassessment visible.
  - The memo explains what evidence would change that, and that unused credit would need to be checked against unclaimed property (escheat) laws before any breakage is recognized (RR 7.4).

### 3.4 Billing limits, disputes, and collections (Tela)
- **Billing limit:** Tela has set a dollar cap on session replay. Usage above the cap is not billed and not recognized, because HM has no right to consideration for it. In effect, the cap is part of the price.
  - *In the model:* Tela's cap is $1,000 a month. January replay usage prices at $1,525, so Tela is invoiced $1,000 and HM recognizes $1,000 of revenue. The $525 is never owed.
  - **The cap is applied before revenue is calculated.** The $525 is not revenue followed by a reversal or contra-revenue, not a credit memo or concession, and not bad debt, because it was never owed.
  - **Reconciliation:** Capped usage is reported separately as a reconciling item, so the usage-to-invoice tie-out shows the gap rather than an unexplained difference.
  - **On the invoice:** replay tier lines are shown at list, followed by a separate "Monthly billing limit ($1,000.00)" line for the capped amount. This line is presentation only. It never posts to revenue, contra-revenue, or a credit memo.
  - *In practice*, products with billing limits often stop processing data once the cap is hit. The model lets the usage arrive and prices it so the cap is visible.
- **The billing question:** In early February, Tela's finance team asks why January's invoice is higher than December's. The answer comes from the model's per-customer usage-to-invoice trace. The repo includes the reply as `output/billing_reply_tela.md`, written in plain language for a customer.
- **The dispute:** Tela says some January event volume came from a misconfigured test environment and asks for relief. HM issues a **$1,500 credit memo** in February.
  - **Classification:** This is a **price concession**, not a credit loss. It's an adjustment outside the original contract terms, given because of customer dissatisfaction, not because Tela can't pay (RR 4.3.3.1).
  - **Timing:** January's service is already delivered, so the change in transaction price reduces revenue in **February**, the period the price changes (ASC 606-10-32-43; RR 5.5.2). It's recorded as contra-revenue and tagged to event analytics in the revenue schedule, since the dispute concerned event volume.
  - **Policy question for the memo:** A reporting entity that expects to give concessions, or has a practice of doing so, should reduce the transaction price up front (RR 4.3.3.1; **Example RR 4-9**). At what point does HM's history become a "practice"?
- **Collections:**
  - Tela is on **Net 15** terms.
  - The January invoice (issued February 3, due February 18) is credited on February 10. Tela short-pays it (invoice less the credit memo) on February 17, on time.
  - The February invoice (issued March 3, due March 18) is paid **20 days late**, on April 7. It's 13 days past due at March 31, so it appears in the 1–30 days past due bucket of the March 31 AR aging. It clears in April, outside the model period.
  - Collectibility isn't in doubt, and lateness alone doesn't change revenue. The memo notes what would trigger a reassessment.
  - The model generates an AR aging and a short collections log: reminder sent at day 5 past due (March 23), follow-up at day 15 (April 2, after the period, shown as scheduled).

### 3.5 Free tier
- Usage within the free tier generates no consideration and therefore no revenue. Free usage is still counted in the reconciliation so completeness can be proven.

---

## 4. The billing ledger and the GL

The posting mentions owning the integration between a billing ledger and the accounting ERP. The model mirrors that pattern generically:

- **Billing ledger** (`output/billing_ledger.csv`): the system of record for every billing event, including usage rated, invoice issued, credit drawn down, credit memo, and payment applied. One row per event, with an immutable `ledger_id`.
  - It also carries the January 1 opening unbilled AR (section 5), so rollforwards and the GL start from the ledger.
  - Events after March 31 (the March invoices issued April 2, Tela's April 7 payment) are kept at their real dates. Every Q1 report and rollforward cuts off at March 31.
  - It also carries the revenue engine's entries (lag estimates and reversals, and credit revenue at 0.80), marked `origin = revenue_engine`, so the GL still comes only from the ledger. Billing events are marked `origin = billing`.
- **Account mapping** (`config/account_mapping.csv`): maps each billing ledger event type to GL debits and credits. This file is where finance owns the integration logic.
- **GL export** (`output/gl_export.csv`): journal entries generated only from the billing ledger through the mapping, summarized by day, account, and customer, with a `ledger_id` trail back to the source rows.
- **Integration controls:**
  - Every billing ledger row is either mapped or appears in exceptions.
  - The GL export's total for each account ties to the billing ledger.
  - Re-running the export produces identical output (idempotent).

The GL export is ERP-agnostic. No real ERP's import format is assumed.

---

## 5. Data model (CSV files in `data/`)

| File | Grain | Key fields |
|---|---|---|
| `customers.csv` | customer | `customer_id`, `name`, `plan_type`, `payment_terms`, `billing_limits` (dollars per product per month) |
| `contracts.csv` | contract | `contract_id`, `customer_id`, `contract_type` (payg / credit), `effective_from`, `effective_to`, `credit_value`, `cash_price` |
| `rate_cards.csv` | product × tier | `product`, `tier_floor`, `tier_ceiling`, `unit_price` |
| `usage_events.csv` | daily aggregate per customer per product | `event_id`, `customer_id`, `product`, `quantity`, `client_ts`, `received_ts`, `processed_ts`, `source` (`normal` / `bug_fix_reprocess`) |
| `payments.csv` | payment, **generated in build step 4** from rules once invoices exist (Harry Hood pays in full 3 days before the due date, or the weekday before if that falls on a weekend; Famous Mockingbird pays January 28; Tela as in 3.4, and pays its December invoice by the same 3-day rule; invoices issued after March 31 have no payments). Invoice IDs follow a fixed pattern, e.g. `INV-2026-01-TELA`. | `payment_id`, `customer_id`, `invoice_id`, `amount`, `received_date` |
| `prior_period_invoices.csv` | December 2025 invoices for Harry Hood and Tela, by product. They're issued January 2 from the opening unbilled AR. Tela's also supports the billing reply in 3.4. December usage is never recognized as revenue in the model period. | `customer_id`, `invoice_id`, `product`, `amount` |
| `opening_balances.csv` | balance at January 1, 2026 | `as_of`, `account`, `customer_id`, `debit`, `credit`, `note` |
| `adjustments.csv` | credit memo | `adjustment_id`, `customer_id`, `invoice_id`, `amount`, `date`, `reason`, `classification` |
| `assumptions.csv` | assumption | `key`, `value`, `note` (close cutoff day, historical lag rate, close threshold as % of the month's revenue, breakage %, collections reminder days) |

Keep the data small enough to inspect by eye: daily aggregates, with a few deliberate problem rows for Harry Hood:
- two duplicate rows
- one batch of 2,000,000 events received January 31 but processed February 6, after the cutoff (business day 3 is February 4). This is HM-side lag: January revenue via the estimate, true-up in February.
- one batch with a January 31 `client_ts` received February 1 (customer-side delay: February usage, no true-up)
- one event at 11pm Pacific on January 31, which is February 1 in UTC (time zone: February usage)
- one unusual item: in March, a bug fix reprocesses $50 of Harry Hood's January usage (2,500,000 events at January's tier 3 rate), marked `source = bug_fix_reprocess`. It's below the close threshold, so it's recorded in March and logged in `passed_adjustments_log.csv` (section 3.2). It's billed on the March invoice as a separate line labeled "January usage, reprocessed after a system fix." It doesn't change any January or February result below.

### Opening balances (January 1, 2026)

Harry Hood and Tela had contracts in 2025, so both have December usage that was unbilled at January 1:
- Unbilled AR: Harry Hood $3,100.00 and Tela $3,800.00. Each is offset to an opening balance equity account. Each equals that customer's December invoice in `prior_period_invoices.csv`.
- Both December invoices are issued January 2 (business day 2) and paid on time in January.
- There are no other opening balances: no billed AR, no contract liability (Famous Mockingbird's contract starts January 1), and no lag estimate.
- Every rollforward in section 6 starts from these balances.

### Check scenarios: fixed inputs and expected results

The generator can randomize how usage is spread across days, but each customer's monthly totals below are fixed, so the results can be checked by hand. The tests assert every expected result.

**Monthly usage totals (received in the month and processed by the cutoff):**

| Customer | Month | Events | Recordings | Flag requests |
|---|---|---|---|---|
| Harry Hood | Jan | 30,000,000 | 300,000 | 20,000,000 |
| Harry Hood | Feb | 30,000,000 | 300,000 | 20,000,000 |
| Harry Hood | Mar | 30,000,000 | 300,000 | 20,000,000 |
| Famous Mockingbird | Jan | 300,000,000 | 1,000,000 | 50,000,000 |
| Famous Mockingbird | Feb | 400,000,000 | 1,500,000 | 60,000,000 |
| Famous Mockingbird | Mar | 350,000,000 | 1,200,000 | 55,000,000 |
| Tela | Jan | 200,000,000 | 600,000 | 15,000,000 |
| Tela | Feb | 120,000,000 | 400,000 | 12,000,000 |
| Tela | Mar | 100,000,000 | 300,000 | 10,000,000 |

Harry Hood's February totals include the customer-side delay batch and the time-zone event. They exclude the duplicates, the lag batch, and the bug-fix reprocess.

**Also:**
- Harry Hood's lag batch: 2,000,000 events received January 31, processed February 6.
- No lag batch arrives for February or March.
- Tela's session replay cap: $1,000 a month.
- Historical lag rate: 1%, applied to Harry Hood only (section 3.2).
- Close threshold: 0.5% of the month's total revenue, measured in aggregate.
- The free tier applies to every customer, including Famous Mockingbird, before usage is priced.

**Expected results:**

| # | Check | Expected |
|---|---|---|
| 1 | Harry Hood January usage at close (events $900 + replay $925 + flags $1,400) | $3,225.00 |
| 1a | Lag estimate accrued January 31 (1% × $3,225) | $32.25 |
| 1b | True-up line on the February invoice (2M events at January's tier 3 rate), and the change in estimate recognized in February ($40.00 − $32.25) | $40.00 and $7.75 |
| 1c | Harry Hood February revenue ($3,225 usage + $32.25 February lag estimate + $7.75 true-up of January's estimate) | $3,265.00 |
| 1d | Harry Hood March revenue ($3,225 usage + $32.25 March estimate − $32.25 reversal of February's estimate, since no February lag batch arrives, + $50 bug fix) | $3,275.00 |
| 2 | Famous Mockingbird credit consumed in Q1 at list price ($11,525 + $15,025 + $13,175) | $39,725.00 |
| 2a | Famous Mockingbird Q1 revenue (× 0.80) | $31,780.00 |
| 2b | Contract liability at March 31 ($80,000 − $31,780, which also equals $60,275 of remaining credit × 0.80) | $48,220.00 |
| 3 | Tela January invoice (events $4,300 + replay capped at $1,000 + flags $1,150; $525 capped) | $6,450.00 |
| 3a | Tela February revenue (usage $4,700, with $125 capped, less the $1,500 concession) | $3,200.00 |
| 3b | Tela January cash received (invoice less the credit memo) | $4,950.00 |
| 3c | Tela March revenue (events $2,300 + replay $925, under the cap + flags $900) | $4,125.00 |
| 4 | March total revenue (Famous Mockingbird $10,540 + Harry Hood $3,275 + Tela $4,125); 0.5% close threshold; the $50 bug fix falls below it | $17,940.00 and $89.70 |
| 5 | Billed AR at March 31 (Tela's February invoice only, 13 days past due) | $4,700.00 |
| 5a | Unbilled AR at March 31 from usage (Harry Hood $3,275 including the $50 bug fix + Tela $4,125; March usage is invoiced April 2) | $7,400.00 |
| 5b | Unbilled AR at March 31 including Harry Hood's $32.25 March lag estimate | $7,432.25 |
| 6 | Total revenue by month: January (Harry Hood $3,257.25 + Famous Mockingbird $9,220 + Tela $6,450) and February (Harry Hood $3,265 + Famous Mockingbird $12,020 + Tela $3,200). March is check 4. | $18,927.25 and $18,485.00 |
| 6a | Q1 total revenue ($18,927.25 + $18,485.00 + $17,940.00) | $55,352.25 |

---

## 6. Outputs (in `output/`)

**Revenue and billing**
1. `invoices.csv`: invoice lines by customer, product, and tier, plus true-up lines
2. `revenue_schedule.csv`: revenue recognized by customer, product, and month, tagged by policy (usage, credit drawdown, concession)
3. `billing_ledger.csv` and `gl_export.csv` (section 4)

**Balance sheet**
4. `rollforwards.csv`:
   - Contract liability: opening + invoiced − recognized = closing
   - Credit balance at list value: opening + purchased − consumed = closing
   - AR, billed and unbilled: opening + billed − cash − credits = closing
   - Opening balances come from `opening_balances.csv` (section 5)
5. `ar_aging.csv` and `collections_log.csv`

**Reconciliation and close**
6. `reconciliation.md`: usage → invoice → revenue → cash per month, with every difference explained by a named reconciling item (free tier, capped, duplicate, lag estimate and true-up, credit drawdown, credit discount, concession, timing of cash)
7. `close_checklist.md`: each revenue close step with an owner, a due day, and an automated pass/fail check (for example, "unbilled AR rollforward ties: PASS")
8. `exceptions.csv`: anything that couldn't be priced, mapped, or explained. Alongside it:
   - `lag_report.csv`: usage received in the month but processed after the cutoff, by customer, with estimate vs actual
   - `passed_adjustments_log.csv`: unusual items recorded in the current month under the close threshold, with the running total (section 3.2)

**Audit**
9. `workpapers/`:
   - **Revenue lead sheet:** GL revenue by account and month, tied to the revenue schedule
   - **Contract liability rollforward:** tied to the GL, with a tickmark legend
   - **Sample tie-outs:** five invoices traced from usage rows → billing ledger → invoice → GL → cash receipt
   - **Controls matrix:** each control in section 7, what it tests, and its result
10. `billing_reply_tela.md` (section 3.4)

---

## 7. Controls the model demonstrates

| Control | What it proves |
|---|---|
| **Completeness** | Raw usage rows = priced + free + capped + duplicate rows. Nothing disappears silently. |
| **Cutoff** | Every row is assigned to a period by `received_ts` (UTC). Usage processed after the cutoff is covered by the lag estimate, and estimate vs actual is tracked each month. |
| **Close threshold** | Unusual items are measured in aggregate against the threshold, and every passed item is logged with a running total. |
| **Pricing accuracy** | Invoice totals are independently recomputed from the rate card and agree. |
| **Integration** | Every billing ledger row is mapped to the GL. GL account totals tie to the billing ledger. |
| **Balance** | Every journal entry balances, and the trial balance is in balance. |
| **Rollforwards** | Each rollforward ties to the GL. Contract liability = remaining credit × 0.80. |
| **Reconciliation** | Zero unexplained difference each month. |

---

## 8. Build order (one commit each)

1. Repo scaffolding, README, this spec, `CLAUDE.md`
2. Synthetic data generator with a fixed random seed, so it's reproducible
3. Pricing engine plus tests. It applies, in order: free tier, graduated tiers, then the billing limit.
4. Billing ledger and invoicing (in arrears, true-ups, credit drawdown, credit memo, payments) plus tests
5. Revenue engine (3.1–3.5) plus tests
6. Account mapping and GL export plus integration controls
7. Rollforwards, AR aging, collections log
8. Reconciliation, close checklist, exceptions
9. Workpapers and the Tela billing reply
10. `run.py`: one command runs the whole quarter's close end to end
11. `MEMO.md`: the policy memo, written by Jonah in his own words

**MVP for the application:** steps 1–8, 10, and 11, plus two pieces of step 9: the Tela billing reply and the controls matrix. The rest of the workpaper pack (lead sheet, tickmarked rollforward, sample tie-outs) comes after submission.

**Acceptance tests that must pass:**
- Every journal entry balances.
- Each rollforward ties to the GL.
- The reconciliation has zero unexplained difference in each month.
- All close checklist checks pass.
- The model matches every expected result in the check scenarios (section 5), which Jonah has recomputed independently in a spreadsheet.

---

## 9. Open judgment calls (interview talking points)

These are left open on purpose. The memo should take a position on each.
- Elect the right-to-invoice practical expedient, or allocate variable consideration to the month (RR 6.4.1.1 vs RR 5.5.1.1)? Does it ever change the numbers here?
- What evidence would let HM stop constraining breakage to zero, and how should it be estimated?
- Should the period follow `received_ts`, and how should the customer terms define billable usage so the invoice and revenue use the same clock?
- How should the historical lag rate and the close threshold be set, and how do they line up with the auditors' performance materiality and "clearly trivial" threshold?
- At what point do concessions like Tela's become a "practice" that must be estimated up front?
- Which of the section 7 controls would an auditor test, and which belong to finance versus billing engineering?
- If the billing ledger and the GL disagree, which one wins, and who fixes it?

---

## 10. Citation check

Every guide reference was read in full against the May 2026 edition.

| Reference | What it supports here |
|---|---|
| RR 3.3.2, ASC 606-10-25-15 | SaaS is a series of distinct monthly services |
| RR 4.3.2, ASC 606-10-32-11 and 32-12 | Constraint on variable consideration, applied to breakage |
| RR 4.3.3.1, Example RR 4-9 | Disputed invoice as a price concession; estimate up front once it's a practice |
| RR 5.5.1, RR 5.5.1.1, ASC 606-10-32-40, Example RR 5-9 | Usage fees allocated to the month they relate to |
| RR 5.5.2, ASC 606-10-32-43 | A concession on delivered service reduces revenue in the period of change |
| RR 6.4.1.1, ASC 606-10-55-18 | Right-to-invoice practical expedient, and why upfront payment undercuts it |
| RR 6.4.3, Example RR 6-10 | Fixed quantity used up → usage-based recognition |
| RR 7.4, ASC 606-10-55-48, Example RR 7-12 | Breakage on prepayments, constraint, escheat |

**Not in this guide:** Receivable vs contract asset presentation (ASC 606-10-45-2 and 45-4) is cited to the ASC directly. PwC covers it in its Financial statement presentation guide (FSP 33). Change in estimate vs error correction for late usage is outside ASC 606 and is cited to ASC 250 directly.

---

## 11. Out of scope for v1 (backlog for v2)

These were considered and parked so v1 stays focused:
- **Platform package with an SLA:** fixed monthly fee recognized straight-line, plus SLA credits as variable consideration (RR 2.9.2, RR 6.4.3, Example RR 6-9, Example RR 4-15)
- **Startup promotional credit:** credit applied against amounts owed reduces the transaction price (RR 4.6)
- **Credit top-ups:** a separate contract at standalone selling price (RR 2.9.2, Example RR 2-15)
- **Rollover of unused credit on renewal:** a possible material right (RR 7.3, Example RR 7-11)
- **Also out of scope:** taxes, multi-currency, commissions (ASC 340-40), disclosures, and any ERP-specific import format

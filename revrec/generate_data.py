"""Synthetic data generator (SPEC section 5, build step 2).

Writes every input CSV into data/. All data is invented.

The random seed only decides how each month's usage is spread across days.
Each customer's monthly totals are fixed by SPEC 5 so results can be checked
by hand. Money and prices are written as exact text (for example "0.00005")
so later steps read them as Decimal, never as floats.

payments.csv is not generated here. It's built in step 4 from rules, once
invoices exist (SPEC 5).
"""

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
YEAR = 2026
MONTHS = [1, 2, 3]  # SPEC 1: model period January-March 2026

EVENTS, REPLAY, FLAGS = "event_analytics", "session_replay", "feature_flags"
PRODUCTS = [EVENTS, REPLAY, FLAGS]

HOOD, MOCK, TELA = "HOOD", "MOCK", "TELA"

# SPEC 5: monthly usage received in the month and processed by the cutoff.
# (events, recordings, flag requests)
MONTHLY_TOTALS = {
    (HOOD, 1): (30_000_000, 300_000, 20_000_000),
    (HOOD, 2): (30_000_000, 300_000, 20_000_000),
    (HOOD, 3): (30_000_000, 300_000, 20_000_000),
    (MOCK, 1): (300_000_000, 1_000_000, 50_000_000),
    (MOCK, 2): (400_000_000, 1_500_000, 60_000_000),
    (MOCK, 3): (350_000_000, 1_200_000, 55_000_000),
    (TELA, 1): (200_000_000, 600_000, 15_000_000),
    (TELA, 2): (120_000_000, 400_000, 12_000_000),
    (TELA, 3): (100_000_000, 300_000, 10_000_000),
}

# SPEC 5: Harry Hood's deliberate problem rows.
# Each is (customer, product, quantity, client_ts, received_ts, processed_ts, source).
LAG_BATCH = (HOOD, EVENTS, 2_000_000,  # received Jan 31, processed Feb 6, after the Feb 4 cutoff
             "2026-01-31T21:58:00Z", "2026-01-31T22:00:00Z", "2026-02-06T09:00:00Z", "normal")
CUSTOMER_DELAY = (HOOD, EVENTS, 500_000,  # generated Jan 31, received Feb 1: February usage
                  "2026-01-31T18:00:00Z", "2026-02-01T02:00:00Z", "2026-02-01T02:30:00Z", "normal")
TIME_ZONE_EVENT = (HOOD, EVENTS, 1,  # 11pm Pacific (UTC-8) on Jan 31 = Feb 1 07:00 UTC: February usage
                   "2026-02-01T07:00:00Z", "2026-02-01T07:00:02Z", "2026-02-01T07:20:00Z", "normal")
BUG_FIX_REPROCESS = (HOOD, EVENTS, 2_500_000,  # January usage reprocessed in March: $50 at Jan tier 3
                     "2026-01-20T12:00:00Z", "2026-01-20T12:00:05Z", "2026-03-10T15:00:00Z",
                     "bug_fix_reprocess")
DUPLICATE_DAYS = [date(2026, 1, 12), date(2026, 1, 25)]  # Harry Hood event rows copied once each

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def days_in_month(year, month):
    first = date(year, month, 1)
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return [first + timedelta(days=i) for i in range((following - first).days)]


def split_total(total, number_of_days, rng):
    """Split a whole-number total across days, varying each day by about +/-15%.

    The pieces always add back to exactly the total: each day gets its share
    rounded down, and the leftover units go one each to the days that were
    rounded down the most.
    """
    weights = [rng.uniform(0.85, 1.15) for _ in range(number_of_days)]
    exact = [total * w / sum(weights) for w in weights]
    amounts = [int(x) for x in exact]
    leftover = total - sum(amounts)
    most_rounded = sorted(range(number_of_days), key=lambda i: exact[i] - amounts[i], reverse=True)
    for i in most_rounded[:leftover]:
        amounts[i] += 1
    assert sum(amounts) == total
    return amounts


def normal_timestamps(day, rng):
    """Received during the day (01:00-22:00 UTC), generated shortly before, processed shortly after."""
    received = datetime(day.year, day.month, day.day, 1) + timedelta(seconds=rng.randint(0, 21 * 3600))
    client = received - timedelta(seconds=rng.randint(1, 300))
    processed = received + timedelta(seconds=rng.randint(300, 5400))
    return client.strftime(TS_FORMAT), received.strftime(TS_FORMAT), processed.strftime(TS_FORMAT)


def build_usage_rows(rng):
    rows = []
    for customer in [HOOD, MOCK, TELA]:
        for month in MONTHS:
            days = days_in_month(YEAR, month)
            for product, total in zip(PRODUCTS, MONTHLY_TOTALS[(customer, month)]):
                if (customer, month, product) == (HOOD, 2, EVENTS):
                    # SPEC 5: Harry Hood's February totals include the two special February rows.
                    total -= CUSTOMER_DELAY[2] + TIME_ZONE_EVENT[2]
                for day, quantity in zip(days, split_total(total, len(days), rng)):
                    client, received, processed = normal_timestamps(day, rng)
                    rows.append([customer, product, quantity, client, received, processed, "normal"])

    for special in [LAG_BATCH, CUSTOMER_DELAY, TIME_ZONE_EVENT, BUG_FIX_REPROCESS]:
        rows.append(list(special))

    rows.sort(key=lambda r: (r[4], r[0], r[1]))  # by received_ts, customer, product
    rows = [[f"EVT-{i:06d}"] + row for i, row in enumerate(rows, start=1)]

    # SPEC 5: two exact duplicate rows (same event_id), deduplicated before pricing (SPEC 3.2).
    duplicates = [list(r) for r in rows
                  if r[1] == HOOD and r[2] == EVENTS and r[7] == "normal"
                  and r[5][:10] in [d.isoformat() for d in DUPLICATE_DAYS]]
    rows += duplicates
    rows.sort(key=lambda r: (r[5], r[1], r[2], r[0]))
    return rows


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def generate(data_dir):
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    # SPEC 2, 3.4: plans, terms, and Tela's $1,000 monthly session replay limit.
    write_csv(data_dir / "customers.csv",
              ["customer_id", "name", "plan_type", "payment_terms", "billing_limits"],
              [[HOOD, "Harry Hood", "payg", "net_30", ""],
               [MOCK, "Famous Mockingbird", "credit", "net_30", ""],
               [TELA, "Tela", "payg", "net_15", "session_replay:1000.00"]])

    # SPEC 3.3: $100,000 of credit for $80,000, term Jan 1 - Dec 31, 2026.
    write_csv(data_dir / "contracts.csv",
              ["contract_id", "customer_id", "contract_type", "effective_from", "effective_to",
               "credit_value", "cash_price"],
              [["CON-HOOD-001", HOOD, "payg", "2025-09-01", "", "", ""],
               ["CON-MOCK-001", MOCK, "credit", "2026-01-01", "2026-12-31", "100000.00", "80000.00"],
               ["CON-TELA-001", TELA, "payg", "2025-11-01", "", "", ""]])

    # SPEC 1: rate card. A tier covers units above tier_floor up to tier_ceiling (blank = no ceiling).
    write_csv(data_dir / "rate_cards.csv",
              ["product", "tier", "tier_floor", "tier_ceiling", "unit_price"],
              [[EVENTS, "free", 0, 1_000_000, "0"],
               [EVENTS, "1", 1_000_000, 5_000_000, "0.00005"],
               [EVENTS, "2", 5_000_000, 25_000_000, "0.00003"],
               [EVENTS, "3", 25_000_000, "", "0.00002"],
               [REPLAY, "free", 0, 5_000, "0"],
               [REPLAY, "1", 5_000, 50_000, "0.005"],
               [REPLAY, "2", 50_000, 250_000, "0.003"],
               [REPLAY, "3", 250_000, "", "0.002"],
               [FLAGS, "free", 0, 1_000_000, "0"],
               [FLAGS, "1", 1_000_000, 10_000_000, "0.0001"],
               [FLAGS, "2", 10_000_000, "", "0.00005"]])

    write_csv(data_dir / "usage_events.csv",
              ["event_id", "customer_id", "product", "quantity", "client_ts", "received_ts",
               "processed_ts", "source"],
              build_usage_rows(rng))

    # SPEC 3.4: $1,500 credit memo on Feb 10 against Tela's January invoice; a price concession.
    write_csv(data_dir / "adjustments.csv",
              ["adjustment_id", "customer_id", "invoice_id", "amount", "date", "reason", "classification"],
              [["ADJ-2026-02-001", TELA, "INV-2026-01-TELA", "1500.00", "2026-02-10",
                "January event volume included a misconfigured test environment", "price_concession"]])

    # SPEC 5: December 2025 invoices, issued January 2 from the opening unbilled AR.
    # December usage is never recognized as revenue in the model period.
    write_csv(data_dir / "prior_period_invoices.csv",
              ["customer_id", "invoice_id", "product", "amount"],
              [[HOOD, "INV-2025-12-HOOD", EVENTS, "850.00"],
               [HOOD, "INV-2025-12-HOOD", REPLAY, "900.00"],
               [HOOD, "INV-2025-12-HOOD", FLAGS, "1350.00"],
               [TELA, "INV-2025-12-TELA", EVENTS, "2100.00"],
               [TELA, "INV-2025-12-TELA", REPLAY, "900.00"],
               [TELA, "INV-2025-12-TELA", FLAGS, "800.00"]])

    # SPEC 5: opening balances at January 1, 2026. Unbilled AR for December usage,
    # offset to opening balance equity. No other opening balances.
    write_csv(data_dir / "opening_balances.csv",
              ["as_of", "account", "customer_id", "debit", "credit", "note"],
              [["2026-01-01", "unbilled_ar", HOOD, "3100.00", "0.00", "December 2025 usage, invoiced January 2"],
               ["2026-01-01", "opening_balance_equity", HOOD, "0.00", "3100.00", "Offset to opening unbilled AR"],
               ["2026-01-01", "unbilled_ar", TELA, "3800.00", "0.00", "December 2025 usage, invoiced January 2"],
               ["2026-01-01", "opening_balance_equity", TELA, "0.00", "3800.00", "Offset to opening unbilled AR"]])

    write_csv(data_dir / "assumptions.csv",
              ["key", "value", "note"],
              [["close_cutoff_business_day", "3", "SPEC 3.2: close cutoff is business day 3"],
               ["lag_rate", "0.01", "SPEC 3.2: historical lag rate, Harry Hood only"],
               ["lag_estimate_customers", "HOOD", "SPEC 3.2: customers whose history shows post-cutoff lag"],
               ["close_threshold_pct", "0.005", "SPEC 3.2: % of the month's total revenue, in aggregate"],
               ["breakage_pct", "0", "SPEC 3.3: expected breakage constrained to zero"],
               ["collections_reminder_days", "5", "SPEC 3.4: reminder at day 5 past due"],
               ["collections_followup_days", "15", "SPEC 3.4: follow-up at day 15 past due"]])

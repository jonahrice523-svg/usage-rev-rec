"""Tests for the synthetic data generator (SPEC section 5)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
import pytest

from revrec import generate_data
from revrec.dates import business_day, next_month


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("data")
    generate_data.generate(folder)
    return folder


def read(data_dir, name):
    # Read everything as text so money never passes through a float.
    return pd.read_csv(data_dir / name, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def usage(data_dir):
    df = read(data_dir, "usage_events.csv")
    df["quantity"] = df["quantity"].astype(int)
    return df


def utc(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


def test_business_days_match_spec():
    # SPEC 1: business day 2 is Feb 3 and Mar 3; business day 3 (close cutoff) is Feb 4 and Mar 4.
    assert business_day(2026, 2, 2) == date(2026, 2, 3)
    assert business_day(2026, 3, 2) == date(2026, 3, 3)
    assert business_day(2026, 2, 3) == date(2026, 2, 4)
    assert business_day(2026, 3, 3) == date(2026, 3, 4)


def test_output_is_reproducible(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    generate_data.generate(first)
    generate_data.generate(second)
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes(), path.name


SPEC_5_TOTALS = [
    # customer, month, events, recordings, flag requests
    ("HOOD", 1, 30_000_000, 300_000, 20_000_000),
    ("HOOD", 2, 30_000_000, 300_000, 20_000_000),
    ("HOOD", 3, 30_000_000, 300_000, 20_000_000),
    ("MOCK", 1, 300_000_000, 1_000_000, 50_000_000),
    ("MOCK", 2, 400_000_000, 1_500_000, 60_000_000),
    ("MOCK", 3, 350_000_000, 1_200_000, 55_000_000),
    ("TELA", 1, 200_000_000, 600_000, 15_000_000),
    ("TELA", 2, 120_000_000, 400_000, 12_000_000),
    ("TELA", 3, 100_000_000, 300_000, 10_000_000),
]


@pytest.mark.parametrize("customer, month, events, recordings, flags", SPEC_5_TOTALS)
def test_monthly_totals_match_spec_5(usage, customer, month, events, recordings, flags):
    # SPEC 5: usage received in the month (UTC) and processed by the close cutoff, after
    # removing duplicates, and excluding the bug-fix reprocess.
    cutoff = business_day(*next_month(2026, month), 3)
    rows = usage.drop_duplicates()
    rows = rows[(rows.customer_id == customer) & (rows.source == "normal")]
    rows = rows[rows.received_ts.str.startswith(f"2026-{month:02d}")]
    rows = rows[rows.processed_ts.str[:10] <= cutoff.isoformat()]
    totals = rows.groupby("product")["quantity"].sum()
    assert totals["event_analytics"] == events
    assert totals["session_replay"] == recordings
    assert totals["feature_flags"] == flags


def test_every_customer_has_a_row_per_product_per_day(usage):
    normal = usage[usage.source == "normal"].drop_duplicates()
    counts = normal.groupby(["customer_id", "product"]).size()
    # 90 days in Q1 2026, plus Harry Hood's three special event rows (lag, delay, time zone).
    assert counts[("HOOD", "event_analytics")] == 90 + 3
    assert (counts.drop(("HOOD", "event_analytics")) == 90).all()


def test_two_exact_duplicates(usage):
    repeated = usage[usage.duplicated("event_id", keep=False)]
    assert repeated.event_id.nunique() == 2
    assert len(repeated) == 4
    assert len(repeated.drop_duplicates()) == 2  # the copies are identical in every field
    assert set(repeated.customer_id) == {"HOOD"}
    assert repeated.received_ts.str.startswith("2026-01").all()


def test_lag_batch(usage):
    # SPEC 5: 2,000,000 events received Jan 31, processed Feb 6, after the Feb 4 cutoff.
    late = usage[(usage.source == "normal")
                 & usage.received_ts.str.startswith("2026-01")
                 & (usage.processed_ts.str[:10] > "2026-02-04")]
    assert len(late) == 1
    row = late.iloc[0]
    assert (row.customer_id, row["product"], row.quantity) == ("HOOD", "event_analytics", 2_000_000)
    assert row.received_ts.startswith("2026-01-31")
    assert row.processed_ts.startswith("2026-02-06")


def test_customer_side_delay(usage):
    # SPEC 5: generated Jan 31, received Feb 1, so it is February usage.
    rows = usage[usage.client_ts.str.startswith("2026-01-31") & usage.received_ts.str.startswith("2026-02-01")]
    assert len(rows) == 1
    assert rows.iloc[0].customer_id == "HOOD"


def test_time_zone_event(usage):
    # SPEC 5: 11pm Pacific on Jan 31 is Feb 1 in UTC. Pacific Standard Time is UTC-8 in January.
    pacific = timezone(timedelta(hours=-8))
    eleven_pm_pacific = datetime(2026, 1, 31, 23, 0, tzinfo=pacific)
    as_utc = eleven_pm_pacific.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = usage[usage.client_ts == as_utc]
    assert as_utc == "2026-02-01T07:00:00Z"
    assert len(rows) == 1
    assert rows.iloc[0].customer_id == "HOOD"
    assert rows.iloc[0].received_ts.startswith("2026-02-01")


def test_bug_fix_reprocess(usage):
    # SPEC 5: $50 of Harry Hood January usage (2,500,000 events) reprocessed in March.
    rows = usage[usage.source == "bug_fix_reprocess"]
    assert len(rows) == 1
    row = rows.iloc[0]
    assert (row.customer_id, row["product"], row.quantity) == ("HOOD", "event_analytics", 2_500_000)
    assert row.received_ts.startswith("2026-01")
    assert row.processed_ts.startswith("2026-03")
    assert set(usage.source) == {"normal", "bug_fix_reprocess"}


def test_row_basics(usage):
    assert (usage.quantity > 0).all()
    assert usage.received_ts.str[:7].isin(["2026-01", "2026-02", "2026-03"]).all()
    for row in usage.itertuples():
        assert utc(row.client_ts) <= utc(row.received_ts) <= utc(row.processed_ts)
    # Apart from the deliberate customer-side delay, no row crosses a month between
    # when it was generated and when it was received.
    crossing = usage[usage.client_ts.str[:7] != usage.received_ts.str[:7]]
    assert len(crossing) == 1


def test_rate_card_matches_spec_1(data_dir):
    rates = read(data_dir, "rate_cards.csv")
    expected = [
        ["event_analytics", "free", "0", "1000000", "0"],
        ["event_analytics", "1", "1000000", "5000000", "0.00005"],
        ["event_analytics", "2", "5000000", "25000000", "0.00003"],
        ["event_analytics", "3", "25000000", "", "0.00002"],
        ["session_replay", "free", "0", "5000", "0"],
        ["session_replay", "1", "5000", "50000", "0.005"],
        ["session_replay", "2", "50000", "250000", "0.003"],
        ["session_replay", "3", "250000", "", "0.002"],
        ["feature_flags", "free", "0", "1000000", "0"],
        ["feature_flags", "1", "1000000", "10000000", "0.0001"],
        ["feature_flags", "2", "10000000", "", "0.00005"],
    ]
    assert rates.values.tolist() == expected
    for price in rates.unit_price:
        Decimal(price)  # every price reads as an exact Decimal


def test_customers_and_contracts(data_dir):
    customers = read(data_dir, "customers.csv").set_index("customer_id")
    assert customers.loc["TELA", "payment_terms"] == "net_15"  # SPEC 3.4
    assert customers.loc["TELA", "billing_limits"] == "session_replay:1000.00"  # SPEC 2, 3.4
    assert customers.loc["HOOD", "payment_terms"] == "net_30"
    assert customers.loc["MOCK", "plan_type"] == "credit"

    contracts = read(data_dir, "contracts.csv").set_index("customer_id")
    credit = contracts.loc["MOCK"]
    assert Decimal(credit.credit_value) == Decimal("100000")  # SPEC 3.3
    assert Decimal(credit.cash_price) == Decimal("80000")
    assert (credit.effective_from, credit.effective_to) == ("2026-01-01", "2026-12-31")


def test_adjustment_and_prior_period_invoice(data_dir):
    adjustments = read(data_dir, "adjustments.csv")
    assert len(adjustments) == 1
    memo = adjustments.iloc[0]
    assert (memo.customer_id, memo.invoice_id, memo.date) == ("TELA", "INV-2026-01-TELA", "2026-02-10")
    assert Decimal(memo.amount) == Decimal("1500.00")
    assert memo.classification == "price_concession"  # SPEC 3.4

    december = read(data_dir, "prior_period_invoices.csv")
    tela = sum(Decimal(a) for a in december[december.customer_id == "TELA"].amount)
    assert tela == Decimal("3800.00")
    assert tela < Decimal("6450.00")  # January (SPEC 5, check 3) is noticeably higher


def test_opening_balances(data_dir):
    # SPEC 5: unbilled AR for December usage at January 1, offset to opening equity; nothing else.
    opening = read(data_dir, "opening_balances.csv")
    assert set(opening.as_of) == {"2026-01-01"}
    assert set(opening.account) == {"unbilled_ar", "opening_balance_equity"}
    assert sum(Decimal(d) for d in opening.debit) == sum(Decimal(c) for c in opening.credit)

    unbilled = opening[opening.account == "unbilled_ar"].set_index("customer_id")
    assert set(unbilled.index) == {"HOOD", "TELA"}

    # Each customer's opening unbilled AR equals its December invoice.
    december = read(data_dir, "prior_period_invoices.csv")
    for customer in ["HOOD", "TELA"]:
        invoice_total = sum(Decimal(a) for a in december[december.customer_id == customer].amount)
        assert Decimal(unbilled.loc[customer, "debit"]) == invoice_total
    assert Decimal(unbilled.loc["TELA", "debit"]) == Decimal("3800.00")


def test_january_business_day_2():
    # SPEC 1: December invoices are issued on business day 2 of January.
    assert business_day(2026, 1, 2) == date(2026, 1, 2)


def test_assumptions(data_dir):
    values = read(data_dir, "assumptions.csv").set_index("key")["value"]
    assert values["close_cutoff_business_day"] == "3"  # SPEC 3.2
    assert Decimal(values["lag_rate"]) == Decimal("0.01")  # SPEC 5
    assert Decimal(values["close_threshold_pct"]) == Decimal("0.005")  # SPEC 5
    assert Decimal(values["breakage_pct"]) == 0  # SPEC 3.3
    assert values["collections_reminder_days"] == "5"  # SPEC 3.4
    assert values["collections_followup_days"] == "15"

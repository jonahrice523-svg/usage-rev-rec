"""Tests for the usage summary (SPEC 3.2) run on the generated data (SPEC 5)."""

from decimal import Decimal

import pytest

from revrec import generate_data
from revrec.pricing import load_billing_limits, load_rate_card, price_monthly_usage
from revrec.usage import load_usage, summarize

from tests.spec5_expected import SPEC_5_DOLLARS


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("data")
    generate_data.generate(folder)
    return folder


@pytest.fixture(scope="module")
def summary(data_dir):
    return summarize(load_usage(data_dir / "usage_events.csv"), cutoff_business_day=3)


def test_monthly_quantities_match_spec_5(summary):
    table = summary.monthly.set_index(["customer_id", "month", "product"])["quantity"]
    for customer, month, (events, recordings, flags), *_ in SPEC_5_DOLLARS:
        key = f"2026-{month:02d}"
        assert table[(customer, key, "event_analytics")] == events
        assert table[(customer, key, "session_replay")] == recordings
        assert table[(customer, key, "feature_flags")] == flags
    assert len(table) == 27  # 3 customers x 3 months x 3 products, nothing else


def test_generated_data_prices_to_spec_5_dollars(data_dir, summary):
    rate_card = load_rate_card(data_dir / "rate_cards.csv")
    limits = load_billing_limits(data_dir / "customers.csv")
    billed = {}
    for customer, month, priced in price_monthly_usage(summary.monthly, rate_card, limits):
        billed[(customer, month)] = billed.get((customer, month), Decimal("0")) + priced.billed_amount
    for customer, month, _, *_, total in SPEC_5_DOLLARS:
        assert billed[(customer, f"2026-{month:02d}")] == Decimal(total)


def test_duplicates_removed_and_listed(summary):
    assert len(summary.duplicates) == 2
    assert set(summary.duplicates.customer_id) == {"HOOD"}


def test_lag_batch_found_in_january(summary):
    # SPEC 5: 2,000,000 events received Jan 31, processed Feb 6, after the Feb 4 cutoff.
    assert len(summary.lag) == 1
    row = summary.lag.iloc[0]
    assert (row.customer_id, row.month, row["product"], row.quantity) == (
        "HOOD", "2026-01", "event_analytics", 2_000_000)


def test_bug_fix_kept_separate(summary):
    assert len(summary.reprocessed) == 1
    row = summary.reprocessed.iloc[0]
    assert (row.customer_id, row.month, row.quantity) == ("HOOD", "2026-01", 2_500_000)


def test_every_row_accounted_for(data_dir, summary):
    # SPEC 7 completeness, in units: raw = priced + lag + reprocessed + duplicates.
    raw = load_usage(data_dir / "usage_events.csv")
    accounted = (summary.monthly.quantity.sum() + summary.lag.quantity.sum()
                 + summary.reprocessed.quantity.sum() + summary.duplicates.quantity.sum())
    assert accounted == raw.quantity.sum()

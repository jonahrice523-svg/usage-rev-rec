"""Tests for the pricing engine (SPEC 1, 3.4, 3.5; expected results from SPEC 5)."""

from decimal import Decimal

import pytest

from revrec import generate_data
from revrec.pricing import load_billing_limits, load_rate_card, price, price_additional
from tests.spec5_expected import SPEC_5_DOLLARS

D = Decimal


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("data")
    generate_data.generate(folder)
    return folder


@pytest.fixture(scope="module")
def rate_card(data_dir):
    return load_rate_card(data_dir / "rate_cards.csv")


@pytest.fixture(scope="module")
def limits(data_dir):
    return load_billing_limits(data_dir / "customers.csv")


def price_month(customer, quantities, rate_card, limits):
    caps = limits.get(customer, {})
    products = ["event_analytics", "session_replay", "feature_flags"]
    return {p: price(p, q, rate_card, caps.get(p)) for p, q in zip(products, quantities)}


@pytest.mark.parametrize("customer, month, quantities, events, replay_list, replay_billed, flags, total",
                         SPEC_5_DOLLARS)
def test_spec_5_usage_totals_in_dollars(rate_card, limits, customer, month, quantities,
                                        events, replay_list, replay_billed, flags, total):
    priced = price_month(customer, quantities, rate_card, limits)
    assert priced["event_analytics"].billed_amount == D(events)
    assert priced["session_replay"].list_amount == D(replay_list)
    assert priced["session_replay"].billed_amount == D(replay_billed)
    assert priced["feature_flags"].billed_amount == D(flags)
    assert sum(p.billed_amount for p in priced.values()) == D(total)


def test_famous_mockingbird_q1_credit_consumed(rate_card, limits):
    # SPEC 5, check 2: $11,525 + $15,025 + $13,175 = $39,725 at list price.
    total = sum(sum(p.billed_amount for p in price_month("MOCK", q, rate_card, limits).values())
                for c, m, q, *_ in SPEC_5_DOLLARS if c == "MOCK")
    assert total == D("39725.00")


# --- Billing limit (SPEC 1, 3.4) ---

def test_tela_january_replay_capped_after_tiers(rate_card, limits):
    # SPEC 3.4: January replay prices at $1,525; Tela is billed $1,000; $525 is never owed.
    replay = price("session_replay", 600_000, rate_card, limits["TELA"]["session_replay"])
    assert replay.list_amount == D("1525.00")
    assert replay.billed_amount == D("1000.00")
    assert replay.capped_amount == D("525.00")
    # The cap doesn't remove units from the tier detail: all 600,000 are priced at list.
    assert sum(line.units for line in replay.tier_lines) == 600_000
    assert [line.amount for line in replay.tier_lines] == [D("0.00"), D("225.00"), D("600.00"), D("700.00")]


def test_tela_february_replay_capped(rate_card, limits):
    # SPEC 5, check 3a: $125 capped.
    replay = price("session_replay", 400_000, rate_card, limits["TELA"]["session_replay"])
    assert (replay.list_amount, replay.billed_amount, replay.capped_amount) == (D("1125"), D("1000"), D("125"))


def test_cap_is_compared_with_the_tiered_dollar_amount(rate_card):
    # The limit applies to what the usage costs after the free tier and graduated tiers.
    # Pricing all 600,000 recordings flat at tier 1 would give $3,000 and $2,000 capped;
    # the spec's $525 only comes from capping the graduated $1,525.
    flat_tier_1 = 600_000 * D("0.005")
    assert flat_tier_1 == D("3000")
    replay = price("session_replay", 600_000, rate_card, cap=D("1000.00"))
    assert replay.capped_amount == replay.list_amount - D("1000.00") == D("525.00")


def test_usage_exactly_at_the_cap_is_not_capped(rate_card):
    # 337,500 recordings: $825 through tier 2, then 87,500 x $0.002 = $175, so exactly $1,000.
    replay = price("session_replay", 337_500, rate_card, cap=D("1000.00"))
    assert replay.list_amount == D("1000.00")
    assert replay.billed_amount == D("1000.00")
    assert replay.capped_amount == D("0.00")


def test_tela_march_replay_under_the_cap(rate_card, limits):
    replay = price("session_replay", 300_000, rate_card, limits["TELA"]["session_replay"])
    assert (replay.list_amount, replay.billed_amount, replay.capped_amount) == (D("925"), D("925"), D("0"))


def test_limit_applies_only_to_tela_session_replay(limits):
    assert limits["TELA"] == {"session_replay": D("1000.00")}
    assert limits["HOOD"] == {}
    assert limits["MOCK"] == {}


# --- Free tier (SPEC 3.5) and tier boundaries (SPEC 1) ---

def test_usage_within_the_free_tier_is_free_but_counted(rate_card):
    priced = price("event_analytics", 1_000_000, rate_card)
    assert priced.billed_amount == D("0.00")
    assert priced.free_units == 1_000_000


def test_famous_mockingbird_gets_the_free_tier(rate_card, limits):
    # SPEC 1: the free tier applies before usage draws down credit.
    events = price_month("MOCK", (300_000_000, 1_000_000, 50_000_000), rate_card, limits)["event_analytics"]
    assert events.free_units == 1_000_000
    assert events.tier_lines[0].amount == D("0.00")


@pytest.mark.parametrize("product, quantity, expected", [
    ("event_analytics", 1_000_000, "0.00"),
    ("event_analytics", 1_000_001, "0.00"),     # one unit at $0.00005 rounds to $0.00
    ("event_analytics", 5_000_000, "200.00"),   # 4M x $0.00005
    ("event_analytics", 25_000_000, "800.00"),  # + 20M x $0.00003
    ("event_analytics", 26_000_000, "820.00"),  # + 1M x $0.00002
    ("session_replay", 5_000, "0.00"),
    ("session_replay", 50_000, "225.00"),
    ("session_replay", 250_000, "825.00"),
    ("feature_flags", 1_000_000, "0.00"),
    ("feature_flags", 10_000_000, "900.00"),
    ("feature_flags", 11_000_000, "950.00"),
])
def test_tier_boundaries(rate_card, product, quantity, expected):
    assert price(product, quantity, rate_card).list_amount == D(expected)


def test_tier_lines_round_half_up_to_cents(rate_card):
    # 100 events in tier 1 = 100 x $0.00005 = $0.005, which rounds half-up to $0.01.
    priced = price("event_analytics", 1_000_100, rate_card)
    assert priced.tier_lines[1].amount == D("0.01")


# --- Extra units priced on top of a month's usage (SPEC 5, checks 1b and 1d) ---

def test_lag_true_up_at_januarys_tier_3_rate(rate_card):
    # 2M lag events on top of Harry Hood's 30M January events = $40.00.
    true_up = price_additional("event_analytics", 30_000_000, 2_000_000, rate_card)
    assert true_up.billed_amount == D("40.00")
    assert [line.tier for line in true_up.tier_lines] == ["3"]


def test_bug_fix_reprocess_at_januarys_tier_3_rate(rate_card):
    # 2.5M events on top of January's 30M + 2M lag batch = $50.00.
    bug_fix = price_additional("event_analytics", 32_000_000, 2_500_000, rate_card)
    assert bug_fix.billed_amount == D("50.00")


def test_extra_units_can_cross_a_tier(rate_card):
    # 2M extra on top of 24M: 1M at tier 2 ($30) + 1M at tier 3 ($20).
    extra = price_additional("event_analytics", 24_000_000, 2_000_000, rate_card)
    assert extra.billed_amount == D("50.00")
    # Same answer as pricing the month with and without the extra units.
    assert extra.billed_amount == (price("event_analytics", 26_000_000, rate_card).list_amount
                                   - price("event_analytics", 24_000_000, rate_card).list_amount)

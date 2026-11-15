"""Pricing engine (SPEC 1, build step 3).

Prices one product's usage for one month, in the order SPEC 8 sets:
free tier, then graduated tiers, then the billing limit.

All math is exact Decimal. Each tier line is rounded to cents once, because
tier lines become invoice lines (SPEC 6; CLAUDE.md: round only at the
invoice-line level). Rounding is half-up: $0.005 becomes $0.01.
"""

import csv
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Tier:
    tier: str            # "free", "1", "2", "3"
    floor: int           # the tier covers units above floor...
    ceiling: int | None  # ...up to ceiling (None = no ceiling)
    unit_price: Decimal


@dataclass(frozen=True)
class TierLine:
    tier: str
    units: int
    unit_price: Decimal
    amount: Decimal  # rounded to cents


@dataclass(frozen=True)
class PricedUsage:
    product: str
    quantity: int
    tier_lines: list
    list_amount: Decimal    # what the usage costs after the free tier and tiers
    billed_amount: Decimal  # the lower of list_amount and the billing limit
    capped_amount: Decimal  # list_amount - billed_amount; never owed (SPEC 3.4)

    @property
    def free_units(self):
        return sum(line.units for line in self.tier_lines if line.tier == "free")


def load_rate_card(path):
    """Read rate_cards.csv into {product: [Tier, ...]} in tier order."""
    rate_card = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ceiling = int(row["tier_ceiling"]) if row["tier_ceiling"] else None
            tier = Tier(row["tier"], int(row["tier_floor"]), ceiling, Decimal(row["unit_price"]))
            rate_card.setdefault(row["product"], []).append(tier)
    return rate_card


def load_billing_limits(path):
    """Read customers.csv billing limits into {customer_id: {product: Decimal cap}}.

    The field looks like "session_replay:1000.00"; several limits are separated by ";".
    """
    limits = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            caps = {}
            for item in filter(None, row["billing_limits"].split(";")):
                product, amount = item.split(":")
                caps[product] = Decimal(amount)
            limits[row["customer_id"]] = caps
    return limits


def tier_lines(quantity, tiers, already_used=0):
    """Split units across tiers. SPEC 1: graduated, each unit at its own tier's rate.

    already_used lets extra units be priced on top of usage already counted in
    the month, so they land in the right tier (used for true-ups).
    """
    start, end = already_used, already_used + quantity
    lines = []
    for tier in tiers:
        top = end if tier.ceiling is None else min(end, tier.ceiling)
        bottom = max(start, tier.floor)
        units = top - bottom
        if units > 0:
            lines.append(TierLine(tier.tier, units, tier.unit_price, to_cents(units * tier.unit_price)))
    return lines


def price(product, quantity, rate_card, cap=None):
    """Price one product's monthly usage."""
    # SPEC 1, 3.5: free tier first (priced at $0, units still counted), then graduated tiers.
    lines = tier_lines(quantity, rate_card[product])
    list_amount = sum((line.amount for line in lines), Decimal("0.00"))

    # SPEC 1, 3.4: the billing limit is applied after the tiers, to the dollar amount.
    # Usage above the cap is never billed and never recognized.
    billed_amount = list_amount if cap is None else min(list_amount, cap)
    return PricedUsage(product, quantity, lines, list_amount, billed_amount, list_amount - billed_amount)


def price_additional(product, already_used, extra, rate_card):
    """Price extra units on top of a month's usage at that month's tier rates.

    SPEC 5, checks 1b and 1d: the lag true-up and the bug-fix reprocess are priced
    at January's rates on top of January's usage. No billing limit applies here:
    in this model only Harry Hood has late usage, and he has no limit.
    """
    lines = tier_lines(extra, rate_card[product], already_used)
    amount = sum((line.amount for line in lines), Decimal("0.00"))
    return PricedUsage(product, extra, lines, amount, amount, Decimal("0.00"))


def price_monthly_usage(monthly, rate_card, limits):
    """Price every customer, month, and product in a monthly usage table.

    monthly has columns customer_id, month, product, quantity (see usage.py).
    Returns a list of (customer_id, month, PricedUsage).
    """
    results = []
    for row in monthly.itertuples(index=False):
        cap = limits.get(row.customer_id, {}).get(row.product)
        results.append((row.customer_id, row.month, price(row.product, int(row.quantity), rate_card, cap)))
    return results

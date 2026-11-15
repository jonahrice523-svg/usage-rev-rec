"""Revenue engine (SPEC 3.1-3.5, build step 5).

Adds the revenue engine's own entries to the billing ledger (origin = revenue_engine):
- lag_estimate at each month end, and its reversal on the 1st of the next month (SPEC 3.2)
- credit_revenue_recognized for Famous Mockingbird at $0.80 per $1.00 of credit (SPEC 3.3)

Then builds output/revenue_schedule.csv from the ledger: revenue by customer, product,
and month, tagged by policy, with a ledger_id trail.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from revrec.billing import ZERO, ledger_event, load_inputs, month_after, month_end, number_ledger, read_text_csv

CENT = Decimal("0.01")
Q1_MONTHS = ["2026-01", "2026-02", "2026-03"]

SCHEDULE_COLUMNS = ["month", "customer_id", "product", "policy", "amount", "spec_ref", "ledger_ids", "note"]


def to_cents(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Assumptions:
    lag_rate: Decimal
    lag_customers: list
    close_threshold_pct: Decimal
    breakage_pct: Decimal


def load_assumptions(data_dir):
    values = read_text_csv(Path(data_dir) / "assumptions.csv").set_index("key")["value"]
    return Assumptions(
        lag_rate=Decimal(values["lag_rate"]),
        lag_customers=values["lag_estimate_customers"].split(";"),
        close_threshold_pct=Decimal(values["close_threshold_pct"]),
        breakage_pct=Decimal(values["breakage_pct"]),
    )


def total(rows):
    return sum((Decimal(a) for a in rows.amount), ZERO)


# --- Revenue engine ledger events ---------------------------------------------------

def lag_estimate_events(ledger, assumptions):
    """SPEC 3.2: at close, accrue lag rate x the month's processed usage revenue, by customer.

    Each estimate reverses on the 1st of the next month; actual late usage is recognized
    when it's rated, so the difference lands in the month it becomes known (ASC 250 change
    in estimate, not an error correction).
    """
    events = []
    for customer in assumptions.lag_customers:
        for month in Q1_MONTHS:
            rated = ledger[(ledger.event_type == "usage_rated") & (ledger.customer_id == customer)
                           & (ledger.usage_month == month)]
            estimate = to_cents(assumptions.lag_rate * total(rated))
            events.append(ledger_event(month_end(month), "lag_estimate", customer, estimate, "revenue_engine",
                                       usage_month=month,
                                       description=f"Lag estimate: {assumptions.lag_rate * 100:g}% "
                                                   f"of {month} processed usage revenue"))
            events.append(ledger_event(date.fromisoformat(month_after(month) + "-01"), "lag_estimate_reversal",
                                       customer, estimate, "revenue_engine", usage_month=month,
                                       description=f"Reverse {month} lag estimate"))
    return events


def credit_revenue_events(ledger, contracts):
    """SPEC 3.3: revenue = credit consumed at list x (cash price / credit value) = x 0.80.

    Cumulative method: revenue to date = rate x credit consumed to date, rounded to cents,
    less revenue already recognized. The contract liability then always equals remaining
    credit x 0.80 (SPEC 7).
    """
    events = []
    for contract in contracts[contracts.contract_type == "credit"].itertuples():
        rate = Decimal(contract.cash_price) / Decimal(contract.credit_value)  # 80,000 / 100,000 = 0.80
        drawdowns = ledger[(ledger.event_type == "credit_drawdown") & (ledger.customer_id == contract.customer_id)]
        for product, rows in drawdowns.groupby("product", sort=True):
            consumed, recognized = ZERO, ZERO
            for row in rows.sort_values("event_date").itertuples():
                consumed += Decimal(row.amount)
                revenue = to_cents(rate * consumed) - recognized
                recognized += revenue
                events.append(ledger_event(row.event_date, "credit_revenue_recognized", row.customer_id, revenue,
                                           "revenue_engine", product=product, usage_month=row.usage_month,
                                           list_amount=row.amount,
                                           description=f"Credit consumed at list x {rate}"))
    return events


def add_revenue_events(ledger, inputs, assumptions):
    events = ledger.to_dict("records")
    events += lag_estimate_events(ledger, assumptions)
    events += credit_revenue_events(ledger, inputs.contracts)
    return number_ledger(events)


# --- Revenue schedule ----------------------------------------------------------------

def evaluate_unusual_items(items, month_revenue, threshold_pct):
    """SPEC 3.2: measure the month's unusual items in aggregate against the close threshold.

    Returns (record_in_month, threshold). Above the threshold, the items aren't recorded
    automatically: they are exceptions to evaluate as a possible prior-period error (ASC 250).
    """
    threshold = to_cents(threshold_pct * month_revenue)
    return abs(sum(items, ZERO)) < threshold, threshold


def build_revenue_schedule(ledger, inputs, assumptions):
    """Revenue by month, customer, product, and policy, from the ledger. Returns (schedule, exceptions)."""
    reprocessed_ids = set(inputs.usage.reprocessed.event_id)
    concessions = inputs.adjustments.set_index("adjustment_id")
    rows = []

    def add(row, policy, amount, spec_ref, product=None, note=""):
        rows.append({"month": row.event_date[:7], "customer_id": row.customer_id,
                     "product": row.product if product is None else product, "policy": policy,
                     "amount": amount, "spec_ref": spec_ref, "ledger_id": row.ledger_id, "note": note})

    in_q1 = ledger[ledger.event_date.str[:7].isin(Q1_MONTHS)]
    for row in in_q1.itertuples():
        amount = Decimal(row.amount)
        if row.event_type == "usage_rated":
            add(row, "usage", amount, "3.1")  # billed amount: free tier and cap already excluded (3.4, 3.5)
        elif row.event_type == "late_usage_rated" and row.source_ref in reprocessed_ids:
            add(row, "unusual_item", amount, "3.2", note=row.description)
        elif row.event_type == "late_usage_rated":
            add(row, "lag_true_up", amount, "3.2", note="Actual late usage, rated when processed")
        elif row.event_type == "lag_estimate":
            add(row, "lag_estimate", amount, "3.2", product="")
        elif row.event_type == "lag_estimate_reversal":
            add(row, "lag_estimate_reversal", -amount, "3.2", product="")
        elif row.event_type == "credit_revenue_recognized":
            add(row, "credit_drawdown", amount, "3.3")
        elif row.event_type == "credit_memo" and concessions.loc[row.source_ref, "classification"] == "price_concession":
            # SPEC 3.4: contra-revenue in the period the price changes, on the product in adjustments.csv.
            add(row, "concession", -amount, "3.4", note=row.source_ref)

    schedule = pd.DataFrame(rows)

    # SPEC 3.2: unusual items vs the close threshold, in aggregate per month.
    exceptions = []
    for month in Q1_MONTHS:
        items = schedule[(schedule.month == month) & (schedule.policy == "unusual_item")]
        if items.empty:
            continue
        month_revenue = sum(schedule[schedule.month == month].amount, ZERO)
        recorded, threshold = evaluate_unusual_items(list(items.amount), month_revenue, assumptions.close_threshold_pct)
        if recorded:
            schedule.loc[items.index, "note"] += f" (below the {month} close threshold of ${threshold:,.2f})"
        else:
            exceptions.append({"month": month, "amount": sum(items.amount, ZERO), "threshold": threshold,
                               "ledger_ids": ";".join(items.ledger_id)})
            schedule = schedule.drop(items.index)

    # SPEC 3.3: breakage is reassessed each month and constrained to zero. Any other
    # percentage would need a recognition pattern the spec doesn't define yet.
    if assumptions.breakage_pct != 0:
        raise ValueError("SPEC 3.3 constrains expected breakage to zero; a nonzero estimate needs a policy decision")
    breakage = [{"month": month, "customer_id": contract.customer_id, "product": "", "policy": "breakage",
                 "amount": ZERO, "spec_ref": "3.3", "ledger_id": "",
                 "note": "Expected breakage constrained to zero (SPEC 3.3)"}
                for contract in inputs.contracts[inputs.contracts.contract_type == "credit"].itertuples()
                for month in Q1_MONTHS]
    schedule = pd.concat([schedule, pd.DataFrame(breakage)], ignore_index=True)

    schedule = (schedule.groupby(["month", "customer_id", "product", "policy", "spec_ref", "note"], as_index=False)
                .agg(amount=("amount", lambda s: sum(s, ZERO)), ledger_ids=("ledger_id", lambda s: ";".join(filter(None, s)))))
    schedule["amount"] = schedule.amount.map(lambda a: f"{a:.2f}")
    return schedule[SCHEDULE_COLUMNS].sort_values(["month", "customer_id", "product", "policy"]).reset_index(drop=True), exceptions


def revenue_by(schedule, *keys):
    """Sum the schedule's amounts by the given columns, as Decimals."""
    out = {}
    for row in schedule.itertuples():
        key = tuple(getattr(row, k) for k in keys)
        key = key[0] if len(key) == 1 else key
        out[key] = out.get(key, ZERO) + Decimal(row.amount)
    return out


def run_revenue(data_dir, output_dir, billing_ledger):
    inputs = load_inputs(data_dir)
    assumptions = load_assumptions(data_dir)
    ledger = add_revenue_events(billing_ledger, inputs, assumptions)
    schedule, exceptions = build_revenue_schedule(ledger, inputs, assumptions)
    ledger.to_csv(Path(output_dir) / "billing_ledger.csv", index=False, lineterminator="\n")
    schedule.to_csv(Path(output_dir) / "revenue_schedule.csv", index=False, lineterminator="\n")
    return ledger, schedule, exceptions

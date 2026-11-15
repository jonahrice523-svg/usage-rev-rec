"""Monthly reconciliation: usage -> invoice -> revenue -> cash (SPEC 6 item 6, SPEC 7; build step 8).

Four bridges per month. Every difference is a named reconciling item, and each bridge
ends with an unexplained difference that must be $0.00 (units for bridge A).

A. Unit completeness: raw units received = free tier + tiered + duplicates + late
B. Usage -> invoice:  usage at list - capped - drawn from credit + late usage = usage invoices
C. Usage -> revenue:  usage at list - capped - credit discount + lag estimate - reversal
                      + late usage - concession = revenue (revenue schedule and GL)
D. Revenue -> cash:   revenue - change in unbilled AR - change in billed AR
                      + change in contract liability = cash received (GL 1000)
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd

from revrec.billing import MONTH_NAMES, invoice_totals
from revrec.pricing import price_monthly_usage
from revrec.revenue import revenue_by

ZERO = Decimal("0.00")
MONTHS = ["2026-01", "2026-02", "2026-03"]


@dataclass
class Bridge:
    key: str           # "A", "B", "C", "D"
    title: str
    explanation: str   # one sentence for a reader who won't run the code
    unit: str          # "units" or "$"
    lines: list = field(default_factory=list)  # (label, amount)
    result_label: str = ""
    computed: Decimal = ZERO   # start + reconciling items
    actual: Decimal = ZERO     # the independent figure it must agree to
    detail: list = field(default_factory=list)  # bridge A: per customer/product rows
    note: str = ""
    gl_revenue: Decimal = None  # bridge C only: revenue per the GL, which must also agree

    @property
    def unexplained(self):
        return self.actual - self.computed


def ledger_sum(ledger, month, *event_types, by="event_date"):
    rows = ledger[(ledger[by].str[:7] == month) & ledger.event_type.isin(event_types)]
    return sum((Decimal(a) for a in rows.amount), ZERO)


def rf_line(rollforwards, name, customer, month, line):
    rows = rollforwards[(rollforwards.rollforward == name) & (rollforwards.customer_id == customer)
                        & (rollforwards.month == month) & (rollforwards.line == line)]
    return Decimal(rows.amount.iloc[0])


def unit_bridge(month, raw_usage, usage_summary, priced):
    """Bridge A, by customer and product."""
    raw = raw_usage.copy()
    raw["month"] = raw.received_ts.str[:7]
    late = pd.concat([usage_summary.lag, usage_summary.reprocessed])
    dups = usage_summary.duplicates.copy()
    dups["month"] = dups.received_ts.str[:7]
    rows, totals = [], [0, 0, 0, 0, 0]
    for customer, m, p in priced:
        if m != month:
            continue
        pick = lambda df: int(df[(df.month == month) & (df.customer_id == customer) & (df["product"] == p.product)].quantity.sum())
        received, duplicates, late_units = pick(raw), pick(dups), pick(late)
        free = p.free_units
        tiered = p.quantity - free
        rows.append((customer, p.product, received, free, tiered, duplicates, late_units,
                     received - free - tiered - duplicates - late_units))
        for i, v in enumerate([received, free, tiered, duplicates, late_units]):
            totals[i] += v
    bridge = Bridge("A", "Unit completeness",
                    "Every unit of usage received in the month is accounted for as free-tier, tiered (priced), "
                    "a duplicate that is never billed, or late usage priced when it's processed.", "units")
    bridge.lines = [("Free-tier units, no charge (SPEC 3.5)", totals[1]),
                    ("Tiered units priced at close", totals[2]),
                    ("Duplicate units removed, never billed (SPEC 3.2)", totals[3]),
                    ("Late units processed after the cutoff (SPEC 3.2)", totals[4])]
    bridge.result_label = "Units received in the month (raw usage file, including duplicates)"
    bridge.computed = Decimal(totals[1] + totals[2] + totals[3] + totals[4])
    bridge.actual = Decimal(totals[0])
    bridge.detail = rows
    return bridge


def build_bridges(month, raw_usage, usage_summary, priced, ledger, invoices, schedule, gl, chart, rollforwards,
                  credit_customers):
    from revrec.gl import revenue_from_gl

    month_priced = [(c, p) for c, m, p in priced if m == month]
    usage_list = sum((p.list_amount for _, p in month_priced), ZERO)
    capped = sum((p.capped_amount for _, p in month_priced), ZERO)
    drawn = sum((p.billed_amount for c, p in month_priced if c in credit_customers), ZERO)
    late = ledger_sum(ledger, month, "late_usage_rated")
    bridges = [unit_bridge(month, raw_usage, usage_summary, priced)]

    usage_invoices = invoices[(invoices.usage_month == month)
                              & invoices.line_types.map(lambda t: "credit_purchase" not in t)]
    b = Bridge("B", "Usage to invoice",
               "Usage priced at list becomes the month's usage invoices after removing capped amounts and usage "
               "drawn from prepaid credit, and adding late usage billed on this month's invoice.", "$")
    b.lines = [("Usage at list price, after the free tier", usage_list),
               ("Capped by the billing limit, never owed (SPEC 3.4)", -capped),
               ("Drawn from prepaid credit, not invoiced (SPEC 3.3)", -drawn),
               ("Late usage rated this month and billed on this invoice (SPEC 3.2)", late)]
    b.result_label = f"Usage invoices for {MONTH_NAMES[month]} usage"
    b.computed = usage_list - capped - drawn + late
    b.actual = sum(usage_invoices.total, ZERO)
    bridges.append(b)

    discount = ledger_sum(ledger, month, "credit_drawdown") - ledger_sum(ledger, month, "credit_revenue_recognized")
    estimate = ledger_sum(ledger, month, "lag_estimate")
    reversal = ledger_sum(ledger, month, "lag_estimate_reversal")
    concession = ledger_sum(ledger, month, "credit_memo")
    c = Bridge("C", "Usage to revenue",
               "Usage priced at list becomes recognized revenue after removing capped amounts and the 20% credit "
               "discount, adding the lag estimate net of last month's reversal and late usage, and deducting "
               "price concessions.", "$")
    c.lines = [("Usage at list price, after the free tier", usage_list),
               ("Capped by the billing limit, never revenue (SPEC 3.4)", -capped),
               ("Credit discount: drawdown at list less revenue at 0.80 (SPEC 3.3)", -discount),
               ("Lag estimate at month end (SPEC 3.2)", estimate),
               ("Reversal of last month's lag estimate (SPEC 3.2)", -reversal),
               ("Late usage rated this month: lag true-up or unusual item (SPEC 3.2)", late),
               ("Price concession, contra-revenue (SPEC 3.4)", -concession)]
    c.result_label = "Revenue per the revenue schedule"
    c.computed = usage_list - capped - discount + estimate - reversal + late - concession
    c.actual = revenue_by(schedule, "month").get(month, ZERO)
    gl_revenue = revenue_from_gl(gl, chart, "month").get(month, ZERO)
    c.gl_revenue = gl_revenue
    c.note = (f"Revenue per the GL (accounts 4000 + 4010 + 4100 − 4900): {gl_revenue:,.2f}, "
              f"{'which agrees with the revenue schedule' if gl_revenue == c.actual else 'which does NOT agree'}.")
    bridges.append(c)

    d_unbilled = rf_line(rollforwards, "unbilled_ar", "ALL", month, "closing") - rf_line(rollforwards, "unbilled_ar", "ALL", month, "opening")
    d_billed = rf_line(rollforwards, "billed_ar", "ALL", month, "closing") - rf_line(rollforwards, "billed_ar", "ALL", month, "opening")
    d_liability = sum((rf_line(rollforwards, "contract_liability", cust, month, "closing")
                       - rf_line(rollforwards, "contract_liability", cust, month, "opening")
                       for cust in credit_customers), ZERO)
    revenue = c.actual
    cash_rows = gl[(gl.account == "1000") & (gl.entry_date.str[:7] == month)]
    d = Bridge("D", "Revenue to cash",
               "Recognized revenue becomes cash received after adjusting for revenue not yet billed or not yet "
               "collected, and for prepaid cash received ahead of revenue.", "$")
    d.lines = [("Revenue", revenue),
               ("Timing of cash: increase in unbilled AR", -d_unbilled),
               ("Timing of cash: increase in billed AR", -d_billed),
               ("Prepaid credit: increase in contract liability (SPEC 3.3)", d_liability)]
    d.result_label = "Cash received (GL 1000)"
    d.computed = revenue - d_unbilled - d_billed + d_liability
    d.actual = sum((Decimal(x) - Decimal(y) for x, y in zip(cash_rows.debit, cash_rows.credit)), ZERO)
    bridges.append(d)
    return bridges


def fmt(amount, unit):
    if amount is None:
        return ""
    if unit == "units":
        return f"{int(amount):,}"
    return f"({-amount:,.2f})" if amount < 0 else f"{amount:,.2f}"


def write_markdown(results, path):
    out = ["# Monthly reconciliation: usage to invoice to revenue to cash", "",
           "Hedgehog Metrics, Inc. (synthetic data). Q1 2026. Generated by `python run.py`.", "",
           "Each month has four bridges. Every difference is a named reconciling item with its SPEC "
           "reference. Each bridge totals its items, compares the total with an independent figure "
           "(the usage file, the invoices, the revenue schedule, or cash in the GL), and shows the "
           "unexplained difference, which must be zero.", "",
           "Amounts in parentheses are deductions.", ""]
    for month, bridges in results.items():
        out += [f"## {MONTH_NAMES[month]} 2026", ""]
        for b in bridges:
            amount_header = "Units" if b.unit == "units" else "Amount ($)"
            out += [f"### {b.key}. {b.title}", "", b.explanation, "", f"| Item | {amount_header} |", "|---|---:|"]
            for label, amount in b.lines:
                out.append(f"| {label} | {fmt(amount, b.unit)} |")
            out.append(f"| **Total of the items above** | **{fmt(b.computed, b.unit)}** |")
            out.append(f"| **{b.result_label}** | **{fmt(b.actual, b.unit)}** |")
            zero = "0" if b.unit == "units" else "$0.00"
            shown = fmt(b.unexplained, b.unit) if b.unexplained else zero
            out += ["", f"**Unexplained difference: {shown}**", ""]
            if b.note:
                out += [b.note, ""]
            if b.detail:
                out += ["<details><summary>By customer and product</summary>", "",
                        "| Customer | Product | Received | Free tier | Tiered | Duplicates | Late | Unexplained |",
                        "|---|---|---:|---:|---:|---:|---:|---:|"]
                for row in b.detail:
                    out.append("| " + " | ".join([row[0], row[1]] + [f"{v:,}" for v in row[2:]]) + " |")
                out += ["", "</details>", ""]
    Path(path).write_text("\n".join(out), encoding="utf-8", newline="\n")


def run_reconciliation(output_dir, raw_usage, inputs, ledger, lines, schedule, gl, chart, rollforwards):
    priced = price_monthly_usage(inputs.usage.monthly, inputs.rate_card, inputs.limits)
    invoices = invoice_totals(lines)
    credit_customers = list(inputs.contracts[inputs.contracts.contract_type == "credit"].customer_id)
    results = {m: build_bridges(m, raw_usage, inputs.usage, priced, ledger, invoices, schedule, gl, chart,
                                rollforwards, credit_customers) for m in MONTHS}
    write_markdown(results, Path(output_dir) / "reconciliation.md")
    return results

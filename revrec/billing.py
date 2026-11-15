"""Invoicing and the billing ledger (SPEC 4, build step 4).

Invoices (output/invoices.csv), one row per invoice line:
- December 2025 invoices, issued January 2 from the opening unbilled AR (SPEC 5)
- Famous Mockingbird's annual credit invoice, January 1 (SPEC 3.3)
- monthly usage invoices in arrears on business day 2, by product and tier (SPEC 1, 6),
  with late usage on the invoice for the month it is processed (SPEC 3.2, 5)

Billing ledger (output/billing_ledger.csv), one row per billing event with a fixed
ledger_id. Amounts are always positive; the event type says what happened, and the
account mapping (step 6) decides debits and credits.

No revenue rules live here. The 0.80 credit rate, the lag estimate, and the
concession's revenue timing are the revenue engine's job (step 5).
"""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from revrec.dates import business_day, next_month
from revrec.pricing import load_billing_limits, load_rate_card, price, price_additional
from revrec.usage import load_usage, summarize

ZERO = Decimal("0.00")
PAYG_CUSTOMERS = ["HOOD", "TELA"]
USAGE_MONTHS = ["2026-01", "2026-02", "2026-03"]
PRODUCTS = ["event_analytics", "session_replay", "feature_flags"]

LATE_USAGE_LABELS = {  # SPEC 3.2, 5
    "normal": "{month} usage, processed after the close cutoff",
    "bug_fix_reprocess": "{month} usage, reprocessed after a system fix",
}
MONTH_NAMES = {"2025-12": "December", "2026-01": "January", "2026-02": "February", "2026-03": "March"}

# Ledger rows sort by date, then in this order, so ledger_ids never change between runs.
# The revenue engine's events (step 5) are included so the whole ledger has one numbering.
EVENT_ORDER = ["opening_balance", "lag_estimate_reversal", "credit_invoice_issued", "invoice_issued",
               "usage_rated", "lag_estimate", "late_usage_rated", "credit_drawdown",
               "credit_revenue_recognized", "credit_memo", "payment_applied"]

LINE_COLUMNS = ["invoice_id", "customer_id", "issue_date", "due_date", "usage_month", "line_no",
                "line_type", "product", "tier", "units", "unit_price", "amount", "description"]
LEDGER_COLUMNS = ["ledger_id", "event_date", "event_type", "origin", "customer_id", "invoice_id", "product",
                  "usage_month", "quantity", "amount", "list_amount", "source_ref", "description"]


@dataclass
class Inputs:
    customers: pd.DataFrame
    contracts: pd.DataFrame
    rate_card: dict
    limits: dict
    usage: object  # UsageSummary
    adjustments: pd.DataFrame
    prior_invoices: pd.DataFrame
    opening: pd.DataFrame
    cutoff_business_day: int


def read_text_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def load_inputs(data_dir):
    data_dir = Path(data_dir)
    assumptions = read_text_csv(data_dir / "assumptions.csv").set_index("key")["value"]
    cutoff_day = int(assumptions["close_cutoff_business_day"])
    return Inputs(
        customers=read_text_csv(data_dir / "customers.csv").set_index("customer_id"),
        contracts=read_text_csv(data_dir / "contracts.csv"),
        rate_card=load_rate_card(data_dir / "rate_cards.csv"),
        limits=load_billing_limits(data_dir / "customers.csv"),
        usage=summarize(load_usage(data_dir / "usage_events.csv"), cutoff_day),
        adjustments=read_text_csv(data_dir / "adjustments.csv"),
        prior_invoices=read_text_csv(data_dir / "prior_period_invoices.csv"),
        opening=read_text_csv(data_dir / "opening_balances.csv"),
        cutoff_business_day=cutoff_day,
    )


def month_after(month):
    year, number = next_month(int(month[:4]), int(month[5:7]))
    return f"{year}-{number:02d}"


def due_date(issue_date, payment_terms):
    """SPEC 1: issue date plus the terms in calendar days (net_30, net_15). Not moved off weekends."""
    return issue_date + timedelta(days=int(payment_terms.split("_")[1]))


def month_end(month):
    return date.fromisoformat(month_after(month) + "-01") - timedelta(days=1)


def money(amount):
    return f"{Decimal(amount):.2f}"


# --- Invoices ---------------------------------------------------------------

def build_invoices(inputs):
    lines = []

    def add_invoice(invoice_id, customer, issue, month, invoice_lines):
        due = due_date(issue, inputs.customers.loc[customer, "payment_terms"])
        for number, line in enumerate(invoice_lines, start=1):
            lines.append({"invoice_id": invoice_id, "customer_id": customer,
                          "issue_date": issue.isoformat(), "due_date": due.isoformat(),
                          "usage_month": month, "line_no": number, **line})

    def line(line_type, amount, description, product="", tier="", units="", unit_price=""):
        return {"line_type": line_type, "product": product, "tier": tier, "units": units,
                "unit_price": unit_price, "amount": money(amount), "description": description}

    # SPEC 5: December 2025 invoices, issued January 2 (business day 2).
    for invoice_id, rows in inputs.prior_invoices.groupby("invoice_id", sort=True):
        add_invoice(invoice_id, rows.customer_id.iloc[0], business_day(2026, 1, 2), "2025-12",
                    [line("prior_period_usage", r.amount, "December 2025 usage", product=r.product)
                     for r in rows.itertuples()])

    # SPEC 3.3: annual prepaid credit, invoiced upfront on January 1.
    for contract in inputs.contracts[inputs.contracts.contract_type == "credit"].itertuples():
        add_invoice(f"INV-2026-01-{contract.customer_id}", contract.customer_id,
                    date.fromisoformat(contract.effective_from), "",
                    [line("credit_purchase", contract.cash_price,
                          f"Annual prepaid credit: ${Decimal(contract.credit_value):,.2f} of usage credit, "
                          f"{contract.effective_from} to {contract.effective_to}")])

    # SPEC 1, 3.1: pay-as-you-go usage invoiced monthly in arrears on business day 2.
    monthly = inputs.usage.monthly.set_index(["customer_id", "month", "product"])["quantity"]
    late = pd.concat([inputs.usage.lag, inputs.usage.reprocessed]).sort_values("processed_ts")
    for customer in PAYG_CUSTOMERS:
        caps = inputs.limits.get(customer, {})
        for month in USAGE_MONTHS:
            invoice_lines = []
            for product in PRODUCTS:
                cap = caps.get(product)
                priced = price(product, int(monthly[(customer, month, product)]), inputs.rate_card, cap)
                for t in priced.tier_lines:
                    label = "Free tier" if t.tier == "free" else f"Tier {t.tier}"
                    invoice_lines.append(line("usage", t.amount, f"{label}, {MONTH_NAMES[month]} usage",
                                              product, t.tier, t.units, str(t.unit_price)))
                if priced.capped_amount > 0:
                    # SPEC 3.4: presentation only. The cap is part of the price; this line explains
                    # the invoice and never posts as revenue, contra-revenue, or a credit memo.
                    invoice_lines.append(line("billing_limit", -priced.capped_amount,
                                              f"Monthly billing limit (${cap:,.2f})", product))

            # SPEC 3.2, 5: late usage goes on the invoice for the month it is processed.
            for row in late[(late.customer_id == customer) & (late.processed_ts.str[:7] == month)].itertuples():
                extra = late_usage_price(inputs, row)
                for t in extra.tier_lines:
                    invoice_lines.append(line(
                        "true_up" if row.source == "normal" else "reprocess", t.amount,
                        LATE_USAGE_LABELS[row.source].format(month=MONTH_NAMES[row.month]),
                        row.product, t.tier, t.units, str(t.unit_price)))

            add_invoice(f"INV-{month}-{customer}", customer,
                        business_day(*next_month(int(month[:4]), int(month[5:7])), 2), month, invoice_lines)

    return pd.DataFrame(lines, columns=LINE_COLUMNS)


def late_usage_price(inputs, row):
    """Price late usage at its usage month's rates, on top of what was already counted (SPEC 5, 1b and 1d)."""
    if row.product in inputs.limits.get(row.customer_id, {}):
        raise ValueError("Late usage on a product with a billing limit isn't covered by the spec")
    monthly = inputs.usage.monthly.set_index(["customer_id", "month", "product"])["quantity"]
    already = int(monthly[(row.customer_id, row.month, row.product)])
    late = pd.concat([inputs.usage.lag, inputs.usage.reprocessed])
    earlier = late[(late.customer_id == row.customer_id) & (late.month == row.month)
                   & (late["product"] == row.product) & (late.processed_ts < row.processed_ts)]
    already += int(earlier.quantity.sum())
    return price_additional(row.product, already, int(row.quantity), inputs.rate_card)


def invoice_totals(lines):
    """One row per invoice: invoice_id, customer_id, issue_date, due_date, usage_month, line_types, total."""
    totals = []
    for invoice_id, rows in lines.groupby("invoice_id", sort=True):
        first = rows.iloc[0]
        totals.append({"invoice_id": invoice_id, "customer_id": first.customer_id,
                       "issue_date": first.issue_date, "due_date": first.due_date,
                       "usage_month": first.usage_month, "line_types": set(rows.line_type),
                       "total": sum(Decimal(a) for a in rows.amount)})
    return pd.DataFrame(totals)


# --- Billing ledger -----------------------------------------------------------

def build_ledger(inputs, lines, payments):
    events = []

    def add(*args, **kwargs):
        events.append(ledger_event(*args, origin="billing", **kwargs))

    # SPEC 5: opening unbilled AR for December usage.
    for row in inputs.opening[inputs.opening.account == "unbilled_ar"].itertuples():
        add(row.as_of, "opening_balance", row.customer_id, row.debit, usage_month="2025-12",
            source_ref="opening_balances.csv", description=row.note)

    # Invoices issued. The credit invoice is kept separate: it isn't billing earned usage.
    for inv in invoice_totals(lines).itertuples():
        event = "credit_invoice_issued" if "credit_purchase" in inv.line_types else "invoice_issued"
        add(inv.issue_date, event, inv.customer_id, inv.total, invoice_id=inv.invoice_id,
            usage_month=inv.usage_month, description=f"Invoice issued, due {inv.due_date}")

    # Usage rated at the billed amount, at month end, by product (SPEC 3.1, 3.4).
    monthly = inputs.usage.monthly
    for row in monthly.sort_values(["customer_id", "month", "product"]).itertuples():
        cap = inputs.limits.get(row.customer_id, {}).get(row.product)
        priced = price(row.product, int(row.quantity), inputs.rate_card, cap)
        credit_customer = row.customer_id not in PAYG_CUSTOMERS
        # SPEC 3.3: credit customers draw down credit at list price; the 0.80 rate is step 5.
        add(month_end(row.month), "credit_drawdown" if credit_customer else "usage_rated", row.customer_id,
            priced.billed_amount, product=row.product, usage_month=row.month, quantity=int(row.quantity),
            list_amount=priced.list_amount,
            description="Credit drawn down at list price" if credit_customer else "Usage rated at close")

    # Late usage rated on the day it is processed (SPEC 3.2, 5).
    late = pd.concat([inputs.usage.lag, inputs.usage.reprocessed])
    for row in late.sort_values("processed_ts").itertuples():
        extra = late_usage_price(inputs, row)
        add(row.processed_ts[:10], "late_usage_rated", row.customer_id, extra.billed_amount,
            invoice_id=f"INV-{row.processed_ts[:7]}-{row.customer_id}", product=row.product,
            usage_month=row.month, quantity=int(row.quantity), list_amount=extra.list_amount,
            source_ref=row.event_id, description=LATE_USAGE_LABELS[row.source].format(month=MONTH_NAMES[row.month]))

    # SPEC 3.4: credit memos.
    for row in inputs.adjustments.itertuples():
        add(row.date, "credit_memo", row.customer_id, row.amount, invoice_id=row.invoice_id,
            source_ref=row.adjustment_id, description=f"{row.classification}: {row.reason}")

    for row in payments.itertuples():
        add(row.received_date, "payment_applied", row.customer_id, row.amount, invoice_id=row.invoice_id,
            source_ref=row.payment_id, description="Payment received")

    return number_ledger(events)


def ledger_event(event_date, event_type, customer, amount, origin, invoice_id="", product="", usage_month="",
                 quantity="", list_amount="", source_ref="", description=""):
    return {"event_date": str(event_date), "event_type": event_type, "origin": origin, "customer_id": customer,
            "invoice_id": invoice_id, "product": product, "usage_month": usage_month,
            "quantity": quantity, "amount": money(amount),
            "list_amount": money(list_amount) if list_amount != "" else "",
            "source_ref": source_ref, "description": description}


def number_ledger(events):
    """Sort events into a fixed order and assign ledger_ids, so reruns give identical ids."""
    ledger = pd.DataFrame(events).drop(columns="ledger_id", errors="ignore")
    ledger["order"] = ledger.event_type.map(EVENT_ORDER.index)
    ledger = ledger.sort_values(["event_date", "order", "customer_id", "invoice_id", "product", "usage_month"],
                                kind="stable").drop(columns="order").reset_index(drop=True)
    ledger.insert(0, "ledger_id", [f"BL-{i:05d}" for i in range(1, len(ledger) + 1)])
    return ledger[LEDGER_COLUMNS]


def ar_balances(ledger, as_of):
    """Billed and unbilled AR by customer at the end of a day, from the ledger alone."""
    rows = ledger[ledger.event_date <= str(as_of)]
    billed, unbilled = {}, {}
    for row in rows.itertuples():
        amount = Decimal(row.amount)
        c = row.customer_id
        if row.event_type in ("opening_balance", "usage_rated", "late_usage_rated", "lag_estimate"):
            unbilled[c] = unbilled.get(c, ZERO) + amount
        elif row.event_type == "lag_estimate_reversal":  # SPEC 3.2: estimate reverses next month
            unbilled[c] = unbilled.get(c, ZERO) - amount
        elif row.event_type == "invoice_issued":  # moves unbilled AR to billed AR
            unbilled[c] = unbilled.get(c, ZERO) - amount
            billed[c] = billed.get(c, ZERO) + amount
        elif row.event_type == "credit_invoice_issued":
            billed[c] = billed.get(c, ZERO) + amount
        elif row.event_type in ("credit_memo", "payment_applied"):
            billed[c] = billed.get(c, ZERO) - amount
    return billed, unbilled


def write_csv(frame, path):
    frame.to_csv(path, index=False, lineterminator="\n")


def run_billing(data_dir, output_dir):
    from revrec.payments import generate_payments  # payments depend on the invoices

    inputs = load_inputs(data_dir)
    lines = build_invoices(inputs)
    payments = generate_payments(invoice_totals(lines), inputs.adjustments)
    write_csv(payments, Path(data_dir) / "payments.csv")
    ledger = build_ledger(inputs, lines, payments)
    write_csv(lines, Path(output_dir) / "invoices.csv")
    write_csv(ledger, Path(output_dir) / "billing_ledger.csv")
    return lines, payments, ledger

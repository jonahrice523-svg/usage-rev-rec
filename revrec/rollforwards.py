"""Monthly rollforwards, each tied to the GL (SPEC 6 item 4, SPEC 7; build step 7).

- Contract liability: opening + invoiced - recognized = closing            (GL 2400)
- Credit balance at list value: opening + purchased - consumed = closing   (memo; x 0.80 = contract liability)
- Billed AR: opening + billed - cash - credits = closing                    (GL 1100)
- Unbilled AR: opening + accrued - invoiced = closing                       (GL 1150)

Movements come from the billing ledger. January's opening comes from the January 1
opening balance rows (SPEC 5), which are an opening line, not a movement.

output/rollforwards.csv is one long table: rollforward, customer_id, month, line, amount,
read top to bottom like a workpaper.
"""

from decimal import Decimal
from pathlib import Path

import pandas as pd

from revrec.billing import month_end

ZERO = Decimal("0.00")
MONTHS = ["2026-01", "2026-02", "2026-03"]
TOTAL = "ALL"
COLUMNS = ["rollforward", "customer_id", "month", "line", "amount"]


def sum_events(ledger, month, customer, *event_types):
    rows = ledger[(ledger.event_date.str[:7] == month) & ledger.event_type.isin(event_types)]
    if customer != TOTAL:
        rows = rows[rows.customer_id == customer]
    return sum((Decimal(a) for a in rows.amount), ZERO)


def gl_balance(gl, account, as_of, customer):
    """Debit-minus-credit balance of a GL account at the end of a day, for one customer or all."""
    rows = gl[(gl.account == account) & (gl.entry_date <= as_of)]
    if customer != TOTAL:
        rows = rows[rows.customer_id == customer]
    return sum((Decimal(d) - Decimal(c) for d, c in zip(rows.debit, rows.credit)), ZERO)


def opening_balance(ledger, customer):
    rows = ledger[ledger.event_type == "opening_balance"]
    if customer != TOTAL:
        rows = rows[rows.customer_id == customer]
    return sum((Decimal(a) for a in rows.amount), ZERO)


def roll(name, customer, movements_by_month, opening, gl_account=None, gl=None, gl_sign=1):
    """Build the lines for one rollforward. movements_by_month: {month: [(line, signed amount), ...]}."""
    lines = []
    for month in MONTHS:
        lines.append((name, customer, month, "opening", opening))
        closing = opening
        for line, amount in movements_by_month[month]:
            lines.append((name, customer, month, line, amount))
            closing += amount
        lines.append((name, customer, month, "closing", closing))
        if gl_account:
            balance = gl_sign * gl_balance(gl, gl_account, month_end(month).isoformat(), customer)
            lines.append((name, customer, month, f"GL {gl_account} balance", balance))
            lines.append((name, customer, month, "difference", closing - balance))
        opening = closing
    return lines


def build_rollforwards(ledger, gl, contracts):
    lines = []
    credit_customers = list(contracts[contracts.contract_type == "credit"].customer_id)
    ar_customers = sorted(set(ledger.customer_id)) + [TOTAL]

    for customer in credit_customers:
        # SPEC 3.3: contract liability at cash value. It's a credit balance, so the GL sign flips.
        lines += roll("contract_liability", customer, {m: [
            ("invoiced", sum_events(ledger, m, customer, "credit_invoice_issued")),
            ("recognized", -sum_events(ledger, m, customer, "credit_revenue_recognized")),
        ] for m in MONTHS}, ZERO, "2400", gl, gl_sign=-1)

        # SPEC 3.3: credit balance at list value, what the customer sees. Memo only; it ties to
        # the contract liability through the 0.80 rate.
        contract = contracts[contracts.customer_id == customer].iloc[0]
        rate = Decimal(contract.cash_price) / Decimal(contract.credit_value)
        credit_lines = roll("credit_balance_at_list", customer, {m: [
            ("purchased", Decimal(contract.credit_value) if contract.effective_from[:7] == m else ZERO),
            ("consumed", -sum_events(ledger, m, customer, "credit_drawdown")),
        ] for m in MONTHS}, ZERO)
        for entry in credit_lines:
            lines.append(entry)
            if entry[3] == "closing":
                month = entry[2]
                liability = -gl_balance(gl, "2400", month_end(month).isoformat(), customer)
                lines.append(("credit_balance_at_list", customer, month, f"closing x {rate:.2f}", entry[4] * rate))
                lines.append(("credit_balance_at_list", customer, month, "GL 2400 balance", liability))
                lines.append(("credit_balance_at_list", customer, month, "difference", entry[4] * rate - liability))

    for customer in ar_customers:
        lines += roll("billed_ar", customer, {m: [
            ("billed", sum_events(ledger, m, customer, "invoice_issued", "credit_invoice_issued")),
            ("cash", -sum_events(ledger, m, customer, "payment_applied")),
            ("credits", -sum_events(ledger, m, customer, "credit_memo")),
        ] for m in MONTHS}, ZERO, "1100", gl)

    for customer in ar_customers:
        # SPEC 3.2: accrued = usage rated + late usage + lag estimate - estimate reversal.
        lines += roll("unbilled_ar", customer, {m: [
            ("accrued", sum_events(ledger, m, customer, "usage_rated", "late_usage_rated", "lag_estimate")
             - sum_events(ledger, m, customer, "lag_estimate_reversal")),
            ("invoiced", -sum_events(ledger, m, customer, "invoice_issued")),
        ] for m in MONTHS}, opening_balance(ledger, customer), "1150", gl)

    frame = pd.DataFrame(lines, columns=COLUMNS)
    frame["amount"] = frame.amount.map(lambda a: f"{a:.2f}")
    return frame


def closing(rollforwards, name, customer, month):
    rows = rollforwards[(rollforwards.rollforward == name) & (rollforwards.customer_id == customer)
                        & (rollforwards.month == month) & (rollforwards.line == "closing")]
    return Decimal(rows.amount.iloc[0])


def run_rollforwards(data_dir, output_dir, ledger, gl):
    contracts = pd.read_csv(Path(data_dir) / "contracts.csv", dtype=str, keep_default_na=False)
    frame = build_rollforwards(ledger, gl, contracts)
    frame.to_csv(Path(output_dir) / "rollforwards.csv", index=False, lineterminator="\n")
    return frame

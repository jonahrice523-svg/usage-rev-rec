"""AR aging and collections log as of March 31 (SPEC 3.4, 6 item 5; build step 7).

AR aging: billed AR only, by open invoice and days past due. Unbilled AR isn't due yet,
so it isn't aged; it's shown as a memo line that ties to GL 1150.

Collections log: reminder at day 5 past due, follow-up at day 15 (assumptions.csv),
for any invoice still open on that day. Actions after March 31 show as scheduled.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from revrec.billing import ar_balances
from revrec.rollforwards import gl_balance

ZERO = Decimal("0.00")
AS_OF = date(2026, 3, 31)
BUCKETS = ["current", "1-30", "31-60", "61-90", "over_90"]
AGING_COLUMNS = ["line", "customer_id", "invoice_id", "issue_date", "due_date", "days_past_due", "bucket",
                 "amount"] + BUCKETS
LOG_COLUMNS = ["invoice_id", "customer_id", "due_date", "action", "action_date", "days_past_due",
               "open_amount", "status"]


def open_amount(ledger, invoice_id, as_of):
    """Invoice total less payments and credit memos, through the end of a day."""
    rows = ledger[(ledger.invoice_id == invoice_id) & (ledger.event_date <= str(as_of))]
    billed = sum((Decimal(a) for a in rows[rows.event_type.isin(["invoice_issued", "credit_invoice_issued"])].amount), ZERO)
    reduced = sum((Decimal(a) for a in rows[rows.event_type.isin(["payment_applied", "credit_memo"])].amount), ZERO)
    return billed - reduced


def bucket(days_past_due):
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "over_90"


def build_aging(ledger, invoices, gl, as_of=AS_OF):
    rows = []
    for inv in invoices[invoices.issue_date <= str(as_of)].sort_values(["customer_id", "invoice_id"]).itertuples():
        amount = open_amount(ledger, inv.invoice_id, as_of)
        if amount == 0:
            continue
        days = (as_of - date.fromisoformat(inv.due_date)).days
        row = {"line": "open_invoice", "customer_id": inv.customer_id, "invoice_id": inv.invoice_id,
               "issue_date": inv.issue_date, "due_date": inv.due_date, "days_past_due": str(max(days, 0)),
               "bucket": bucket(days), "amount": amount, **{b: ZERO for b in BUCKETS}}
        row[bucket(days)] = amount
        rows.append(row)

    total = {"line": "total_billed_ar", "amount": sum((r["amount"] for r in rows), ZERO),
             **{b: sum((r[b] for r in rows), ZERO) for b in BUCKETS}}
    gl_1100 = gl_balance(gl, "1100", as_of.isoformat(), "ALL")
    _, unbilled = ar_balances(ledger, as_of)
    gl_1150 = gl_balance(gl, "1150", as_of.isoformat(), "ALL")
    rows += [total,
             {"line": "GL 1100 balance", "amount": gl_1100},
             {"line": "difference", "amount": total["amount"] - gl_1100},
             {"line": "memo: unbilled AR (not aged)", "amount": sum(unbilled.values(), ZERO)},
             {"line": "GL 1150 balance", "amount": gl_1150},
             {"line": "difference", "amount": sum(unbilled.values(), ZERO) - gl_1150}]

    frame = pd.DataFrame(rows, columns=AGING_COLUMNS).astype(object).fillna("")
    for column in ["amount"] + BUCKETS:
        frame[column] = frame[column].map(lambda a: f"{a:.2f}" if a != "" else "")
    return frame


def build_collections_log(ledger, invoices, reminder_days, followup_days, as_of=AS_OF):
    rows = []
    for inv in invoices[invoices.issue_date <= str(as_of)].sort_values(["due_date", "invoice_id"]).itertuples():
        due = date.fromisoformat(inv.due_date)
        for action, days in [("reminder", reminder_days), ("follow_up", followup_days)]:
            action_date = due + timedelta(days=days)
            # Sent if the invoice was still open that day; scheduled if it's still open at the period end.
            checked_on = min(action_date, as_of)
            amount = open_amount(ledger, inv.invoice_id, checked_on)
            if amount == 0:
                continue
            rows.append({"invoice_id": inv.invoice_id, "customer_id": inv.customer_id, "due_date": inv.due_date,
                         "action": action, "action_date": action_date.isoformat(), "days_past_due": days,
                         "open_amount": f"{amount:.2f}",
                         "status": "sent" if action_date <= as_of else "scheduled (after period end)"})
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def run_collections(data_dir, output_dir, ledger, invoices, gl):
    values = pd.read_csv(Path(data_dir) / "assumptions.csv", dtype=str, keep_default_na=False).set_index("key")["value"]
    aging = build_aging(ledger, invoices, gl)
    log = build_collections_log(ledger, invoices, int(values["collections_reminder_days"]),
                                int(values["collections_followup_days"]))
    aging.to_csv(Path(output_dir) / "ar_aging.csv", index=False, lineterminator="\n")
    log.to_csv(Path(output_dir) / "collections_log.csv", index=False, lineterminator="\n")
    return aging, log

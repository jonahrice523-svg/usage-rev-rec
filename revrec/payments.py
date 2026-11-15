"""Generate data/payments.csv from rules, once invoices exist (SPEC 5, build step 4).

- Harry Hood pays in full 3 days before the due date (the weekday before, if that's a weekend).
- Famous Mockingbird pays its credit invoice on January 28 (SPEC 3.3).
- Tela pays its December invoice by the same 3-day rule, short-pays January (invoice less
  the credit memo) on February 17, and pays February 20 days late, on April 7 (SPEC 3.4).

Invoices issued April 2 (March usage) are after the model period and have no payments.
"""

from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

FIXED_DATES = {  # SPEC 3.3, 3.4
    "INV-2026-01-MOCK": date(2026, 1, 28),
    "INV-2026-01-TELA": date(2026, 2, 17),
    "INV-2026-02-TELA": date(2026, 4, 7),
}
PERIOD_END = date(2026, 3, 31)


def three_days_before(due):
    paid = due - timedelta(days=3)
    while paid.weekday() >= 5:  # Saturday or Sunday: pay the weekday before
        paid -= timedelta(days=1)
    return paid


def generate_payments(invoices, adjustments):
    credits = {}
    for row in adjustments.itertuples():
        credits[row.invoice_id] = credits.get(row.invoice_id, Decimal("0")) + Decimal(row.amount)

    payments = []
    for inv in invoices.itertuples():
        if date.fromisoformat(inv.issue_date) > PERIOD_END:
            continue
        paid_on = FIXED_DATES.get(inv.invoice_id) or three_days_before(date.fromisoformat(inv.due_date))
        amount = inv.total - credits.get(inv.invoice_id, Decimal("0"))  # SPEC 3.4: short-pay net of credit
        payments.append((paid_on, inv.customer_id, inv.invoice_id, f"{amount:.2f}"))

    payments.sort()
    return pd.DataFrame(
        [(f"PAY-{i:04d}", c, inv, amt, d.isoformat()) for i, (d, c, inv, amt) in enumerate(payments, start=1)],
        columns=["payment_id", "customer_id", "invoice_id", "amount", "received_date"])

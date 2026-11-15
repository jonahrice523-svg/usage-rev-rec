"""Run the quarter's revenue close end to end.

So far: synthetic data (step 2), pricing (step 3), invoices, payments,
and the billing ledger (step 4), and the revenue engine (step 5). Each later step in SPEC.md section 8
adds its piece here.
"""

from pathlib import Path

from revrec.billing import ar_balances, invoice_totals, run_billing
from revrec.generate_data import generate
from revrec.pricing import load_billing_limits, load_rate_card, price_monthly_usage
from revrec.gl import account_balances, run_gl
from revrec.revenue import revenue_by, run_revenue
from revrec.usage import load_usage, summarize

ROOT = Path(__file__).parent
FOLDERS = ["data", "config", "output", "output/workpapers"]

# SPEC 8: build order
BUILD_STEPS = [
    "1. Repo scaffolding, README, spec, CLAUDE.md",
    "2. Synthetic data generator (fixed random seed)",
    "3. Pricing engine: free tier, graduated tiers, billing limit",
    "4. Billing ledger and invoicing",
    "5. Revenue engine (SPEC 3.1-3.5)",
    "6. Account mapping, GL export, integration controls",
    "7. Rollforwards, AR aging, collections log",
    "8. Reconciliation, close checklist, exceptions",
    "9. Workpapers and the Tela billing reply",
    "10. run.py runs the whole quarter's close",
]
STEPS_DONE = 6


def print_gl_summary(config, data, output, ledger):
    """Step 6: GL export through the account mapping, trial balance, and integration controls."""
    gl, mapped, controls, chart = run_gl(config, data, output, ledger)
    names = chart.set_index("account")["name"].to_dict()
    print("Trial balance at March 31 (from output/gl_export.csv):")
    print(f"  {'Account':<38}{'Debit':>14}{'Credit':>14}")
    balances = account_balances(gl)
    for account in sorted(balances):
        value = balances[account]
        debit, credit = (f"{value:,.2f}", "") if value > 0 else ("", f"{-value:,.2f}")
        print(f"  {account + ' ' + names[account]:<38}{debit:>14}{credit:>14}")
    debits = sum(v for v in balances.values() if v > 0)
    print(f"  {'Total':<38}{debits:>14,.2f}{debits:>14,.2f}")
    print("Integration controls:")
    for name, passed, detail in controls:
        print(f"  {'PASS' if passed else 'FAIL'}  {name} ({detail})")
    print()


def print_revenue_summary(data, output, billing_ledger):
    """Step 5: revenue schedule, and the revenue engine's entries added to the ledger."""
    ledger, schedule, exceptions = run_revenue(data, output, billing_ledger)
    by = revenue_by(schedule, "customer_id", "month")
    months = ["2026-01", "2026-02", "2026-03"]
    print("Revenue recognized (output/revenue_schedule.csv):")
    print(f"  {'Customer':<9}" + "".join(f"{m:>12}" for m in months) + f"{'Q1':>12}")
    for customer in ["HOOD", "MOCK", "TELA"]:
        values = [by.get((customer, m), 0) for m in months]
        print(f"  {customer:<9}" + "".join(f"{v:>12,.2f}" for v in values) + f"{sum(values):>12,.2f}")
    totals = [sum(v for (c, m), v in by.items() if m == month) for month in months]
    print(f"  {'Total':<9}" + "".join(f"{v:>12,.2f}" for v in totals) + f"{sum(totals):>12,.2f}")
    _, unbilled = ar_balances(ledger, "2026-03-31")
    print(f"Unbilled AR at March 31 including the lag estimate: {sum(unbilled.values()):,.2f}")
    print(f"Billing ledger now has {len(ledger)} events; unusual-item exceptions: {len(exceptions)}")
    print()
    return ledger


def print_billing_summary(data, output):
    """Step 4: invoices, payments, and the billing ledger."""
    lines, payments, ledger = run_billing(data, output)
    print("Invoices (output/invoices.csv):")
    for inv in invoice_totals(lines).sort_values(["issue_date", "invoice_id"]).itertuples():
        print(f"  {inv.invoice_id:<18} issued {inv.issue_date}  due {inv.due_date}  {inv.total:>12,.2f}")
    print(f"Payments written to data/payments.csv: {len(payments)}")
    print(f"Billing ledger (output/billing_ledger.csv): {len(ledger)} events")
    billed, unbilled = ar_balances(ledger, "2026-03-31")
    print(f"AR at March 31 from billing: billed {sum(billed.values()):,.2f}, unbilled {sum(unbilled.values()):,.2f}")
    print()
    return ledger


def print_pricing_summary(data):
    """Step 3: price each customer's monthly usage and show list, capped, and billed amounts."""
    summary = summarize(load_usage(data / "usage_events.csv"), cutoff_business_day=3)  # SPEC 3.2
    priced = price_monthly_usage(summary.monthly, load_rate_card(data / "rate_cards.csv"),
                                 load_billing_limits(data / "customers.csv"))
    totals = {}
    for customer, month, p in priced:
        row = totals.setdefault((customer, month), [0, 0, 0])
        row[0] += p.list_amount
        row[1] += p.capped_amount
        row[2] += p.billed_amount

    print("Usage priced at close (processed by the cutoff, list prices, before credit or revenue rules):")
    print(f"  {'Customer':<9}{'Month':<9}{'List':>12}{'Capped':>10}{'Billed':>12}")
    for (customer, month), (list_amount, capped, billed) in sorted(totals.items()):
        print(f"  {customer:<9}{month:<9}{list_amount:>12,.2f}{capped:>10,.2f}{billed:>12,.2f}")
    print(f"  Also: {len(summary.duplicates)} duplicate rows removed, {len(summary.lag)} lag batch, "
          f"{len(summary.reprocessed)} bug-fix reprocess (priced in later steps)")
    print()


def main():
    print("Hedgehog Metrics, Inc. - usage revenue model (synthetic data)")
    print("Model period: January-March 2026")  # SPEC 1
    print()

    for folder in FOLDERS:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    print("Folders ready: " + ", ".join(FOLDERS))

    generate(ROOT / "data")  # step 2
    print("Synthetic data written to data/: " + ", ".join(sorted(p.name for p in (ROOT / "data").glob("*.csv"))))
    print()

    print_pricing_summary(ROOT / "data")  # step 3
    billing_ledger = print_billing_summary(ROOT / "data", ROOT / "output")  # step 4
    ledger = print_revenue_summary(ROOT / "data", ROOT / "output", billing_ledger)  # step 5
    print_gl_summary(ROOT / "config", ROOT / "data", ROOT / "output", ledger)  # step 6

    print("Build progress (SPEC section 8):")
    for number, step in enumerate(BUILD_STEPS, start=1):
        status = "done" if number <= STEPS_DONE else "not built yet"
        print(f"  [{status}] {step}")


if __name__ == "__main__":
    main()

"""Run the quarter's revenue close end to end: `python run.py` (SPEC 8, step 10).

`close_quarter()` runs every step in SPEC section 8 order and writes data/ and output/.
`main()` then prints a short summary of each step. The fixed random seed means every run
produces identical files.
"""

from pathlib import Path

from revrec.billing import invoice_totals, load_inputs, read_text_csv, run_billing
from revrec.billing_reply import run_billing_reply
from revrec.workpapers import run_workpapers
from revrec.close import run_close
from revrec.collections import run_collections
from revrec.generate_data import generate
from revrec.gl import account_balances, run_gl
from revrec.pricing import price_monthly_usage
from revrec.reconciliation import run_reconciliation
from revrec.revenue import load_assumptions, revenue_by, run_revenue
from revrec.rollforwards import MONTHS, closing, run_rollforwards
from revrec.usage import load_usage

ROOT = Path(__file__).parent
CONFIG = ROOT / "config"
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
STEPS_DONE = 10


def close_quarter(root=ROOT, config=CONFIG):
    """Run steps 2-9 and return everything each step produced.

    root is the folder that gets data/ and output/ (the repo by default; tests pass a
    temporary folder). config is the hand-kept chart of accounts and account mapping.
    """
    root = Path(root)
    DATA, CONFIG, OUTPUT = root / "data", Path(config), root / "output"
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    r = {"root": root}
    generate(DATA)                                                                     # step 2
    inputs = load_inputs(DATA)
    r["inputs"] = inputs
    r["priced"] = price_monthly_usage(inputs.usage.monthly, inputs.rate_card, inputs.limits)  # step 3
    r["lines"], r["payments"], r["billing_ledger"] = run_billing(DATA, OUTPUT)         # step 4
    r["invoices"] = invoice_totals(r["lines"])
    r["ledger"], r["schedule"], r["unusual_exceptions"] = run_revenue(DATA, OUTPUT, r["billing_ledger"])  # step 5
    r["gl"], r["mapped"], r["controls"], r["chart"] = run_gl(CONFIG, DATA, OUTPUT, r["ledger"])  # step 6
    r["rollforwards"] = run_rollforwards(DATA, OUTPUT, r["ledger"], r["gl"])           # step 7
    r["aging"], r["collections_log"] = run_collections(DATA, OUTPUT, r["ledger"], r["invoices"], r["gl"])
    assumptions = load_assumptions(DATA)
    r["reconciliation"] = run_reconciliation(OUTPUT, load_usage(DATA / "usage_events.csv"), inputs, r["ledger"],
                                             r["lines"], r["schedule"], r["gl"], r["chart"], r["rollforwards"])  # step 8
    days = read_text_csv(DATA / "assumptions.csv").set_index("key")["value"]  # SPEC 3.4: collections days
    r["close"] = run_close(OUTPUT, inputs=inputs, assumptions=assumptions, mapped=r["mapped"],
                           unusual_exceptions=r["unusual_exceptions"], ledger=r["ledger"], lines=r["lines"],
                           invoices_frame=r["invoices"], schedule=r["schedule"], gl=r["gl"], chart=r["chart"],
                           integration_controls=r["controls"], rollforwards=r["rollforwards"],
                           reconciliation=r["reconciliation"],
                           reminder_days=int(days["collections_reminder_days"]),
                           followup_days=int(days["collections_followup_days"]))
    r["reply_text"], r["reply"] = run_billing_reply(OUTPUT, r["lines"], inputs.limits)        # step 9
    r["workpapers"] = run_workpapers(
        OUTPUT, checklist=r["close"]["checklist"], integration_controls=r["controls"],
        raw_usage=load_usage(DATA / "usage_events.csv"), usage_summary=inputs.usage, ledger=r["ledger"],
        lines=r["lines"], invoices=r["invoices"], gl=r["gl"], mapping=read_text_csv(CONFIG / "account_mapping.csv"),
        adjustments=inputs.adjustments, cutoff_day=inputs.cutoff_business_day)
    return r


# --- Printed summary, one section per step ---------------------------------------------------------

def print_pricing(r):
    totals = {}
    for customer, month, p in r["priced"]:
        row = totals.setdefault((customer, month), [0, 0, 0])
        row[0] += p.list_amount
        row[1] += p.capped_amount
        row[2] += p.billed_amount
    usage = r["inputs"].usage
    print("Step 3. Usage priced at close (list prices, before credit or revenue rules):")
    print(f"  {'Customer':<9}{'Month':<9}{'List':>12}{'Capped':>10}{'Billed':>12}")
    for (customer, month), (list_amount, capped, billed) in sorted(totals.items()):
        print(f"  {customer:<9}{month:<9}{list_amount:>12,.2f}{capped:>10,.2f}{billed:>12,.2f}")
    print(f"  Also: {len(usage.duplicates)} duplicate rows removed, {len(usage.lag)} lag batch, "
          f"{len(usage.reprocessed)} bug-fix reprocess")
    print()


def print_billing(r):
    print("Step 4. Invoices (output/invoices.csv):")
    for inv in r["invoices"].sort_values(["issue_date", "invoice_id"]).itertuples():
        print(f"  {inv.invoice_id:<18} issued {inv.issue_date}  due {inv.due_date}  {inv.total:>12,.2f}")
    print(f"  Payments written to data/payments.csv: {len(r['payments'])}")
    print()


def print_revenue(r):
    by = revenue_by(r["schedule"], "customer_id", "month")
    print("Step 5. Revenue recognized (output/revenue_schedule.csv):")
    print(f"  {'Customer':<9}" + "".join(f"{m:>12}" for m in MONTHS) + f"{'Q1':>12}")
    for customer in ["HOOD", "MOCK", "TELA"]:
        values = [by.get((customer, m), 0) for m in MONTHS]
        print(f"  {customer:<9}" + "".join(f"{v:>12,.2f}" for v in values) + f"{sum(values):>12,.2f}")
    totals = [sum(v for (c, m), v in by.items() if m == month) for month in MONTHS]
    print(f"  {'Total':<9}" + "".join(f"{v:>12,.2f}" for v in totals) + f"{sum(totals):>12,.2f}")
    print(f"  Billing ledger (output/billing_ledger.csv): {len(r['ledger'])} events")
    print()


def print_gl(r):
    names = r["chart"].set_index("account")["name"].to_dict()
    print("Step 6. Trial balance at March 31 (from output/gl_export.csv):")
    print(f"  {'Account':<38}{'Debit':>14}{'Credit':>14}")
    balances = account_balances(r["gl"])
    for account in sorted(balances):
        value = balances[account]
        debit, credit = (f"{value:,.2f}", "") if value > 0 else ("", f"{-value:,.2f}")
        print(f"  {account + ' ' + names[account]:<38}{debit:>14}{credit:>14}")
    debits = sum(v for v in balances.values() if v > 0)
    print(f"  {'Total':<38}{debits:>14,.2f}{debits:>14,.2f}")
    print("  Integration controls:")
    for name, passed, detail in r["controls"]:
        print(f"    {'PASS' if passed else 'FAIL'}  {name} ({detail})")
    print()


def print_rollforwards(r):
    rf = r["rollforwards"]
    print("Step 7. Rollforward closing balances (output/rollforwards.csv):")
    print(f"  {'Rollforward':<28}" + "".join(f"{m:>12}" for m in MONTHS))
    for name, customer in [("contract_liability", "MOCK"), ("credit_balance_at_list", "MOCK"),
                           ("billed_ar", "ALL"), ("unbilled_ar", "ALL")]:
        print(f"  {name:<28}" + "".join(f"{closing(rf, name, customer, m):>12,.2f}" for m in MONTHS))
    untied = rf[(rf.line == "difference") & (rf.amount != "0.00")]
    print(f"  Ties to the GL: {'PASS' if untied.empty else 'FAIL'} ({len(rf[rf.line == 'difference'])} checks)")
    for row in r["aging"][r["aging"].line == "open_invoice"].itertuples():
        print(f"  Aging: {row.invoice_id}  {row.days_past_due} days past due  bucket {row.bucket}  "
              f"{float(row.amount):,.2f}")
    for row in r["collections_log"].itertuples():
        print(f"  Collections: {row.invoice_id}  {row.action:<10} {row.action_date}  {row.status}")
    print()


def print_close(r):
    print("Step 8. Reconciliation (output/reconciliation.md), unexplained difference by bridge:")
    for month, bridges in r["reconciliation"].items():
        print(f"  {month}: " + "  ".join(f"{b.key} {b.unexplained}" for b in bridges))
    print("  Close checklist (output/close_checklist.md):")
    for month, results in r["close"]["checklist"].items():
        complete = sum(1 for passed, _ in results.values() if passed is True)
        pending = [name for name, (passed, _) in results.items() if passed is not True]
        print(f"    {month}: {complete} of {len(results)} complete; outstanding: {', '.join(pending) or 'none'}")
    exceptions = r["close"]["exceptions"]
    print(f"  Exceptions (output/exceptions.csv): {len(exceptions)}, open: {(exceptions.status == 'open').sum()}")
    print()


def print_workpapers(r):
    reply = r["reply"]
    print("Step 9. Tela billing reply (output/billing_reply_tela.md): "
          f"December {reply['dec_total']:,.2f} -> January {reply['jan_total']:,.2f}")
    results = r["workpapers"]["control_results"]
    print("  Controls matrix (output/workpapers/controls_matrix.md):")
    for control in results[MONTHS[0]]:
        print(f"    {control:<18}" + "  ".join("PASS" if results[m][control] else "FAIL" for m in MONTHS))
    print("  Sample tie-outs (output/workpapers/sample_tieouts.md):")
    for invoice_id, checks in r["workpapers"]["tieout_checks"].items():
        tied = all(passed for _, passed, _ in checks)
        print(f"    {invoice_id:<18} {'ties' if tied else 'DOES NOT TIE'} ({len(checks)} checks)")
    print()


def main():
    print("Hedgehog Metrics, Inc. - usage revenue model (synthetic data)")
    print("Model period: January-March 2026")  # SPEC 1
    print()
    r = close_quarter()
    for section in [print_pricing, print_billing, print_revenue, print_gl, print_rollforwards, print_close,
                    print_workpapers]:
        section(r)
    print("Build progress (SPEC section 8):")
    for number, step in enumerate(BUILD_STEPS, start=1):
        print(f"  [{'done' if number <= STEPS_DONE else 'not built yet'}] {step}")


if __name__ == "__main__":
    main()

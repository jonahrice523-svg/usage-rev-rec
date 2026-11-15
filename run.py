"""Run the quarter's revenue close end to end.

So far this generates the synthetic input data (step 2). Each later step
in SPEC.md section 8 adds its piece here.
"""

from pathlib import Path

from revrec.generate_data import generate
from revrec.pricing import load_billing_limits, load_rate_card, price_monthly_usage
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
STEPS_DONE = 3


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

    print("Build progress (SPEC section 8):")
    for number, step in enumerate(BUILD_STEPS, start=1):
        status = "done" if number <= STEPS_DONE else "not built yet"
        print(f"  [{status}] {step}")


if __name__ == "__main__":
    main()

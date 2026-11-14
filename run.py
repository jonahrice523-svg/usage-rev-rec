"""Run the quarter's revenue close end to end.

Step 1 (scaffolding): no accounting yet. This prints the build plan and
makes sure the input and output folders exist. Each later step in
SPEC.md section 8 adds its piece here.
"""

from pathlib import Path

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
STEPS_DONE = 1


def main():
    print("Hedgehog Metrics, Inc. - usage revenue model (synthetic data)")
    print("Model period: January-March 2026")  # SPEC 1
    print()

    for folder in FOLDERS:
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    print("Folders ready: " + ", ".join(FOLDERS))
    print()

    print("Build progress (SPEC section 8):")
    for number, step in enumerate(BUILD_STEPS, start=1):
        status = "done" if number <= STEPS_DONE else "not built yet"
        print(f"  [{status}] {step}")


if __name__ == "__main__":
    main()

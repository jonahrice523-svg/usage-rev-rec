# Usage-based revenue recognition model

**Why I built this:** I built this to get hands-on with usage-based revenue accounting before interviewing for a revenue accounting role. Reading the guidance is one thing. Watching a $525 billing cap refuse to become revenue, and proving it with a test, is another.

A small, end-to-end model of one quarter (January–March 2026) of revenue accounting for Hedgehog Metrics, Inc., a fictional usage-billed analytics company. It covers usage, pricing, billing, revenue recognition under ASC 606, journal entries, AR and collections, rollforwards, reconciliations, the monthly close, and audit workpapers.

**All data is synthetic.** The company, customers, prices, and events are invented. Accounting guidance is cited to PwC's *Revenue from contracts with customers* by section number; the guide itself isn't in this repo.

## What this covers

- **Usage-based revenue recognition:** [output/revenue_schedule.csv](output/revenue_schedule.csv)
- **Deferrals and recognition schedules:** [output/rollforwards.csv](output/rollforwards.csv) (contract liability and prepaid credit)
- **Reconciliations:** [output/reconciliation.md](output/reconciliation.md)
- **AR and collections:** [output/ar_aging.csv](output/ar_aging.csv) and [output/collections_log.csv](output/collections_log.csv)
- **Month-end close:** [output/close_checklist.md](output/close_checklist.md)
- **Audit support (controls and workpapers):** [output/workpapers/controls_matrix.md](output/workpapers/controls_matrix.md) and [output/workpapers/sample_tieouts.md](output/workpapers/sample_tieouts.md)
- **Billing ledger-to-GL integration:** [output/billing_ledger.csv](output/billing_ledger.csv) → [config/account_mapping.csv](config/account_mapping.csv) → [output/gl_export.csv](output/gl_export.csv)
- **Automating the close (one command):** [run.py](run.py)

## Three customers, done thoroughly

| Customer | Plan | What it shows |
|---|---|---|
| Harry Hood | Monthly pay-as-you-go | Tiered pricing, month-end accrual and cutoff, lag estimate and true-up, duplicates, time zones |
| Famous Mockingbird | $100,000 of annual credit for $80,000 | Contract liability, revenue at $0.80 per $1.00 of credit, breakage constrained to zero |
| Tela | Pay-as-you-go, Net 15, $1,000 replay limit | Billing limit, a billing question, a price concession, a late payment, AR aging |

## Q1 results

| | January | February | March | Q1 |
|---|---:|---:|---:|---:|
| Revenue | 18,927.25 | 18,485.00 | 17,940.00 | 55,352.25 |

Every expected result in [SPEC.md](SPEC.md) section 5 was worked out independently of the model code before it was built, and the tests assert each one.

## Where to look (no code needed)

1. [output/reconciliation.md](output/reconciliation.md): usage → invoice → revenue → cash, each month, with zero unexplained difference
2. [output/close_checklist.md](output/close_checklist.md): close steps, preparer and reviewer, automated checks
3. [output/workpapers/controls_matrix.md](output/workpapers/controls_matrix.md): the eight controls and their results
4. [output/workpapers/sample_tieouts.md](output/workpapers/sample_tieouts.md): five invoices traced end to end
5. [output/billing_reply_tela.md](output/billing_reply_tela.md): a plain-language reply to a customer's billing question
6. [MEMO.md](MEMO.md): the policy memo and judgment calls
7. [SPEC.md](SPEC.md): the full requirements and accounting policies

Supporting files in `output/`: invoices, revenue schedule, billing ledger, GL export, rollforwards, AR aging, collections log, exceptions, lag report, and passed adjustments log.

## How it works

Usage events → pricing (free tier, graduated tiers, billing limit) → billing ledger (every billing event, one `ledger_id` each) → revenue engine (SPEC 3.1–3.5) → GL export through a finance-owned account mapping → rollforwards, aging, reconciliation, close checklist, and workpapers. The GL comes only from the billing ledger.

## Accounting policies at a glance

| Topic | Treatment | Reference |
|---|---|---|
| Usage | Recognized in the month received (UTC) | SPEC 3.1–3.2; RR 3.3.2, RR 5.5.1 |
| HM-side lag | 1% estimate at close, trued up as a change in estimate | SPEC 3.2; ASC 250 |
| Prepaid credit | Contract liability; revenue at $0.80 per $1.00 consumed | SPEC 3.3; RR 6.4.3 |
| Breakage | Constrained to zero | SPEC 3.3; RR 7.4, ASC 606-10-32-11 |
| Billing limit | Applied before revenue; never billed or recognized | SPEC 3.4 |
| Concession | Contra-revenue in the period of change | SPEC 3.4; RR 4.3.3.1, RR 5.5.2 |

## Run it

Requires Python 3.11 or later.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py                   # regenerates data/ and output/ (fixed seed: identical every run)
pytest                          # every test, including the SPEC 8 acceptance tests
```

## How I built this

I set the scope, the accounting policies, and the expected results, and reviewed and approved every step. Claude helped draft the spec, and Claude Code wrote the code one step at a time, with tests. The commit history shows the process. [MEMO.md](MEMO.md) is my own writing.

## Notes and limitations

- The close checklist shows "11 of 12 steps complete" each month by design: the Controller's sign-off is manual, and the model never marks it complete.
- The lag estimate applies the lag rate to dollars rather than re-rating units through the tiers (a simplification, SPEC 3.2).
- **Next:** the revenue lead sheet and the tickmarked contract liability rollforward. Out of scope for v1: see SPEC section 11.

## Repo layout

| Folder or file | Contents |
|---|---|
| `data/` | Synthetic inputs (generated by `run.py`) |
| `config/` | Chart of accounts and account mapping (kept by hand) |
| `revrec/` | The model, one module per step |
| `output/` | Every generated output |
| `tests/` | pytest tests, including `test_acceptance.py` |
| `run.py` | Runs the whole quarter's close |

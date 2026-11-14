# usage-rev-rec

A usage-based revenue recognition model under ASC 606 for a fictional SaaS company, Hedgehog Metrics, Inc. It covers one quarter (January–March 2026) for three customers: usage, billing, revenue, journal entries, AR, reconciliations, and close.

**All data is synthetic.** The full requirements are in [SPEC.md](SPEC.md).

## Setup

Requires Python 3.11 or later.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python run.py    # generate data and outputs
pytest           # run the tests
```

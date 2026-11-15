"""SPEC 8 acceptance tests, run against the whole quarter's close in one command (build step 10).

`close_quarter()` runs end to end in a temporary folder, then:
1. Every journal entry balances.
2. Each rollforward ties to the GL.
3. The reconciliation has zero unexplained difference in each month.
4. All close checklist checks pass.
5. The model matches every expected result in the SPEC 5 check scenarios.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

import run
from revrec.billing import ar_balances
from revrec.gl import account_balances
from revrec.revenue import revenue_by
from revrec.rollforwards import closing

D = Decimal
MONTHS = ["2026-01", "2026-02", "2026-03"]


@pytest.fixture(scope="module")
def quarter(tmp_path_factory):
    return run.close_quarter(tmp_path_factory.mktemp("quarter"))


# --- 1-4: the acceptance tests in SPEC 8 ----------------------------------------------------------

def test_1_every_journal_entry_balances(quarter):
    for je, lines in quarter["gl"].groupby("je_id"):
        assert sum(D(d) for d in lines.debit) == sum(D(c) for c in lines.credit), je
    assert sum(account_balances(quarter["gl"]).values()) == 0  # and the trial balance is in balance


def test_2_each_rollforward_ties_to_the_gl(quarter):
    differences = quarter["rollforwards"][quarter["rollforwards"].line == "difference"]
    assert len(differences) == 30
    assert (differences.amount == "0.00").all()


def test_3_zero_unexplained_difference_each_month(quarter):
    for month in MONTHS:
        for bridge in quarter["reconciliation"][month]:
            assert bridge.unexplained == 0, (month, bridge.key)


def test_4_all_close_checklist_checks_pass(quarter):
    for month in MONTHS:
        results = quarter["close"]["checklist"][month]
        failed = [name for name, (passed, _) in results.items() if passed is False]
        assert failed == [], month
        # The only step without an automated check is the manual sign-off.
        assert [name for name, (passed, _) in results.items() if passed is None] == ["Close sign-off"]


# --- 5: every SPEC 5 expected result ---------------------------------------------------------------

def schedule_amount(quarter, **filters):
    rows = quarter["schedule"]
    for column, value in filters.items():
        rows = rows[rows[column] == value]
    return sum((D(a) for a in rows.amount), D("0"))


def test_5_spec_5_expected_results(quarter):
    s = quarter["schedule"]
    by = revenue_by(s, "month", "customer_id")
    by_month = revenue_by(s, "month")
    rf = quarter["rollforwards"]
    lines = quarter["lines"]
    _, unbilled = ar_balances(quarter["ledger"], "2026-03-31")
    billed, _ = ar_balances(quarter["ledger"], "2026-03-31")
    paid = quarter["payments"].set_index("invoice_id").amount
    true_up = lines[lines.line_type == "true_up"].amount.iloc[0]

    checks = {
        "1":  (schedule_amount(quarter, month="2026-01", customer_id="HOOD", policy="usage"), "3225.00"),
        "1a": (schedule_amount(quarter, month="2026-01", customer_id="HOOD", policy="lag_estimate"), "32.25"),
        "1b": (D(true_up), "40.00"),
        "1b change": (schedule_amount(quarter, month="2026-02", customer_id="HOOD", policy="lag_true_up")
                      + schedule_amount(quarter, month="2026-02", customer_id="HOOD", policy="lag_estimate_reversal"), "7.75"),
        "1c": (by[("2026-02", "HOOD")], "3265.00"),
        "1d": (by[("2026-03", "HOOD")], "3275.00"),
        "2":  (sum(D(a) for a in quarter["ledger"][quarter["ledger"].event_type == "credit_drawdown"].amount), "39725.00"),
        "2a": (schedule_amount(quarter, customer_id="MOCK"), "31780.00"),
        "2b": (closing(rf, "contract_liability", "MOCK", "2026-03"), "48220.00"),
        "3":  (quarter["invoices"].set_index("invoice_id").loc["INV-2026-01-TELA", "total"], "6450.00"),
        "3a": (by[("2026-02", "TELA")], "3200.00"),
        "3b": (D(paid["INV-2026-01-TELA"]), "4950.00"),
        "3c": (by[("2026-03", "TELA")], "4125.00"),
        "4":  (by_month["2026-03"], "17940.00"),
        "4 threshold": (D(quarter["close"]["passed_log"].threshold.iloc[0]), "89.70"),
        "5":  (sum(billed.values()), "4700.00"),
        "5b": (sum(unbilled.values()), "7432.25"),
        "6 Jan": (by_month["2026-01"], "18927.25"),
        "6 Feb": (by_month["2026-02"], "18485.00"),
        "6a": (sum(by_month.values()), "55352.25"),
    }
    wrong = {k: (str(actual), expected) for k, (actual, expected) in checks.items() if actual != D(expected)}
    assert wrong == {}

    # 5a: unbilled AR from usage, before the March lag estimate.
    assert sum(unbilled.values()) - D("32.25") == D("7400.00")

    # 7: trial balance at March 31.
    assert account_balances(quarter["gl"]) == {
        "1000": D("98340.00"), "1100": D("4700.00"), "1150": D("7432.25"), "2400": D("-48220.00"),
        "3000": D("-6900.00"), "4000": D("-25040.00"), "4010": D("-32.25"), "4100": D("-31780.00"),
        "4900": D("1500.00")}

    # 8: rollforward month-end balances.
    expected_8 = {("contract_liability", "MOCK"): ["70780.00", "58760.00", "48220.00"],
                  ("credit_balance_at_list", "MOCK"): ["88475.00", "73450.00", "60275.00"],
                  ("billed_ar", "ALL"): ["0.00", "3225.00", "4700.00"],
                  ("unbilled_ar", "ALL"): ["9707.25", "7997.25", "7432.25"]}
    for (name, customer), values in expected_8.items():
        assert [closing(rf, name, customer, m) for m in MONTHS] == [D(v) for v in values], name

    # 9: bridge results.
    results = {m: {b.key: b.actual for b in quarter["reconciliation"][m]} for m in MONTHS}
    assert [results[m]["B"] for m in MONTHS] == [D("9675.00"), D("7965.00"), D("7400.00")]
    assert [results[m]["C"] for m in MONTHS] == [D("18927.25"), D("18485.00"), D("17940.00")]
    assert [results[m]["D"] for m in MONTHS] == [D("86900.00"), D("4950.00"), D("6490.00")]


# --- One command, reproducible -------------------------------------------------------------------------

def test_the_close_is_reproducible(quarter, tmp_path):
    again = run.close_quarter(tmp_path)
    for folder, count in [("data", 9), ("output", 15), ("docs", 1)]:  # 9 inputs; 13 outputs + 2 workpapers; the page
        first, second = quarter["root"] / folder, again["root"] / folder
        files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
        assert len(files) == count, folder
        for name in files:
            assert (first / name).read_bytes() == (second / name).read_bytes(), name


# --- README -----------------------------------------------------------------------------------------------

README = Path(__file__).parent.parent / "README.md"


def test_readme_results_table_matches_the_model(quarter):
    text = README.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| Revenue |"))
    figures = [D(x.replace(",", "")) for x in re.findall(r"[\d,]+\.\d{2}", row)]
    by_month = revenue_by(quarter["schedule"], "month")
    assert figures == [by_month[m] for m in MONTHS] + [sum(by_month.values())]


def test_readme_links_point_to_files_that_exist():
    text = README.read_text(encoding="utf-8")
    root = README.parent
    for target in re.findall(r"\]\(([^)#]+)\)", text):
        if target.startswith("http"):
            continue
        assert (root / target).exists(), target

"""Tests for rollforwards, AR aging, and the collections log (SPEC 3.3, 3.4, 6, 7; SPEC 5 check 8)."""

from decimal import Decimal
from pathlib import Path

import pytest

from revrec import generate_data
from revrec.billing import invoice_totals, run_billing
from revrec.collections import run_collections
from revrec.gl import run_gl
from revrec.revenue import run_revenue
from revrec.rollforwards import MONTHS, closing, run_rollforwards

D = Decimal
CONFIG = Path(__file__).parent.parent / "config"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    output = tmp_path_factory.mktemp("output")
    generate_data.generate(data)
    lines, _, billing_ledger = run_billing(data, output)
    ledger, _, _ = run_revenue(data, output, billing_ledger)
    gl, _, _, _ = run_gl(CONFIG, data, output, ledger)
    rollforwards = run_rollforwards(data, output, ledger, gl)
    aging, log = run_collections(data, output, ledger, invoice_totals(lines), gl)
    return {"data": data, "output": output, "ledger": ledger, "gl": gl, "lines": lines,
            "rf": rollforwards, "aging": aging, "log": log}


# --- SPEC 5, check 8: month-end balances -----------------------------------------------------

@pytest.mark.parametrize("name, customer, expected", [
    ("contract_liability", "MOCK", ["70780.00", "58760.00", "48220.00"]),
    ("credit_balance_at_list", "MOCK", ["88475.00", "73450.00", "60275.00"]),
    ("billed_ar", "ALL", ["0.00", "3225.00", "4700.00"]),
    ("unbilled_ar", "ALL", ["9707.25", "7997.25", "7432.25"]),
])
def test_month_end_closing_balances(built, name, customer, expected):
    assert [closing(built["rf"], name, customer, m) for m in MONTHS] == [D(e) for e in expected]


def test_movements_match_spec(built):
    rf = built["rf"]

    def line(name, customer, month, label):
        rows = rf[(rf.rollforward == name) & (rf.customer_id == customer) & (rf.month == month) & (rf.line == label)]
        return D(rows.amount.iloc[0])

    assert line("contract_liability", "MOCK", "2026-01", "invoiced") == D("80000")
    assert [line("contract_liability", "MOCK", m, "recognized") for m in MONTHS] == [D("-9220"), D("-12020"), D("-10540")]
    assert [line("billed_ar", "ALL", m, "billed") for m in MONTHS] == [D("86900"), D("9675"), D("7965")]
    assert [line("billed_ar", "ALL", m, "cash") for m in MONTHS] == [D("-86900"), D("-4950"), D("-6490")]
    assert [line("billed_ar", "ALL", m, "credits") for m in MONTHS] == [D("0"), D("-1500"), D("0")]
    assert [line("unbilled_ar", "ALL", m, "accrued") for m in MONTHS] == [D("9707.25"), D("7965.00"), D("7400.00")]
    assert [line("unbilled_ar", "ALL", m, "invoiced") for m in MONTHS] == [D("-6900"), D("-9675"), D("-7965")]


def test_february_balances_by_customer(built):
    # Billed AR at Feb 28 is Harry Hood's January invoice; unbilled is HH $3,225 + $40 + $32.25 and Tela $4,700.
    rf = built["rf"]
    assert closing(rf, "billed_ar", "HOOD", "2026-02") == D("3225.00")
    assert closing(rf, "unbilled_ar", "HOOD", "2026-02") == D("3297.25")
    assert closing(rf, "unbilled_ar", "TELA", "2026-02") == D("4700.00")


# --- Each rollforward is internally consistent and ties to the GL -------------------------------

def test_january_opening_comes_from_opening_balances(built):
    rf = built["rf"]
    jan_open = rf[(rf.month == "2026-01") & (rf.line == "opening")].set_index(["rollforward", "customer_id"]).amount
    assert jan_open[("unbilled_ar", "ALL")] == "6900.00"
    assert jan_open[("unbilled_ar", "HOOD")] == "3100.00"
    assert jan_open[("unbilled_ar", "TELA")] == "3800.00"
    assert jan_open[("billed_ar", "ALL")] == "0.00"
    assert jan_open[("contract_liability", "MOCK")] == "0.00"


def test_opening_plus_movements_equals_closing_and_rolls_forward(built):
    rf = built["rf"]
    for (name, customer), rows in rf.groupby(["rollforward", "customer_id"]):
        previous_closing = None
        for month in MONTHS:
            block = rows[rows.month == month].set_index("line").amount.map(D)
            movements = block.drop(["opening", "closing", "difference"], errors="ignore")
            movements = movements[~movements.index.str.startswith(("GL ", "closing x"))]
            assert block["opening"] + movements.sum() == block["closing"], (name, customer, month)
            if previous_closing is not None:
                assert block["opening"] == previous_closing, (name, customer, month)
            previous_closing = block["closing"]


def test_every_rollforward_ties_to_the_gl(built):
    # SPEC 7: each rollforward ties to the GL; contract liability = remaining credit x 0.80.
    rf = built["rf"]
    differences = rf[rf.line == "difference"]
    assert len(differences) == 3 * (1 + 1 + 4 + 4)  # months x (CL, credit, billed AR x 4, unbilled AR x 4)
    assert (differences.amount == "0.00").all()


# --- AR aging -------------------------------------------------------------------------------------

def test_aging_at_march_31(built):
    aging = built["aging"]
    invoices = aging[aging.line == "open_invoice"]
    assert invoices[["invoice_id", "due_date", "days_past_due", "bucket", "amount", "1-30"]].values.tolist() == [
        ["INV-2026-02-TELA", "2026-03-18", "13", "1-30", "4700.00", "4700.00"]]  # SPEC 3.4


def test_aging_ties_to_gl_and_unbilled_is_not_aged(built):
    lines = built["aging"].set_index("line").amount
    assert lines["total_billed_ar"] == lines["GL 1100 balance"] == "4700.00"
    assert lines["memo: unbilled AR (not aged)"] == lines["GL 1150 balance"] == "7432.25"
    assert (built["aging"][built["aging"].line == "difference"].amount == "0.00").all()


# --- Collections log ------------------------------------------------------------------------------

def test_collections_log(built):
    # SPEC 3.4: reminder at day 5 (Mar 23), follow-up at day 15 (Apr 2, after the period).
    log = built["log"]
    assert log[["invoice_id", "action", "action_date", "days_past_due", "open_amount", "status"]].values.tolist() == [
        ["INV-2026-02-TELA", "reminder", "2026-03-23", 5, "4700.00", "sent"],
        ["INV-2026-02-TELA", "follow_up", "2026-04-02", 15, "4700.00", "scheduled (after period end)"],
    ]


def test_invoices_paid_on_time_get_no_collections_actions(built):
    # Tela paid January on Feb 17, a day before it was due; Harry Hood always pays early.
    assert set(built["log"].invoice_id) == {"INV-2026-02-TELA"}


def test_rerun_is_identical(built, tmp_path):
    run_rollforwards(built["data"], tmp_path, built["ledger"], built["gl"])
    run_collections(built["data"], tmp_path, built["ledger"], invoice_totals(built["lines"]), built["gl"])
    for name in ["rollforwards.csv", "ar_aging.csv", "collections_log.csv"]:
        assert (tmp_path / name).read_bytes() == (built["output"] / name).read_bytes(), name

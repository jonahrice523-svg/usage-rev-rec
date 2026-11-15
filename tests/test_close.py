"""Tests for the reconciliation and close outputs (SPEC 3.2, 6 items 6-8, 7, 8; SPEC 5 check 9)."""

from decimal import Decimal
from pathlib import Path

import pytest

from revrec import generate_data
from revrec.billing import invoice_totals, load_inputs, run_billing
from revrec.close import STEPS, run_close
from revrec.gl import run_gl
from revrec.reconciliation import run_reconciliation
from revrec.revenue import load_assumptions, run_revenue
from revrec.rollforwards import run_rollforwards
from revrec.usage import load_usage

D = Decimal
CONFIG = Path(__file__).parent.parent / "config"
MONTHS = ["2026-01", "2026-02", "2026-03"]


def build(data, output, tamper_gl=None):
    lines, _, billing_ledger = run_billing(data, output)
    ledger, schedule, unusual = run_revenue(data, output, billing_ledger)
    gl, mapped, controls, chart = run_gl(CONFIG, data, output, ledger)
    if tamper_gl:
        gl = tamper_gl(gl)
    rollforwards = run_rollforwards(data, output, ledger, gl)
    inputs = load_inputs(data)
    reconciliation = run_reconciliation(output, load_usage(data / "usage_events.csv"), inputs, ledger, lines,
                                        schedule, gl, chart, rollforwards)
    close = run_close(output, inputs=inputs, assumptions=load_assumptions(data), mapped=mapped,
                      unusual_exceptions=unusual, ledger=ledger, lines=lines, invoices_frame=invoice_totals(lines),
                      schedule=schedule, gl=gl, chart=chart, integration_controls=controls,
                      rollforwards=rollforwards, reconciliation=reconciliation, reminder_days=5, followup_days=15)
    return {"data": data, "output": output, "reconciliation": reconciliation, **close}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    generate_data.generate(data)
    return build(data, tmp_path_factory.mktemp("output"))


def bridge(built, month, key):
    return next(b for b in built["reconciliation"][month] if b.key == key)


def lines_of(b):
    return [amount for _, amount in b.lines]


# --- SPEC 5, check 9: reconciliation bridges B-D -------------------------------------------------

@pytest.mark.parametrize("month, items, invoices", [
    ("2026-01", ["21725.00", "-525.00", "-11525.00", "0.00"], "9675.00"),
    ("2026-02", ["23075.00", "-125.00", "-15025.00", "40.00"], "7965.00"),
    ("2026-03", ["20525.00", "0.00", "-13175.00", "50.00"], "7400.00"),
])
def test_bridge_b_usage_to_invoice(built, month, items, invoices):
    b = bridge(built, month, "B")
    assert lines_of(b) == [D(i) for i in items]
    assert b.actual == D(invoices)


@pytest.mark.parametrize("month, items, revenue", [
    ("2026-01", ["21725.00", "-525.00", "-2305.00", "32.25", "0.00", "0.00", "0.00"], "18927.25"),
    ("2026-02", ["23075.00", "-125.00", "-3005.00", "32.25", "-32.25", "40.00", "-1500.00"], "18485.00"),
    ("2026-03", ["20525.00", "0.00", "-2635.00", "32.25", "-32.25", "50.00", "0.00"], "17940.00"),
])
def test_bridge_c_usage_to_revenue(built, month, items, revenue):
    b = bridge(built, month, "C")
    assert lines_of(b) == [D(i) for i in items]
    assert b.actual == b.gl_revenue == D(revenue)  # schedule and GL agree


@pytest.mark.parametrize("month, items, cash", [
    ("2026-01", ["18927.25", "-2807.25", "0.00", "70780.00"], "86900.00"),
    ("2026-02", ["18485.00", "1710.00", "-3225.00", "-12020.00"], "4950.00"),
    ("2026-03", ["17940.00", "565.00", "-1475.00", "-10540.00"], "6490.00"),
])
def test_bridge_d_revenue_to_cash(built, month, items, cash):
    b = bridge(built, month, "D")
    assert lines_of(b) == [D(i) for i in items]
    assert b.actual == D(cash)


def test_zero_unexplained_difference_every_month(built):
    # SPEC 8 acceptance test.
    for month in MONTHS:
        for b in built["reconciliation"][month]:
            assert b.unexplained == 0, (month, b.key)
            for row in b.detail:
                assert row[-1] == 0, (month, row)


def test_bridge_a_counts_duplicates_and_late_units_in_january(built):
    jan = bridge(built, "2026-01", "A")
    labels = dict(jan.lines)
    assert labels["Late units processed after the cutoff (SPEC 3.2)"] == 2_000_000 + 2_500_000  # lag + bug fix
    assert labels["Duplicate units removed, never billed (SPEC 3.2)"] > 0


def test_reconciliation_markdown_is_readable(built):
    text = (built["output"] / "reconciliation.md").read_text(encoding="utf-8")
    assert text.count("**Unexplained difference: $0.00**") == 9  # bridges B-D x 3 months
    assert text.count("**Unexplained difference: 0**") == 3      # bridge A x 3 months
    for b in built["reconciliation"]["2026-01"]:
        assert b.explanation in text


# --- Exceptions, lag report, passed adjustments ------------------------------------------------------

def test_exceptions_are_the_two_resolved_duplicates(built):
    exceptions = built["exceptions"]
    assert exceptions.type.tolist() == ["duplicate_usage", "duplicate_usage"]
    assert (exceptions.status == "resolved").all()


def test_lag_report(built):
    report = built["lag_report"].set_index("usage_month")
    assert report.loc["2026-01", ["estimate", "actual_late_usage", "change_in_estimate", "recognized_in"]].tolist() == [
        "32.25", "40.00", "7.75", "2026-02"]
    assert report.loc["2026-02", ["estimate", "actual_late_usage", "change_in_estimate"]].tolist() == [
        "32.25", "0.00", "-32.25"]
    assert report.loc["2026-03", "actual_late_usage"] == "pending"


def test_passed_adjustments_log(built):
    log = built["passed_log"]
    assert log[["month", "amount", "month_total_revenue", "threshold", "below_threshold", "running_total"]].values.tolist() == [
        ["2026-03", "50.00", "17940.00", "89.70", "yes", "50.00"]]


# --- Close checklist ------------------------------------------------------------------------------------

def test_every_automated_check_passes_each_month(built):
    # SPEC 8 acceptance test: all close checklist checks pass.
    for month in MONTHS:
        results = built["checklist"][month]
        automated = {name: passed for name, (passed, _) in results.items() if passed is not None}
        assert len(automated) == 11
        assert all(automated.values()), (month, [n for n, p in automated.items() if not p])


def test_sign_off_is_manual_and_pending(built):
    for month in MONTHS:
        assert built["checklist"][month]["Close sign-off"][0] is None


def test_preparer_and_reviewer_always_differ():
    for step in STEPS:
        assert step.preparer != step.reviewer, step.name
    assert {s.reviewer for s in STEPS if s.preparer != "Controller"} == {"Controller"}


def test_checklist_markdown_summary_and_columns(built):
    text = (built["output"] / "close_checklist.md").read_text(encoding="utf-8")
    for name in ["January", "February", "March"]:
        assert f"**{name} close: 11 of 12 steps complete, 1 outstanding.** Outstanding: Close sign-off." in text
    assert "| Due | Step | Preparer | Reviewer | Automated check | Result | Status |" in text
    assert "Finance Manager, Revenue Accounting" in text
    assert "Billing engineering" in text


def test_a_one_cent_gl_error_fails_the_checks(tmp_path):
    # A balanced one-cent misposting on Feb 28 (Dr unbilled AR, Cr usage revenue): the trial balance
    # still balances, but the revenue tie-out and the unbilled AR rollforward catch it.
    data = tmp_path / "data"
    generate_data.generate(data)
    output = tmp_path / "output"
    output.mkdir()

    def tamper(gl):
        gl = gl.copy()
        feb_28 = (gl.entry_date == "2026-02-28") & (gl.customer_id == "HOOD")
        revenue = gl.index[feb_28 & (gl.account == "4000")][0]
        unbilled = gl.index[feb_28 & (gl.account == "1150")][0]
        gl.loc[revenue, "credit"] = f"{D(gl.loc[revenue, 'credit']) + D('0.01'):.2f}"
        gl.loc[unbilled, "debit"] = f"{D(gl.loc[unbilled, 'debit']) + D('0.01'):.2f}"
        return gl

    broken = build(data, output, tamper_gl=tamper)
    feb = broken["checklist"]["2026-02"]
    assert feb["Revenue schedule ties to the GL"][0] is False
    assert feb["Rollforwards tie to the GL"][0] is False
    assert broken["checklist"]["2026-01"]["Rollforwards tie to the GL"][0] is True  # January is unaffected
    summary = (output / "close_checklist.md").read_text(encoding="utf-8")
    assert "February close: 11 of 12" not in summary


def test_rerun_is_identical(built, tmp_path):
    rerun = build(built["data"], tmp_path)
    for name in ["reconciliation.md", "close_checklist.md", "exceptions.csv", "lag_report.csv",
                 "passed_adjustments_log.csv"]:
        assert (tmp_path / name).read_bytes() == (built["output"] / name).read_bytes(), name

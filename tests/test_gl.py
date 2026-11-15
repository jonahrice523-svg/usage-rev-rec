"""Tests for the account mapping, GL export, and integration controls (SPEC 4, 7; SPEC 5 check 7)."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from revrec import generate_data
from revrec.billing import run_billing
from revrec.gl import account_balances, map_ledger, read_text_csv, revenue_from_gl, run_gl
from revrec.revenue import revenue_by, run_revenue

D = Decimal
CONFIG = Path(__file__).parent.parent / "config"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    output = tmp_path_factory.mktemp("output")
    generate_data.generate(data)
    _, _, billing_ledger = run_billing(data, output)
    ledger, schedule, _ = run_revenue(data, output, billing_ledger)
    gl, mapped, controls, chart = run_gl(CONFIG, data, output, ledger)
    return {"data": data, "output": output, "ledger": ledger, "schedule": schedule,
            "gl": gl, "mapped": mapped, "controls": controls, "chart": chart,
            "mapping": read_text_csv(CONFIG / "account_mapping.csv"),
            "adjustments": read_text_csv(data / "adjustments.csv")}


# --- SPEC 5, check 7: trial balance at March 31 ----------------------------------------------

def test_trial_balance_at_march_31(built):
    # Debit balances positive, credit balances negative.
    assert account_balances(built["gl"]) == {
        "1000": D("98340.00"),    # cash
        "1100": D("4700.00"),     # billed AR: Tela's February invoice (check 5)
        "1150": D("7432.25"),     # unbilled AR including the March lag estimate (check 5b)
        "2400": D("-48220.00"),   # contract liability (check 2b)
        "3000": D("-6900.00"),    # retained earnings: offset to the opening unbilled AR
        "4000": D("-25040.00"),   # usage revenue
        "4010": D("-32.25"),      # lag estimate: three estimates less two reversals
        "4100": D("-31780.00"),   # prepaid credit revenue (check 2a)
        "4900": D("1500.00"),     # price concession
    }


def test_trial_balance_totals(built):
    balances = account_balances(built["gl"])
    debits = sum(v for v in balances.values() if v > 0)
    credits = -sum(v for v in balances.values() if v < 0)
    assert debits == credits == D("111972.25")


# --- Integration controls --------------------------------------------------------------------

def test_all_controls_pass(built):
    failed = [(name, detail) for name, passed, detail in built["controls"] if not passed]
    assert failed == []
    assert len(built["controls"]) == 5


def test_every_row_mapped_memo_or_after_period(built):
    ledger, mapped = built["ledger"], built["mapped"]
    posted = {p["ledger_id"] for p in mapped.postings}
    assert mapped.exceptions == []
    assert len(posted) + len(mapped.memo) + len(mapped.after_period) == len(ledger)
    # SPEC 3.3: credit drawdown at list value is memo only.
    memo_types = set(ledger[ledger.ledger_id.isin(mapped.memo)].event_type)
    assert memo_types == {"credit_drawdown"}


def test_rows_after_march_31_are_not_exported(built):
    ledger, mapped, gl = built["ledger"], built["mapped"], built["gl"]
    after = ledger[ledger.ledger_id.isin(mapped.after_period)]
    assert set(after.event_type) == {"lag_estimate_reversal", "invoice_issued", "payment_applied"}
    assert after.event_date.min() == "2026-04-01"
    assert gl.entry_date.max() <= "2026-03-31"


def test_unmapped_event_becomes_an_exception(built):
    ledger = built["ledger"].copy()
    extra = ledger.iloc[[0]].copy()
    extra["ledger_id"], extra["event_type"] = "BL-99999", "mystery_event"
    mapped = map_ledger(pd.concat([ledger, extra]), built["mapping"], built["chart"], built["adjustments"])
    assert [e["ledger_id"] for e in mapped.exceptions] == ["BL-99999"]
    assert "BL-99999" not in {p["ledger_id"] for p in mapped.postings}


def test_credit_memo_that_is_not_a_concession_becomes_an_exception(built):
    # Only price_concession is mapped (SPEC 3.4); a credit loss needs a person to classify it.
    adjustments = built["adjustments"].copy()
    adjustments["classification"] = "credit_loss"
    mapped = map_ledger(built["ledger"], built["mapping"], built["chart"], adjustments)
    assert [e["event_type"] for e in mapped.exceptions] == ["credit_memo"]


def test_every_journal_entry_balances(built):
    for je, lines in built["gl"].groupby("je_id"):
        assert sum(D(d) for d in lines.debit) == sum(D(c) for c in lines.credit), je


def test_gl_lines_trace_to_ledger_ids(built):
    known = set(built["ledger"].ledger_id)
    for ids in built["gl"].ledger_ids:
        assert ids and set(ids.split(";")) <= known


# --- Posting uses amount only ------------------------------------------------------------------

def test_cap_never_reaches_the_gl(built):
    # SPEC 3.4: Tela's January replay posts at the billed $1,000, never $1,525 or the $525 cap.
    gl = built["gl"]
    replay = gl[(gl.account == "4000") & (gl.customer_id == "TELA") & (gl["product"] == "session_replay")]
    assert replay.set_index("entry_date").credit.to_dict() == {
        "2026-01-31": "1000.00", "2026-02-28": "1000.00", "2026-03-31": "925.00"}
    assert not gl.debit.isin(["525.00", "125.00"]).any()
    assert not gl.credit.isin(["525.00", "125.00"]).any()


def test_contract_liability_moves_at_cash_value(built):
    # SPEC 3.3: the GL moves at 0.80, never at the $39,725 list value of credit consumed.
    gl = built["gl"]
    cl = gl[gl.account == "2400"]
    assert sum(D(d) for d in cl.debit) == D("31780.00")
    assert sum(D(c) for c in cl.credit) == D("80000.00")


# --- Revenue from the GL ties to the revenue schedule -------------------------------------------

def nonzero(d):
    return {k: v for k, v in d.items() if v != 0}


def test_gl_revenue_by_month_equals_schedule(built):
    assert nonzero(revenue_from_gl(built["gl"], built["chart"], "month")) == nonzero(
        revenue_by(built["schedule"], "month"))


def test_gl_revenue_by_product_and_month_equals_schedule(built):
    # Supports the ASC 606 disaggregation of revenue from the GL.
    from_gl = revenue_from_gl(built["gl"], built["chart"], "product", "month")
    from_schedule = revenue_by(built["schedule"], "product", "month")
    assert nonzero(from_gl) == nonzero(from_schedule)
    assert from_gl[("event_analytics", "2026-02")] == from_schedule[("event_analytics", "2026-02")]


def test_product_only_on_revenue_accounts(built):
    gl = built["gl"]
    revenue_accounts = {"4000", "4010", "4100", "4900"}
    assert (gl[~gl.account.isin(revenue_accounts)]["product"] == "").all()
    # Every revenue line except the customer-level lag estimate carries a product.
    product_lines = gl[gl.account.isin({"4000", "4100", "4900"})]
    assert (product_lines["product"] != "").all()
    assert gl[gl.account == "4900"]["product"].tolist() == ["event_analytics"]


def test_rerun_is_identical(built, tmp_path):
    run_gl(CONFIG, built["data"], tmp_path, built["ledger"])
    assert (tmp_path / "gl_export.csv").read_bytes() == (built["output"] / "gl_export.csv").read_bytes()

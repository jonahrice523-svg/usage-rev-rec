"""Tests for the Tela billing reply, controls matrix, and sample tie-outs (SPEC 3.4, 6 item 9, 7, 8)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from revrec import generate_data
from revrec.billing import invoice_totals, load_inputs, read_text_csv, run_billing
from revrec.billing_reply import run_billing_reply
from revrec.close import run_close
from revrec.gl import run_gl
from revrec.reconciliation import run_reconciliation
from revrec.revenue import load_assumptions, run_revenue
from revrec.rollforwards import run_rollforwards
from revrec.usage import load_usage
from revrec.workpapers import CONTROLS, SAMPLES, build_controls_matrix, run_workpapers

D = Decimal
CONFIG = Path(__file__).parent.parent / "config"
MONTHS = ["2026-01", "2026-02", "2026-03"]


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    output = tmp_path_factory.mktemp("output")
    generate_data.generate(data)
    lines, _, billing_ledger = run_billing(data, output)
    ledger, schedule, unusual = run_revenue(data, output, billing_ledger)
    gl, mapped, controls, chart = run_gl(CONFIG, data, output, ledger)
    rollforwards = run_rollforwards(data, output, ledger, gl)
    inputs = load_inputs(data)
    invoices = invoice_totals(lines)
    raw = load_usage(data / "usage_events.csv")
    reconciliation = run_reconciliation(output, raw, inputs, ledger, lines, schedule, gl, chart, rollforwards)
    close = run_close(output, inputs=inputs, assumptions=load_assumptions(data), mapped=mapped,
                      unusual_exceptions=unusual, ledger=ledger, lines=lines, invoices_frame=invoices,
                      schedule=schedule, gl=gl, chart=chart, integration_controls=controls,
                      rollforwards=rollforwards, reconciliation=reconciliation, reminder_days=5, followup_days=15)
    reply_text, reply = run_billing_reply(output, lines, inputs.limits)
    workpapers = run_workpapers(output, checklist=close["checklist"], integration_controls=controls, raw_usage=raw,
                                usage_summary=inputs.usage, ledger=ledger, lines=lines, invoices=invoices, gl=gl,
                                mapping=read_text_csv(CONFIG / "account_mapping.csv"),
                                adjustments=inputs.adjustments, cutoff_day=inputs.cutoff_business_day)
    return {"output": output, "lines": lines, "reply_text": reply_text, "reply": reply, "close": close,
            "controls": controls, "workpapers": workpapers, "invoices": invoices.set_index("invoice_id")}


# --- Tela billing reply ------------------------------------------------------------------------------

def test_reply_totals_tie_to_the_invoices(built):
    reply, invoices = built["reply"], built["invoices"]
    assert reply["dec_total"] == invoices.loc["INV-2025-12-TELA", "total"] == D("3800.00")
    assert reply["jan_total"] == invoices.loc["INV-2026-01-TELA", "total"] == D("6450.00")
    assert "$6,450.00" in built["reply_text"] and "$3,800.00" in built["reply_text"] and "+$2,650.00" in built["reply_text"]


def test_reply_compares_units_and_dollars_by_product(built):
    rows = {r[0]: r[1:] for r in built["reply"]["rows"]}
    assert rows["event_analytics"] == (90_000_000, 200_000_000, D("2100.00"), D("4300.00"))
    assert rows["session_replay"] == (287_500, 600_000, D("900.00"), D("1000.00"))
    assert rows["feature_flags"] == (9_000_000, 15_000_000, D("800.00"), D("1150.00"))
    assert "your event volume more than doubled" in built["reply_text"]


def test_reply_explains_the_cap_from_the_invoice_line(built):
    lines = built["lines"]
    cap_line = lines[(lines.invoice_id == "INV-2026-01-TELA") & (lines.line_type == "billing_limit")]
    assert -D(cap_line.amount.iloc[0]) == built["reply"]["capped"] == D("525.00")
    assert "would have cost $1,525.00" in built["reply_text"]


def test_reply_is_dated_before_the_dispute_and_promises_no_credit(built):
    text = built["reply_text"]
    assert "**Date:** February 5, 2026" in text
    assert "new environment" in text and "billing limit on event analytics" in text
    for word in ["credit", "refund", "discount"]:
        assert word not in text.lower(), word


def test_reply_avoids_accounting_terms(built):
    text = built["reply_text"].lower()
    for term in ["revenue", "contract liability", "asc ", "accrual", "recognized", "deferred", "receivable", "gl "]:
        assert term not in text, term


def test_reply_signed_by_the_team(built):
    assert built["reply_text"].rstrip().endswith("Hedgehog Metrics Billing Team")


# --- Controls matrix -----------------------------------------------------------------------------------

def test_controls_matrix_covers_every_spec_7_control_and_passes(built):
    results = built["workpapers"]["control_results"]
    names = ["Completeness", "Cutoff", "Close threshold", "Pricing accuracy", "Integration", "Balance",
             "Rollforwards", "Reconciliation"]
    assert [c.name for c in CONTROLS] == names
    for month in MONTHS:
        assert results[month] == {name: True for name in names}, month


def test_controls_matrix_evidence_files_exist(built):
    for control in CONTROLS:
        for filename in re.findall(r"[\w]+\.(?:csv|md)", control.evidence):
            assert (built["output"] / filename).exists(), (control.name, filename)


def test_controls_matrix_owners_and_reviewer(built):
    owners = {c.name: c.owner for c in CONTROLS}
    assert owners["Completeness"] == owners["Pricing accuracy"] == "Billing engineering"
    assert {owners[n] for n in ["Cutoff", "Close threshold", "Integration", "Reconciliation"]} == {
        "Finance Manager, Revenue Accounting"}
    assert owners["Balance"] == owners["Rollforwards"] == "GL accountant"
    text = (built["output"] / "workpapers" / "controls_matrix.md").read_text(encoding="utf-8")
    assert text.count("| Controller |") == len(CONTROLS)
    assert "auditor" not in text.lower()  # SPEC 9: left for the memo


def test_a_failed_check_shows_as_fail_in_the_matrix(built):
    checklist = {m: dict(built["close"]["checklist"][m]) for m in MONTHS}
    checklist["2026-02"]["Rollforwards tie to the GL"] = (False, "broken")
    text, results = build_controls_matrix(checklist, built["controls"])
    assert results["2026-02"]["Rollforwards"] is False
    assert results["2026-01"]["Rollforwards"] is True
    assert "**FAIL**" in text


# --- Sample tie-outs -----------------------------------------------------------------------------------

def test_five_samples_cover_every_customer_and_the_required_invoices():
    ids = [invoice_id for invoice_id, _ in SAMPLES]
    assert len(ids) == 5
    assert {"INV-2026-01-TELA", "INV-2026-01-MOCK"} <= set(ids)
    assert {i.split("-")[-1] for i in ids} == {"HOOD", "MOCK", "TELA"}


def test_every_sample_ties(built):
    for invoice_id, checks in built["workpapers"]["tieout_checks"].items():
        failed = [name for name, passed, _ in checks if not passed]
        assert failed == [], invoice_id


def test_sample_open_balances_at_march_31(built):
    # Only Tela's February invoice is open at March 31 (SPEC 5, check 5).
    assert built["workpapers"]["open_balances"] == {
        "INV-2026-01-TELA": D("0.00"), "INV-2026-01-MOCK": D("0.00"), "INV-2026-02-HOOD": D("0.00"),
        "INV-2026-02-TELA": D("4700.00"), "INV-2025-12-HOOD": D("0.00")}


def test_tela_january_trace_shows_the_cap_credit_memo_and_short_pay(built):
    text = (built["output"] / "workpapers" / "sample_tieouts.md").read_text(encoding="utf-8")
    section = text.split("## INV-2026-01-TELA")[1].split("## INV-")[0]
    for expected in ["billing_limit", "-525.00", "credit_memo", "1,500.00", "4900 Price concessions",
                     "PAY-0004", "4,950.00", "6,450.00 - 1,500.00 = 4,950.00"]:
        assert expected in section, expected


def test_mockingbird_trace_shows_liability_then_drawdown(built):
    text = (built["output"] / "workpapers" / "sample_tieouts.md").read_text(encoding="utf-8")
    section = text.split("## INV-2026-01-MOCK")[1].split("## INV-")[0]
    for expected in ["1100 / 2400", "credit_drawdown", "memo only", "2400 / 4100", "80,000.00"]:
        assert expected in section, expected


def test_trace_ledger_ids_exist_in_the_gl(built):
    text = (built["output"] / "workpapers" / "sample_tieouts.md").read_text(encoding="utf-8")
    gl_ids = set()
    for ids in read_text_csv(built["output"] / "gl_export.csv").ledger_ids:
        gl_ids |= set(ids.split(";"))
    gl_rows = [line for line in text.splitlines() if line.startswith("| JE-")]
    for line in gl_rows:
        for ledger_id in re.findall(r"BL-\d{5}", line):
            assert ledger_id in gl_ids

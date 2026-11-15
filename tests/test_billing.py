"""Tests for invoicing, payments, and the billing ledger (SPEC 3.2-3.4, 4, 5)."""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from revrec import generate_data
from revrec.billing import ar_balances, invoice_totals, run_billing
from revrec.pricing import load_rate_card, price

D = Decimal


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    output = tmp_path_factory.mktemp("output")
    generate_data.generate(data)
    lines, payments, ledger = run_billing(data, output)
    return {"data": data, "output": output, "lines": lines, "payments": payments,
            "ledger": ledger, "invoices": invoice_totals(lines).set_index("invoice_id")}


def total(built, invoice_id):
    return built["invoices"].loc[invoice_id, "total"]


# --- Invoices -------------------------------------------------------------------

def test_invoice_totals(built):
    expected = {
        "INV-2025-12-HOOD": "3100.00", "INV-2025-12-TELA": "3800.00",   # SPEC 5 opening balances
        "INV-2026-01-MOCK": "80000.00",                                  # SPEC 3.3
        "INV-2026-01-HOOD": "3225.00", "INV-2026-01-TELA": "6450.00",   # SPEC 5, checks 1 and 3
        "INV-2026-02-HOOD": "3265.00", "INV-2026-02-TELA": "4700.00",   # $3,225 + $40 true-up; 3a
        "INV-2026-03-HOOD": "3275.00", "INV-2026-03-TELA": "4125.00",   # $3,225 + $50 bug fix; 3c
    }
    assert {k: str(v) for k, v in built["invoices"]["total"].items()} == expected


def test_invoice_dates(built):
    inv = built["invoices"]
    # SPEC 1: issued on business day 2; due after the customer's terms (Tela Net 15, SPEC 3.4).
    assert inv.loc["INV-2025-12-HOOD", ["issue_date", "due_date"]].tolist() == ["2026-01-02", "2026-02-01"]
    assert inv.loc["INV-2025-12-TELA", ["issue_date", "due_date"]].tolist() == ["2026-01-02", "2026-01-17"]
    assert inv.loc["INV-2026-01-MOCK", ["issue_date", "due_date"]].tolist() == ["2026-01-01", "2026-01-31"]
    assert inv.loc["INV-2026-01-TELA", ["issue_date", "due_date"]].tolist() == ["2026-02-03", "2026-02-18"]
    assert inv.loc["INV-2026-02-TELA", ["issue_date", "due_date"]].tolist() == ["2026-03-03", "2026-03-18"]
    assert inv.loc["INV-2026-01-HOOD", "issue_date"] == "2026-02-03"
    assert inv.loc["INV-2026-02-HOOD", "issue_date"] == "2026-03-03"
    assert inv.loc["INV-2026-03-HOOD", "issue_date"] == "2026-04-02"


def test_famous_mockingbird_has_only_the_credit_invoice(built):
    assert [i for i in built["invoices"].index if "MOCK" in i] == ["INV-2026-01-MOCK"]


def test_true_up_line_on_february_invoice(built):
    # SPEC 5, check 1b: 2M January events at January's tier 3 rate = $40.00.
    lines = built["lines"]
    true_up = lines[lines.line_type == "true_up"]
    assert len(true_up) == 1
    row = true_up.iloc[0]
    assert (row.invoice_id, row.tier, row.units, row.amount) == ("INV-2026-02-HOOD", "3", 2_000_000, "40.00")
    assert row.description == "January usage, processed after the close cutoff"


def test_bug_fix_line_on_march_invoice(built):
    # SPEC 5: separate line on the March invoice, $50 at January's tier 3 rate.
    lines = built["lines"]
    reprocess = lines[lines.line_type == "reprocess"]
    assert len(reprocess) == 1
    row = reprocess.iloc[0]
    assert (row.invoice_id, row.units, row.amount) == ("INV-2026-03-HOOD", 2_500_000, "50.00")
    assert row.description == "January usage, reprocessed after a system fix"


def test_january_invoice_excludes_february_arrivals_and_duplicates(built):
    # SPEC 3.2: the customer-side delay and time-zone event are February usage; duplicates are never billed.
    lines = built["lines"]
    jan_events = lines[(lines.invoice_id == "INV-2026-01-HOOD") & (lines["product"] == "event_analytics")]
    feb_events = lines[(lines.invoice_id == "INV-2026-02-HOOD") & (lines["product"] == "event_analytics")
                       & (lines.line_type == "usage")]
    assert jan_events.units.astype(int).sum() == 30_000_000
    assert feb_events.units.astype(int).sum() == 30_000_000


def test_free_tier_lines_shown_at_zero(built):
    lines = built["lines"]
    free = lines[(lines.invoice_id == "INV-2026-01-TELA") & (lines.tier == "free")]
    assert len(free) == 3
    assert set(free.amount) == {"0.00"}


def test_billing_limit_line_on_tela_invoices(built):
    # SPEC 3.4: replay tier lines at list, then the cap as its own line.
    lines = built["lines"]
    caps = lines[lines.line_type == "billing_limit"].set_index("invoice_id").amount
    assert caps.to_dict() == {"INV-2026-01-TELA": "-525.00", "INV-2026-02-TELA": "-125.00"}


def test_invoice_lines_recompute_from_the_rate_card(built):
    # SPEC 7 pricing accuracy: every tiered line = units x unit price, rounded to cents.
    lines = built["lines"]
    tiered = lines[lines.line_type.isin(["usage", "true_up", "reprocess"])]
    for row in tiered.itertuples():
        expected = (D(row.units) * D(row.unit_price)).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        assert D(row.amount) == expected


def test_invoices_tie_to_step_3_pricing(built):
    rate_card = load_rate_card(built["data"] / "rate_cards.csv")
    replay = price("session_replay", 600_000, rate_card, D("1000.00"))
    lines = built["lines"]
    jan_replay = lines[(lines.invoice_id == "INV-2026-01-TELA") & (lines["product"] == "session_replay")]
    assert sum(D(a) for a in jan_replay.amount) == replay.billed_amount == D("1000.00")


# --- Payments ---------------------------------------------------------------------

def test_payments(built):
    paid = built["payments"].set_index("invoice_id")[["amount", "received_date"]]
    assert paid.to_dict("index") == {
        "INV-2025-12-TELA": {"amount": "3800.00", "received_date": "2026-01-14"},
        "INV-2026-01-MOCK": {"amount": "80000.00", "received_date": "2026-01-28"},  # SPEC 3.3
        "INV-2025-12-HOOD": {"amount": "3100.00", "received_date": "2026-01-29"},
        "INV-2026-01-TELA": {"amount": "4950.00", "received_date": "2026-02-17"},   # SPEC 5, check 3b
        "INV-2026-01-HOOD": {"amount": "3225.00", "received_date": "2026-03-02"},
        "INV-2026-02-HOOD": {"amount": "3265.00", "received_date": "2026-03-30"},
        "INV-2026-02-TELA": {"amount": "4700.00", "received_date": "2026-04-07"},   # SPEC 3.4: 20 days late
    }


def test_payments_file_written(built):
    assert (built["data"] / "payments.csv").read_text().startswith("payment_id,customer_id,invoice_id")


# --- Billing ledger ----------------------------------------------------------------

def test_ledger_ids_unique_and_sequential(built):
    ids = built["ledger"].ledger_id.tolist()
    assert ids == [f"BL-{i:05d}" for i in range(1, len(ids) + 1)]


def test_every_invoice_memo_and_payment_has_one_ledger_event(built):
    ledger = built["ledger"]
    issued = ledger[ledger.event_type.isin(["invoice_issued", "credit_invoice_issued"])]
    assert sorted(issued.invoice_id) == sorted(built["invoices"].index)
    assert sorted(ledger[ledger.event_type == "payment_applied"].source_ref) == sorted(built["payments"].payment_id)
    assert ledger[ledger.event_type == "credit_memo"].source_ref.tolist() == ["ADJ-2026-02-001"]


def test_credit_drawdown_at_list(built):
    # SPEC 5, checks 2 and 2b: $39,725 drawn at list price, leaving $60,275 of credit.
    ledger = built["ledger"]
    drawn = ledger[ledger.event_type == "credit_drawdown"]
    by_month = drawn.groupby("usage_month").amount.apply(lambda s: sum(D(a) for a in s))
    assert by_month.to_dict() == {"2026-01": D("11525"), "2026-02": D("15025"), "2026-03": D("13175")}
    assert D("100000") - sum(by_month) == D("60275.00")


def test_cap_never_posts_to_revenue_or_contra_revenue(built):
    # SPEC 3.4: the billing-limit line is presentation only. The ledger's amount field (what posts)
    # carries the billed amount; the capped $525 and $125 appear nowhere as a posting.
    ledger = built["ledger"]
    tela_replay = ledger[(ledger.customer_id == "TELA") & (ledger["product"] == "session_replay")
                         & (ledger.event_type == "usage_rated")].set_index("usage_month")
    assert tela_replay.amount.to_dict() == {"2026-01": "1000.00", "2026-02": "1000.00", "2026-03": "925.00"}
    assert not ledger.event_type.str.contains("limit|cap").any()
    assert not ledger.amount.isin(["525.00", "125.00"]).any()
    assert not ledger.amount.str.startswith("-").any()
    # The only credit memo is the $1,500 concession.
    assert ledger[ledger.event_type == "credit_memo"].amount.tolist() == ["1500.00"]


def test_rated_usage_ties_to_invoices(built):
    # Unbilled usage rated for a month = the usage lines billed for it (after the cap).
    ledger, inv = built["ledger"], built["invoices"]
    for customer in ["HOOD", "TELA"]:
        for month in ["2026-01", "2026-02", "2026-03"]:
            rated = ledger[(ledger.customer_id == customer) & (ledger.usage_month == month)
                           & (ledger.event_type == "usage_rated")]
            invoice = f"INV-{month}-{customer}"
            late_on_invoice = ledger[(ledger.event_type == "late_usage_rated") & (ledger.invoice_id == invoice)]
            assert sum(D(a) for a in rated.amount) + sum(D(a) for a in late_on_invoice.amount) == inv.loc[invoice, "total"]


def test_ar_at_march_31(built):
    # SPEC 5, checks 5 and 5a.
    billed, unbilled = ar_balances(built["ledger"], "2026-03-31")
    assert {c: v for c, v in billed.items() if v} == {"TELA": D("4700.00")}  # 13 days past due (due Mar 18)
    assert unbilled == {"HOOD": D("3275.00"), "TELA": D("4125.00")}         # includes the $50 bug fix
    assert sum(unbilled.values()) == D("7400.00")


def test_ar_at_january_1_is_the_opening_balance(built):
    billed, unbilled = ar_balances(built["ledger"], "2026-01-01")
    assert unbilled == {"HOOD": D("3100.00"), "TELA": D("3800.00")}
    assert billed == {"MOCK": D("80000.00")}  # the credit invoice is issued January 1


def test_rerun_is_identical(built, tmp_path):
    lines, payments, ledger = run_billing(built["data"], tmp_path)
    for name in ["invoices.csv", "billing_ledger.csv"]:
        assert (tmp_path / name).read_bytes() == (built["output"] / name).read_bytes()

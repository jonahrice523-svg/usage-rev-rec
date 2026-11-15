"""Tests for the revenue engine (SPEC 3.1-3.5; expected results from SPEC 5)."""

from decimal import Decimal

import pytest

from revrec import generate_data
from revrec.billing import ar_balances, run_billing
from revrec.revenue import evaluate_unusual_items, revenue_by, run_revenue

D = Decimal


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    output = tmp_path_factory.mktemp("output")
    generate_data.generate(data)
    _, _, billing_ledger = run_billing(data, output)
    ledger, schedule, exceptions = run_revenue(data, output, billing_ledger)
    return {"data": data, "output": output, "billing_ledger": billing_ledger,
            "ledger": ledger, "schedule": schedule, "exceptions": exceptions}


def amount(schedule, **filters):
    rows = schedule
    for column, value in filters.items():
        rows = rows[rows[column] == value]
    return sum((D(a) for a in rows.amount), D("0"))


# --- SPEC 5 expected results ------------------------------------------------------------

EXPECTED_BY_CUSTOMER_MONTH = {
    ("2026-01", "HOOD"): "3257.25", ("2026-02", "HOOD"): "3265.00", ("2026-03", "HOOD"): "3275.00",  # 1, 1a, 1c, 1d
    ("2026-01", "MOCK"): "9220.00", ("2026-02", "MOCK"): "12020.00", ("2026-03", "MOCK"): "10540.00",  # 2a
    ("2026-01", "TELA"): "6450.00", ("2026-02", "TELA"): "3200.00", ("2026-03", "TELA"): "4125.00",  # 3, 3a, 3c
}


def test_revenue_by_customer_and_month(built):
    actual = revenue_by(built["schedule"], "month", "customer_id")
    assert actual == {k: D(v) for k, v in EXPECTED_BY_CUSTOMER_MONTH.items()}


def test_monthly_and_q1_totals(built):
    # SPEC 5, checks 4 and 6.
    by_month = revenue_by(built["schedule"], "month")
    assert by_month == {"2026-01": D("18927.25"), "2026-02": D("18485.00"), "2026-03": D("17940.00")}
    assert sum(by_month.values()) == D("55352.25")


def test_harry_hood_january_usage_and_lag_estimate(built):
    s = built["schedule"]
    assert amount(s, month="2026-01", customer_id="HOOD", policy="usage") == D("3225.00")       # check 1
    assert amount(s, month="2026-01", customer_id="HOOD", policy="lag_estimate") == D("32.25")  # check 1a


def test_february_change_in_estimate(built):
    # SPEC 5, check 1b: $40.00 actual less the $32.25 January estimate = $7.75 in February.
    s = built["schedule"]
    actual = amount(s, month="2026-02", customer_id="HOOD", policy="lag_true_up")
    reversal = amount(s, month="2026-02", customer_id="HOOD", policy="lag_estimate_reversal")
    assert actual == D("40.00")
    assert actual + reversal == D("7.75")


def test_march_reversal_with_no_february_lag(built):
    # SPEC 5, check 1d: no February lag batch arrives, so the $32.25 estimate reverses to nothing.
    s = built["schedule"]
    assert amount(s, month="2026-03", customer_id="HOOD", policy="lag_true_up") == D("0")
    assert amount(s, month="2026-03", customer_id="HOOD", policy="lag_estimate_reversal") == D("-32.25")


def test_lag_estimate_only_for_harry_hood(built):
    s = built["schedule"]
    lag = s[s.policy.str.startswith("lag")]
    assert set(lag.customer_id) == {"HOOD"}  # SPEC 3.2


def test_bug_fix_recorded_in_march_below_threshold(built):
    # SPEC 5, check 4: $50 against a $89.70 threshold (0.5% of $17,940).
    s = built["schedule"]
    item = s[s.policy == "unusual_item"]
    assert item.month.tolist() == ["2026-03"]
    assert D(item.amount.iloc[0]) == D("50.00")
    assert "$89.70" in item.note.iloc[0]
    assert built["exceptions"] == []


def test_unusual_items_above_threshold_are_exceptions():
    # SPEC 3.2: above the threshold, items aren't recorded automatically.
    recorded, threshold = evaluate_unusual_items([D("100.00")], D("17990.00"), D("0.005"))
    assert (recorded, threshold) == (False, D("89.95"))
    recorded, _ = evaluate_unusual_items([D("50.00")], D("17940.00"), D("0.005"))
    assert recorded


def test_famous_mockingbird_revenue_at_080(built):
    # SPEC 5, check 2a: $39,725 consumed x 0.80 = $31,780.
    s = built["schedule"]
    assert amount(s, customer_id="MOCK", policy="credit_drawdown") == D("31780.00")
    assert amount(s, customer_id="MOCK", policy="breakage") == D("0")  # SPEC 3.3: constrained to zero
    assert len(s[(s.customer_id == "MOCK") & (s.policy == "breakage")]) == 3  # reassessed each month


def test_contract_liability_equals_remaining_credit_x_080(built):
    # SPEC 3.3, 7; SPEC 5, check 2b at March 31.
    ledger = built["ledger"]
    for month_end, expected in [("2026-01-31", "70780.00"), ("2026-02-28", "58760.00"), ("2026-03-31", "48220.00")]:
        to_date = ledger[(ledger.customer_id == "MOCK") & (ledger.event_date <= month_end)]
        invoiced = sum(D(a) for a in to_date[to_date.event_type == "credit_invoice_issued"].amount)
        recognized = sum(D(a) for a in to_date[to_date.event_type == "credit_revenue_recognized"].amount)
        consumed = sum(D(a) for a in to_date[to_date.event_type == "credit_drawdown"].amount)
        liability = invoiced - recognized
        assert liability == D(expected)
        assert liability == (D("100000") - consumed) * D("0.80")


def test_tela_concession_in_february_on_event_analytics(built):
    # SPEC 3.4: contra-revenue in February, tagged to event analytics; January untouched.
    s = built["schedule"]
    concession = s[s.policy == "concession"]
    assert concession[["month", "customer_id", "product", "amount"]].values.tolist() == [
        ["2026-02", "TELA", "event_analytics", "-1500.00"]]
    assert amount(s, month="2026-01", customer_id="TELA") == D("6450.00")


def test_capped_amounts_are_never_revenue(built):
    # SPEC 3.4: Tela replay revenue is the billed $1,000, not the $1,525 or $1,125 at list.
    s = built["schedule"]
    replay = s[(s.customer_id == "TELA") & (s["product"] == "session_replay")].set_index("month").amount
    assert replay.to_dict() == {"2026-01": "1000.00", "2026-02": "1000.00", "2026-03": "925.00"}


def test_december_usage_is_never_revenue(built):
    # SPEC 5: December usage was billed from the opening unbilled AR.
    s = built["schedule"]
    assert set(s.month) == {"2026-01", "2026-02", "2026-03"}
    assert not s.ledger_ids.str.contains("|".join(
        built["ledger"][built["ledger"].usage_month == "2025-12"].ledger_id)).any()


def test_unbilled_ar_at_march_31_includes_the_lag_estimate(built):
    # SPEC 5, check 5b: $7,400 from usage + $32.25 March lag estimate.
    billed, unbilled = ar_balances(built["ledger"], "2026-03-31")
    assert unbilled == {"HOOD": D("3307.25"), "TELA": D("4125.00")}
    assert sum(unbilled.values()) == D("7432.25")
    assert sum(billed.values()) == D("4700.00")


def test_schedule_ties_to_ledger_revenue_events_by_month(built):
    # Every dollar in the schedule comes from a ledger revenue or contra-revenue event.
    revenue_events = {"usage_rated": 1, "late_usage_rated": 1, "lag_estimate": 1,
                      "lag_estimate_reversal": -1, "credit_revenue_recognized": 1}
    contra_revenue_events = {"credit_memo": -1}  # price concessions (SPEC 3.4)
    signs = {**revenue_events, **contra_revenue_events}
    ledger = built["ledger"]
    from_ledger = {}
    for row in ledger[ledger.event_type.isin(signs)].itertuples():
        month = row.event_date[:7]
        from_ledger[month] = from_ledger.get(month, D("0")) + signs[row.event_type] * D(row.amount)
    from_schedule = revenue_by(built["schedule"], "month")
    for month in ["2026-01", "2026-02", "2026-03"]:
        assert from_schedule[month] == from_ledger[month], month


def test_revenue_engine_events_are_marked(built):
    ledger = built["ledger"]
    engine = ledger[ledger.origin == "revenue_engine"]
    assert set(engine.event_type) == {"lag_estimate", "lag_estimate_reversal", "credit_revenue_recognized"}
    assert set(ledger[ledger.origin == "billing"].event_type).isdisjoint(set(engine.event_type))
    # The revenue engine adds events; it never changes the billing rows.
    billing_rows = ledger[ledger.origin == "billing"].drop(columns="ledger_id").reset_index(drop=True)
    original = built["billing_ledger"].drop(columns="ledger_id").reset_index(drop=True)
    assert billing_rows.equals(original)


def test_rerun_is_identical(built, tmp_path):
    run_revenue(built["data"], tmp_path, built["billing_ledger"])
    for name in ["billing_ledger.csv", "revenue_schedule.csv"]:
        assert (tmp_path / name).read_bytes() == (built["output"] / name).read_bytes()

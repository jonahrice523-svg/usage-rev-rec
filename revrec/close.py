"""Close outputs (SPEC 3.2, 6 items 7-8, 7; build step 8).

- output/exceptions.csv: everything that couldn't be priced, mapped, or explained
- output/lag_report.csv: lag estimate vs actual late usage, by customer and month
- output/passed_adjustments_log.csv: unusual items recorded under the close threshold
- output/close_checklist.md: each close step with preparer, reviewer, due day, an
  automated check, result, and status, for each month
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from revrec.billing import MONTH_NAMES, month_after, month_end
from revrec.collections import build_aging, build_collections_log, open_amount
from revrec.dates import business_day, next_month
from revrec.gl import revenue_from_gl
from revrec.revenue import revenue_by

ZERO = Decimal("0.00")
MONTHS = ["2026-01", "2026-02", "2026-03"]
PERIOD_END = "2026-03-31"

# Roles. The Controller reviews every step, so preparer and reviewer always differ.
BILLING = "Billing engineering"
REVENUE = "Finance Manager, Revenue Accounting"
GL = "GL accountant"
AR = "AR specialist"
CONTROLLER = "Controller"
CFO = "CFO"


# --- Exceptions -----------------------------------------------------------------------------------

def build_exceptions(usage_summary, mapped, unusual_exceptions):
    rows = []
    for row in usage_summary.duplicates.sort_values("event_id").itertuples():
        rows.append({"type": "duplicate_usage", "reference": row.event_id, "customer_id": row.customer_id,
                     "month": row.received_ts[:7], "units": row.quantity, "amount": "",
                     "status": "resolved", "resolution": "Excluded from pricing and billing by rule (SPEC 3.2)"})
    for e in mapped.exceptions:
        rows.append({"type": "unmapped_ledger_row", "reference": e["ledger_id"], "customer_id": "", "month": "",
                     "units": "", "amount": "", "status": "open", "resolution": e["reason"]})
    for e in unusual_exceptions:
        rows.append({"type": "unusual_item_above_threshold", "reference": e["ledger_ids"], "customer_id": "",
                     "month": e["month"], "units": "", "amount": f"{e['amount']:.2f}", "status": "open",
                     "resolution": f"Above the ${e['threshold']:,.2f} threshold: evaluate under ASC 250 (SPEC 3.2)"})
    frame = pd.DataFrame(rows, columns=["type", "reference", "customer_id", "month", "units", "amount",
                                        "status", "resolution"])
    frame.insert(0, "exception_id", [f"EXC-{i:03d}" for i in range(1, len(frame) + 1)])
    return frame


# --- Lag report -----------------------------------------------------------------------------------

def build_lag_report(ledger, assumptions, reprocessed_ids):
    rows = []
    for customer in assumptions.lag_customers:
        for month in MONTHS:
            processed = sum((Decimal(a) for a in ledger[(ledger.event_type == "usage_rated") & (ledger.customer_id == customer)
                                                        & (ledger.usage_month == month)].amount), ZERO)
            estimate = sum((Decimal(a) for a in ledger[(ledger.event_type == "lag_estimate") & (ledger.customer_id == customer)
                                                       & (ledger.usage_month == month)].amount), ZERO)
            following = month_after(month)
            known = following in MONTHS  # the actual is known when next month's close is in the period
            late = ledger[(ledger.event_type == "late_usage_rated") & (ledger.customer_id == customer)
                          & (ledger.usage_month == month) & ~ledger.source_ref.isin(reprocessed_ids)]
            actual = sum((Decimal(a) for a in late.amount), ZERO)
            rows.append({"customer_id": customer, "usage_month": month, "processed_usage_revenue": f"{processed:.2f}",
                         "lag_rate": str(assumptions.lag_rate), "estimate": f"{estimate:.2f}",
                         "actual_late_usage": f"{actual:.2f}" if known else "pending",
                         "late_units": str(int(late.quantity.astype(int).sum())) if known else "pending",
                         "change_in_estimate": f"{actual - estimate:.2f}" if known else "",
                         "recognized_in": following if known else f"{following} (after period end)"})
    return pd.DataFrame(rows)


# --- Passed adjustments log -------------------------------------------------------------------------

def build_passed_adjustments(schedule, ledger, threshold_pct):
    items = schedule[schedule.policy == "unusual_item"]
    month_totals = revenue_by(schedule, "month")
    rows, running = [], ZERO
    for row in items.sort_values("month").itertuples():
        amount = Decimal(row.amount)
        running += amount
        month_items = sum((Decimal(a) for a in items[items.month == row.month].amount), ZERO)
        threshold = (threshold_pct * month_totals[row.month]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append({"month": row.month, "customer_id": row.customer_id, "product": row.product,
                     "ledger_ids": row.ledger_ids, "description": row.note.split(" (below")[0],
                     "amount": f"{amount:.2f}", "month_unusual_items_total": f"{month_items:.2f}",
                     "month_total_revenue": f"{month_totals[row.month]:.2f}",
                     "threshold_pct": str(threshold_pct), "threshold": f"{threshold:.2f}",
                     "below_threshold": "yes" if abs(month_items) < threshold else "no",
                     "running_total": f"{running:.2f}"})
    return pd.DataFrame(rows, columns=["month", "customer_id", "product", "ledger_ids", "description", "amount",
                                       "month_unusual_items_total", "month_total_revenue", "threshold_pct",
                                       "threshold", "below_threshold", "running_total"])


# --- Close checklist --------------------------------------------------------------------------------

@dataclass
class Step:
    due: str
    name: str
    preparer: str
    reviewer: str
    check: str


STEPS = [
    Step("BD1", "Usage loaded and complete", BILLING, CONTROLLER, "Unit completeness: zero units unexplained"),
    Step("BD1", "Duplicates removed", BILLING, CONTROLLER, "Every duplicate logged in exceptions and never billed"),
    Step("BD2", "Invoices issued", BILLING, CONTROLLER, "Issued on business day 2; every line recomputes from the rate card"),
    Step("BD3", "Cutoff and lag estimate", REVENUE, CONTROLLER, "Lag estimate = lag rate x processed usage revenue; in the lag report"),
    Step("BD3", "Unusual items reviewed", REVENUE, CONTROLLER, "Aggregate below the close threshold, and every item logged"),
    Step("BD3", "Revenue schedule ties to the GL", REVENUE, CONTROLLER, "Revenue by product equals GL revenue by product"),
    Step("BD4", "Integration controls", GL, CONTROLLER, "All integration controls pass (SPEC 4, 7)"),
    Step("BD4", "Rollforwards tie to the GL", GL, CONTROLLER, "Every rollforward difference is zero"),
    Step("BD4", "AR aging and collections", AR, CONTROLLER, "Aging ties to GL 1100; every invoice 5+ days past due has a reminder"),
    Step("BD5", "Reconciliation", REVENUE, CONTROLLER, "Bridges A-D: zero unexplained difference"),
    Step("BD5", "Exceptions cleared", REVENUE, CONTROLLER, "No open exceptions"),
    Step("BD5", "Close sign-off", CONTROLLER, CFO, "Manual: no automated check"),
]


def checklist_results(month, *, bridges, exceptions, lines, usage_monthly, ledger, assumptions, passed_log, schedule,
                      gl, chart, integration_controls, rollforwards, invoices_frame, reminder_days, followup_days):
    """Return {step name: (passed or None for manual, detail)} for one month."""
    results = {}
    by_key = {b.key: b for b in bridges}

    results["Usage loaded and complete"] = (by_key["A"].unexplained == 0, f"{by_key['A'].actual:,.0f} units received")

    # Duplicates are logged and resolved, and units billed for the month equal the deduplicated units.
    dup = exceptions[(exceptions.type == "duplicate_usage") & (exceptions.month == month)]
    usage_lines = lines[(lines.usage_month == month) & (lines.line_type == "usage")]
    billed_units = int(usage_lines.units.astype(int).sum())
    payg = set(usage_lines.customer_id)
    deduplicated = usage_monthly[(usage_monthly.month == month) & usage_monthly.customer_id.isin(payg)]
    results["Duplicates removed"] = (bool((dup.status == "resolved").all()) and billed_units == int(deduplicated.quantity.sum()),
                                     f"{len(dup)} duplicate(s) logged and resolved; {billed_units:,} units billed")

    month_invoices = invoices_frame[(invoices_frame.usage_month == month)
                                    & invoices_frame.line_types.map(lambda t: "credit_purchase" not in t)]
    bd2 = business_day(*next_month(int(month[:4]), int(month[5:7])), 2).isoformat()
    on_time = (month_invoices.issue_date == bd2).all()
    tiered = lines[(lines.usage_month == month) & lines.line_type.isin(["usage", "true_up", "reprocess"])]
    recompute = all(Decimal(r.amount) == (Decimal(r.units) * Decimal(r.unit_price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    for r in tiered.itertuples())
    results["Invoices issued"] = (bool(on_time) and recompute, f"{len(month_invoices)} invoices issued {bd2}")

    ok = True
    for customer in assumptions.lag_customers:
        processed = sum((Decimal(a) for a in ledger[(ledger.event_type == "usage_rated") & (ledger.customer_id == customer)
                                                    & (ledger.usage_month == month)].amount), ZERO)
        estimate = sum((Decimal(a) for a in ledger[(ledger.event_type == "lag_estimate") & (ledger.customer_id == customer)
                                                   & (ledger.usage_month == month)].amount), ZERO)
        ok &= estimate == (assumptions.lag_rate * processed).quantize(Decimal("0.01"), ROUND_HALF_UP)
    results["Cutoff and lag estimate"] = (ok, f"estimate {estimate:,.2f} on {processed:,.2f}")

    items = schedule[(schedule.month == month) & (schedule.policy == "unusual_item")]
    logged = passed_log[passed_log.month == month]
    below = (logged.below_threshold == "yes").all()
    results["Unusual items reviewed"] = (len(items) == len(logged) and bool(below),
                                         f"{len(items)} item(s)" + (f", threshold {logged.threshold.iloc[0]}" if len(logged) else ""))

    from_gl = {k: v for k, v in revenue_from_gl(gl, chart, "product", "month").items() if k[1] == month and v}
    from_schedule = {k: v for k, v in revenue_by(schedule, "product", "month").items() if k[1] == month and v}
    results["Revenue schedule ties to the GL"] = (from_gl == from_schedule, f"{sum(from_gl.values()):,.2f} revenue")

    failed = [name for name, passed, _ in integration_controls if not passed]
    results["Integration controls"] = (not failed, f"{len(integration_controls) - len(failed)} of {len(integration_controls)} pass")

    diffs = rollforwards[(rollforwards.month == month) & (rollforwards.line == "difference")]
    results["Rollforwards tie to the GL"] = ((diffs.amount == "0.00").all(), f"{len(diffs)} checks")

    as_of = month_end(month)
    aging = build_aging(ledger, invoices_frame, gl, as_of)
    aging_ok = (aging[aging.line == "difference"].amount == "0.00").all()
    log = build_collections_log(ledger, invoices_frame, reminder_days, followup_days, as_of)
    needs_reminder = [inv.invoice_id for inv in invoices_frame.itertuples()
                      if inv.issue_date <= str(as_of) and (as_of - date.fromisoformat(inv.due_date)).days >= reminder_days
                      and open_amount(ledger, inv.invoice_id, as_of) > 0]
    reminded = set(log[(log.action == "reminder") & (log.status == "sent")].invoice_id)
    results["AR aging and collections"] = (bool(aging_ok) and set(needs_reminder) <= reminded,
                                           f"{len(needs_reminder)} invoice(s) needing a reminder")

    unexplained = [b.key for b in bridges if b.unexplained != 0]
    results["Reconciliation"] = (not unexplained, "bridges A-D" + (f"; unexplained in {unexplained}" if unexplained else ""))

    open_items = exceptions[(exceptions.status == "open") & exceptions.month.isin([month, ""])]
    results["Exceptions cleared"] = (open_items.empty, f"{len(open_items)} open")

    results["Close sign-off"] = (None, "Awaiting Controller sign-off; reviewed by the CFO")
    # pandas returns its own true/false type; turn every result into a plain True, False, or None.
    return {name: (None if passed is None else bool(passed), detail) for name, (passed, detail) in results.items()}


def status(passed):
    return {True: "Complete", False: "Outstanding", None: "Pending manual sign-off"}[passed]


def write_checklist(results_by_month, path):
    out = ["# Revenue close checklist", "",
           "Hedgehog Metrics, Inc. (synthetic data). Q1 2026. Generated by `python run.py`.", ""]
    for month, results in results_by_month.items():
        complete = sum(1 for passed, _ in results.values() if passed is True)
        outstanding = len(results) - complete
        out.append(f"- **{MONTH_NAMES[month]} close: {complete} of {len(results)} steps complete, "
                   f"{outstanding} outstanding.**" + (" Outstanding: " + ", ".join(
                       n for n, (p, _) in results.items() if p is not True) + "." if outstanding else ""))
    out += ["", "Automated checks run each time the model runs. The Controller reviews every step; "
                "the CFO reviews the Controller's sign-off, so preparer and reviewer always differ.", ""]
    for month, results in results_by_month.items():
        out += [f"## {MONTH_NAMES[month]} 2026 close", "",
                "| Due | Step | Preparer | Reviewer | Automated check | Result | Status |",
                "|---|---|---|---|---|---|---|"]
        for step in STEPS:
            passed, detail = results[step.name]
            result = {True: "PASS", False: "FAIL", None: "Manual"}[passed]
            out.append(f"| {step.due} | {step.name} | {step.preparer} | {step.reviewer} | {step.check} | "
                       f"{result} ({detail}) | {status(passed)} |")
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8", newline="\n")


def run_close(output_dir, *, inputs, assumptions, mapped, unusual_exceptions, ledger, lines, invoices_frame, schedule,
              gl, chart, integration_controls, rollforwards, reconciliation, reminder_days, followup_days):
    output_dir = Path(output_dir)
    exceptions = build_exceptions(inputs.usage, mapped, unusual_exceptions)
    reprocessed_ids = set(inputs.usage.reprocessed.event_id)
    lag_report = build_lag_report(ledger, assumptions, reprocessed_ids)
    passed_log = build_passed_adjustments(schedule, ledger, assumptions.close_threshold_pct)
    results = {m: checklist_results(m, bridges=reconciliation[m], exceptions=exceptions, lines=lines,
                                    usage_monthly=inputs.usage.monthly, ledger=ledger, assumptions=assumptions,
                                    passed_log=passed_log, schedule=schedule, gl=gl, chart=chart,
                                    integration_controls=integration_controls, rollforwards=rollforwards,
                                    invoices_frame=invoices_frame, reminder_days=reminder_days,
                                    followup_days=followup_days)
               for m in MONTHS}
    exceptions.to_csv(output_dir / "exceptions.csv", index=False, lineterminator="\n")
    lag_report.to_csv(output_dir / "lag_report.csv", index=False, lineterminator="\n")
    passed_log.to_csv(output_dir / "passed_adjustments_log.csv", index=False, lineterminator="\n")
    write_checklist(results, output_dir / "close_checklist.md")
    return {"exceptions": exceptions, "lag_report": lag_report, "passed_log": passed_log, "checklist": results}

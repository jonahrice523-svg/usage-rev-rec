"""Account mapping, GL export, and integration controls (SPEC 4, 7; build step 6).

The GL comes only from the billing ledger, through config/account_mapping.csv:
- each ledger row's `amount` posts to one debit and one credit account (never `list_amount`)
- memo-only rows (credit drawdown at list value) are mapped but don't post
- credit memos are mapped by classification; anything unmapped becomes an exception
- rows dated after the period end stay in the ledger and are reported, not exported

output/gl_export.csv has one journal entry per day (JE-YYYY-MM-DD), with lines summed by
account and customer, and by product on revenue and contra-revenue accounts (to support
the ASC 606 disaggregation of revenue). Each line lists the ledger_ids behind it.
"""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

ZERO = Decimal("0.00")
PERIOD_START, PERIOD_END = "2026-01-01", "2026-03-31"
GL_COLUMNS = ["je_id", "entry_date", "account", "account_name", "customer_id", "product",
              "debit", "credit", "ledger_ids"]


def read_text_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


@dataclass
class Mapped:
    postings: list      # one dict per debit or credit line, before summarizing
    memo: list          # ledger_ids mapped as memo-only (no posting)
    exceptions: list    # dicts: ledger_id, event_type, reason
    after_period: list  # ledger_ids dated after the period end


def map_ledger(ledger, mapping, chart, adjustments, period_end=PERIOD_END):
    """Apply the account mapping to every ledger row."""
    rules = {(r.event_type, r.classification): r for r in mapping.itertuples()}
    revenue_accounts = set(chart[chart.type.isin(["revenue", "contra_revenue"])].account)
    classification = adjustments.set_index("adjustment_id")["classification"].to_dict()
    result = Mapped([], [], [], [])

    for row in ledger.itertuples():
        if row.event_date > period_end:
            result.after_period.append(row.ledger_id)
            continue
        key = (row.event_type, classification.get(row.source_ref, "") if row.event_type == "credit_memo" else "")
        rule = rules.get(key)
        if rule is None:
            result.exceptions.append({"ledger_id": row.ledger_id, "event_type": row.event_type,
                                      "reason": f"No account mapping for {key[0]} {key[1]}".strip()})
            continue
        if rule.posts == "no":
            result.memo.append(row.ledger_id)
            continue
        amount = Decimal(row.amount)  # SPEC 4: post the ledger amount only, never list_amount
        for account, debit, credit in [(rule.debit_account, amount, ZERO), (rule.credit_account, ZERO, amount)]:
            result.postings.append({
                "entry_date": row.event_date, "account": account, "customer_id": row.customer_id,
                "product": row.product if account in revenue_accounts else "",
                "debit": debit, "credit": credit, "ledger_id": row.ledger_id})
    return result


def build_gl_export(postings, chart):
    names = chart.set_index("account")["name"].to_dict()
    lines = {}
    for p in postings:
        key = (p["entry_date"], p["account"], p["customer_id"], p["product"])
        line = lines.setdefault(key, {"debit": ZERO, "credit": ZERO, "ledger_ids": []})
        line["debit"] += p["debit"]
        line["credit"] += p["credit"]
        line["ledger_ids"].append(p["ledger_id"])
    rows = [{"je_id": f"JE-{d}", "entry_date": d, "account": a, "account_name": names[a], "customer_id": c,
             "product": prod, "debit": f"{v['debit']:.2f}", "credit": f"{v['credit']:.2f}",
             "ledger_ids": ";".join(sorted(set(v["ledger_ids"])))}
            for (d, a, c, prod), v in sorted(lines.items())]
    return pd.DataFrame(rows, columns=GL_COLUMNS)


def account_balances(gl, as_of=PERIOD_END):
    """Net balance (debit - credit) by account at the end of a day."""
    balances = {}
    for row in gl[gl.entry_date <= as_of].itertuples():
        balances[row.account] = balances.get(row.account, ZERO) + Decimal(row.debit) - Decimal(row.credit)
    return balances


def revenue_from_gl(gl, chart, *keys):
    """Revenue (credit - debit) on revenue and contra-revenue accounts, summed by the given GL columns."""
    accounts = set(chart[chart.type.isin(["revenue", "contra_revenue"])].account)
    out = {}
    for row in gl[gl.account.isin(accounts)].itertuples():
        key = tuple(row.entry_date[:7] if k == "month" else getattr(row, k) for k in keys)
        key = key[0] if len(key) == 1 else key
        out[key] = out.get(key, ZERO) + Decimal(row.credit) - Decimal(row.debit)
    return out


# --- Integration controls (SPEC 4, 7) -----------------------------------------------------

def run_controls(ledger, mapped, gl, mapping, adjustments):
    """Return a list of (control, passed, detail)."""
    results = []

    in_period = ledger[ledger.event_date <= PERIOD_END]
    posted_ids = {p["ledger_id"] for p in mapped.postings}
    accounted = len(posted_ids) + len(mapped.memo) + len(mapped.exceptions)
    results.append(("Every ledger row is mapped or in exceptions",
                    accounted == len(in_period) and not mapped.exceptions,
                    f"{len(in_period)} rows: {len(posted_ids)} posted, {len(mapped.memo)} memo-only, "
                    f"{len(mapped.exceptions)} exceptions; {len(mapped.after_period)} after period end"))

    # Recompute each account's total straight from the ledger rows and the mapping.
    rules = mapping.set_index(["event_type", "classification"])
    classification = adjustments.set_index("adjustment_id")["classification"].to_dict()
    expected = {}
    for row in in_period.itertuples():
        key = (row.event_type, classification.get(row.source_ref, "") if row.event_type == "credit_memo" else "")
        if key not in rules.index or rules.loc[key, "posts"] == "no":
            continue
        amount = Decimal(row.amount)
        expected[rules.loc[key, "debit_account"]] = expected.get(rules.loc[key, "debit_account"], ZERO) + amount
        expected[rules.loc[key, "credit_account"]] = expected.get(rules.loc[key, "credit_account"], ZERO) - amount
    actual = account_balances(gl)
    results.append(("GL account totals tie to the billing ledger",
                    {a: v for a, v in expected.items() if v} == {a: v for a, v in actual.items() if v},
                    f"{len(actual)} accounts compared"))

    unbalanced = [je for je, lines in gl.groupby("je_id")
                  if sum(Decimal(d) for d in lines.debit) != sum(Decimal(c) for c in lines.credit)]
    results.append(("Every journal entry balances", not unbalanced,
                    f"{gl.je_id.nunique()} journal entries; unbalanced: {unbalanced or 'none'}"))

    tb_total = sum(actual.values(), ZERO)
    results.append(("Trial balance is in balance", tb_total == 0, f"net of all accounts: {tb_total:.2f}"))
    return results


def run_gl(config_dir, data_dir, output_dir, ledger):
    chart = read_text_csv(Path(config_dir) / "chart_of_accounts.csv")
    mapping = read_text_csv(Path(config_dir) / "account_mapping.csv")
    adjustments = read_text_csv(Path(data_dir) / "adjustments.csv")
    mapped = map_ledger(ledger, mapping, chart, adjustments)
    gl = build_gl_export(mapped.postings, chart)
    gl.to_csv(Path(output_dir) / "gl_export.csv", index=False, lineterminator="\n")

    # SPEC 4: re-running the export produces identical output.
    rerun = build_gl_export(map_ledger(ledger, mapping, chart, adjustments).postings, chart)
    controls = run_controls(ledger, mapped, gl, mapping, adjustments)
    controls.append(("Re-running the GL export gives identical output", rerun.equals(gl), "compared row by row"))
    return gl, mapped, controls, chart

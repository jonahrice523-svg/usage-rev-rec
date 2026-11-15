"""The one-page case study (SPEC 6, item 11; build step 12): docs/index.html.

Every figure on the page comes from the model's results (the dict `close_quarter()` returns),
never typed by hand. The intro, the customer cards and "How I built this" come from README.md,
and the judgment call cards pull their text from MEMO.md on every run. The page is written for a
reviewer who won't read code or CSVs.

How it's built: `page_facts()` collects every number the page shows; `render()` turns those facts
into HTML. tests/test_site.py checks each fact against the model and every dollar figure on the
page against the facts.
"""

import html
import json
import re
from decimal import Decimal
from pathlib import Path

from revrec.revenue import revenue_by
from revrec.rollforwards import MONTHS, closing
from revrec.workpapers import gl_lines_for

D = Decimal
REPO = "https://github.com/jonahrice523-svg/usage-rev-rec"
CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"  # pinned exact version
MONTH_NAMES = {"2026-01": "January", "2026-02": "February", "2026-03": "March"}
CUSTOMERS = {"HOOD": "Harry Hood", "MOCK": "Famous Mockingbird", "TELA": "Tela"}

# The one-sentence positions on the judgment call cards, approved by Jonah word for word.
# The text behind each card comes from the matching MEMO.md section.
POSITIONS = [
    "One standard approach for every contract: usage allocated to its month, prepaid credit recognized as "
    "consumed. The expedient gives the same answer for pay-as-you-go but can’t handle prepaid.",
    "Held at zero until HM has years of expiry history by segment; at Famous Mockingbird’s pace, its credit "
    "runs out in August anyway.",
    "Usage belongs to the month HM receives it, because receiving and processing the data is the service; "
    "the customer terms must use the same clock.",
    "Estimate the routine processing lag every month; send unusual items over the threshold to a person, "
    "checked against both the month they belong to and the month they’re booked.",
    "One concession is an event; a pattern is an estimate, and repeated causes are also a product question.",
    "The real audit risk is the usage data, not the journal entries. Billing engineering owns the pipeline, "
    "finance owns the mapping and reconciliations, and preventive controls come next.",
    "Neither wins automatically: fix the difference where it started and re-sync; never plug the GL.",
]

# Where a card's policy goes further than the model, say what the model actually does.
MODEL_NOTES = {
    4: "In the model: unusual items are tested against the current month's revenue only. "
       "Checking both months is the policy I'd adopt.",
}


def money(amount, sign=False):
    """$1,234.56, with a minus sign for negatives (or a plus sign if asked)."""
    amount = D(amount)
    prefix = "−" if amount < 0 else ("+" if sign and amount > 0 else "")
    return f"{prefix}${abs(amount):,.2f}"


def esc(text):
    return html.escape(str(text), quote=True)


# --- Facts: every number on the page, taken from the model ----------------------------------------

def tela_january(r):
    """Follow one dollar: Tela's January invoice from usage at list to cash (SPEC 3.4)."""
    lines = r["lines"][r["lines"].invoice_id == "INV-2026-01-TELA"]
    usage = lines[lines.line_type == "usage"]
    ledger = r["ledger"][r["ledger"].customer_id == "TELA"]
    rated = ledger[(ledger.event_type == "usage_rated") & (ledger.usage_month == "2026-01")]
    on_invoice = ledger[ledger.invoice_id == "INV-2026-01-TELA"]

    def event(event_type):
        return on_invoice[on_invoice.event_type == event_type].iloc[0]

    def entry(ledger_ids):
        gl = gl_lines_for(r["gl"], set(ledger_ids))
        gl = gl[gl.customer_id == "TELA"]
        lines = [{"account": row.account, "name": row.account_name, "product": row.product,
                  "debit": D(row.debit), "credit": D(row.credit)} for row in gl.itertuples()]
        lines.sort(key=lambda line: (line["credit"] > 0, line["account"], line["product"]))  # debits first
        return {"je_id": gl.je_id.iloc[0], "date": gl.entry_date.iloc[0], "lines": lines}

    invoice, credit_memo, payment = event("invoice_issued"), event("credit_memo"), event("payment_applied")
    return {
        "list": sum((D(a) for a in usage.amount), D("0")),
        "billing_limit": D(lines[lines.line_type == "billing_limit"].amount.iloc[0]),
        "recognized": sum((D(a) for a in rated.amount), D("0")),
        "invoiced": D(invoice.amount),
        "concession": -D(credit_memo.amount),
        "cash": D(payment.amount),
        "entries": {
            "recognized": entry(rated.ledger_id),
            "invoiced": entry([invoice.ledger_id]),
            "concession": entry([credit_memo.ledger_id]),
            "cash": entry([payment.ledger_id]),
        },
    }


def tela_replay_tiers(r):
    """Free tier -> graduated tiers -> billing limit, using Tela's January session replay (SPEC 3.4, 3.5)."""
    # ["product"], not .product: .product is a pandas method name
    lines = r["lines"][(r["lines"].invoice_id == "INV-2026-01-TELA") & (r["lines"]["product"] == "session_replay")]
    tiers = [{"tier": row.tier, "units": int(row.units), "unit_price": D(row.unit_price), "amount": D(row.amount)}
             for row in lines[lines.line_type == "usage"].itertuples()]
    limit = D(lines[lines.line_type == "billing_limit"].amount.iloc[0])
    at_list = sum((t["amount"] for t in tiers), D("0"))
    return {"tiers": tiers, "units": sum(t["units"] for t in tiers), "list": at_list,
            "billing_limit": limit, "billed": at_list + limit}


def page_facts(r):
    by = revenue_by(r["schedule"], "month", "customer_id")
    by_month = revenue_by(r["schedule"], "month")
    rf = r["rollforwards"]
    bridges = [b for month in MONTHS for b in r["reconciliation"][month]]
    controls = r["workpapers"]["control_results"]
    january_c = next(b for b in r["reconciliation"]["2026-01"] if b.key == "C")
    credit = r["inputs"].contracts.set_index("customer_id").loc["MOCK"]
    return {
        # SPEC 3.3: the customer pays $0.80 for each $1.00 of credit
        "credit_terms": {"credit_value": D(credit.credit_value), "cash_price": D(credit.cash_price),
                         "per_dollar": D(credit.cash_price) / D(credit.credit_value), "dollar": D("1.00")},
        "q1_revenue": sum(by_month.values()),
        "revenue_by_month": {m: by_month[m] for m in MONTHS},
        "revenue_by_customer": {c: {m: by.get((m, c), D("0")) for m in MONTHS} for c in CUSTOMERS},
        "bridge_count": len(bridges),
        "largest_unexplained": max(abs(b.unexplained) for b in bridges),
        "controls": {m: dict(controls[m]) for m in MONTHS},
        "tiers": tela_replay_tiers(r),
        "tela": tela_january(r),
        "mock": {m: {"credit": closing(rf, "credit_balance_at_list", "MOCK", m),
                     "liability": closing(rf, "contract_liability", "MOCK", m)} for m in MONTHS},
        "bridge_c_january": {"lines": [(label, D(amount)) for label, amount in january_c.lines],
                             "total": january_c.computed, "schedule": january_c.actual,
                             "unexplained": january_c.unexplained},
        "checklist": {m: {"complete": sum(1 for passed, _ in r["close"]["checklist"][m].values() if passed is True),
                          "total": len(r["close"]["checklist"][m]),
                          "outstanding": [n for n, (p, _) in r["close"]["checklist"][m].items() if p is not True]}
                      for m in MONTHS},
    }


# --- Text from README.md and MEMO.md ---------------------------------------------------------------

def link_target(target):
    """Relative repo links point to GitHub, which formats Markdown; Pages only serves docs/."""
    return target if target.startswith("http") else f"{REPO}/blob/main/{target}"


def inline(text):
    """Markdown inline formatting (bold, italic, links) to HTML."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                 lambda m: f'<a href="{esc(link_target(m.group(2)))}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", out)


def blocks_to_html(blocks):
    out = []
    for block in blocks:
        rows = block.splitlines()
        if all(row.startswith("- ") for row in rows):
            out.append("<ul>" + "".join(f"<li>{inline(row[2:])}</li>" for row in rows) + "</ul>")
        else:
            out.append(f"<p>{inline(' '.join(rows))}</p>")
    return "\n".join(out)


def memo_sections(memo_text):
    """The seven judgment call sections of MEMO.md, as (title, blocks), every paragraph included."""
    sections = re.split(r"^### ", memo_text, flags=re.M)[1:]
    out = []
    for section in sections:
        heading, _, body = section.partition("\n")
        body = re.split(r"^## ", body, flags=re.M)[0]
        blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]
        out.append((re.sub(r"^\d+\.\s*", "", heading.strip()), blocks))
    return out


def readme_parts(readme_text):
    why = re.search(r"\*\*Why I built this:\*\*\s*(.+)", readme_text).group(1).strip()
    cap_line = why.split(". ", 1)[1]  # "Reading the guidance is one thing. Watching a $525 billing cap ..."
    how = readme_text.split("## How I built this", 1)[1].split("\n## ", 1)[0].strip()
    table = readme_text.split("## Three customers", 1)[1].split("\n## ", 1)[0]
    customers = []
    for row in table.splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in CUSTOMERS.values():
            customers.append(cells)
    return {"why": why, "cap_line": cap_line, "how": how, "customers": customers}


# --- HTML -----------------------------------------------------------------------------------------

def entry_table(entry):
    rows = "".join(
        f"<tr><td>{esc(line['account'])} {esc(line['name'])}"
        + (f" <span class=\"muted\">({esc(line['product'].replace('_', ' '))})</span>" if line["product"] else "")
        + f"</td><td class=\"num\">{money(line['debit']) if line['debit'] else ''}</td>"
        f"<td class=\"num\">{money(line['credit']) if line['credit'] else ''}</td></tr>"
        for line in entry["lines"])
    return (f'<div class="je"><div class="je-head"><span>{esc(entry["je_id"])}</span>'
            f'<span class="muted">{esc(entry["date"])}</span></div>'
            f'<table><thead><tr><th>Account</th><th class="num">Dr</th><th class="num">Cr</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>")


def no_entry(reason):
    return f'<div class="je je-none"><strong>No journal entry.</strong> {reason}</div>'


INTRO = ("A full quarter of usage-based revenue accounting for a fictional company, from raw usage to "
         "reconciled GL, built to show how I’d run revenue accounting at a usage-billed business. Built over "
         "one weekend, spec first, with Claude Code.")

ABOUT = ("Previously acting controller at a $16M ARR SaaS company, where I ran an accrued-revenue workflow for "
         "pay-as-you-go revenue, posted revenue from Chargebee into QuickBooks, and was the main contact for our "
         "auditors. Started at PwC in audit.")


def section_hero(f, sections):
    return f"""
<header class="hero">
  <p class="eyebrow">Hedgehog Metrics, Inc. · Q1 2026 · synthetic data</p>
  <h1>Usage-based revenue, closed and reconciled.</h1>
  <p class="lede">{esc(INTRO)}</p>
  <div class="tiles">
    <div class="tile"><div class="tile-value">{money(f["largest_unexplained"])}</div>
      <div class="tile-label">unexplained difference in every reconciliation
        ({f["bridge_count"]} bridges, 3 months)</div></div>
    <div class="tile"><div class="tile-value">{controls_passing(f)} of {len(f["controls"][MONTHS[0]])}</div>
      <div class="tile-label">controls pass, every month</div></div>
    <div class="tile"><div class="tile-value">{len(sections)}</div>
      <div class="tile-label">judgment calls documented</div></div>
  </div>
  <p class="tile-note">Every number on this page is checked by the test suite.</p>
</header>"""


def controls_passing(f):
    """Controls that pass in every month."""
    names = f["controls"][MONTHS[0]]
    return sum(1 for name in names if all(f["controls"][m][name] for m in MONTHS))


def section_business(f, text):
    t = f["tiers"]
    steps = []
    for tier in t["tiers"]:
        if tier["tier"] == "free":
            steps.append(f'<div class="step step-free"><div class="step-name">Free tier</div>'
                         f'<div class="step-math">{tier["units"]:,} recordings</div>'
                         f'<div class="step-amt">{money(tier["amount"])}</div></div>')
        else:
            steps.append(f'<div class="step"><div class="step-name">Tier {esc(tier["tier"])}</div>'
                         f'<div class="step-math">{tier["units"]:,} × ${tier["unit_price"]}</div>'
                         f'<div class="step-amt">{money(tier["amount"])}</div></div>')
    steps.append(f'<div class="step step-total"><div class="step-name">At list</div>'
                 f'<div class="step-math">cheaper per unit as volume grows</div>'
                 f'<div class="step-amt">{money(t["list"])}</div></div>')
    steps.append(f'<div class="step step-cap"><div class="step-name">Billing limit</div>'
                 f'<div class="step-math">set by the customer</div>'
                 f'<div class="step-amt">{money(t["billing_limit"])}</div></div>')
    steps.append(f'<div class="step step-total"><div class="step-name">Billed and recognized</div>'
                 f'<div class="step-math">the cap is part of the price</div>'
                 f'<div class="step-amt">{money(t["billed"])}</div></div>')
    cards = "".join(
        f'<div class="card customer"><h3>{esc(name)}</h3><p class="plan">{inline(plan)}</p>'
        f"<p>{inline(shows)}.</p></div>" for name, plan, shows in text["customers"])
    return f"""
<section id="business">
  <p class="eyebrow">#N · The business in 30 seconds</p>
  <h2>Pay for what you use, down to the last recording</h2>
  <p>Customers send Hedgehog Metrics product data and pay monthly for what they use. Each product has a
  free allowance, then graduated tiers, and customers can cap their own monthly spend. Here is Tela's
  January session replay, {t["units"]:,} recordings, from free tier to invoice:</p>
  <div class="flow" role="list">{"".join(steps)}</div>
  <p class="muted small">Each unit is priced at its own tier's rate, and tiers reset every month.
  Usage above the limit is never billed and never revenue, because it was never owed.</p>
  <p class="callout">{inline(text["cap_line"])}</p>
  <h3 class="sub">Three customers, three lessons</h3>
  <div class="cards three">{cards}</div>
</section>"""


def section_dollar(f):
    t = f["tela"]
    e = t["entries"]
    steps = [
        ("Usage at list", t["list"], "January usage priced at list, after the free tier.",
         no_entry("List price isn't the price Tela owes, so nothing posts yet.")),
        ("Billing limit", t["billing_limit"], "Tela's $1,000 monthly cap on session replay.",
         no_entry("Never owed, so never revenue: not a reversal, a credit memo, or bad debt.")),
        ("Recognized in January", t["recognized"],
         "January's usage is January's revenue, accrued as an unbilled receivable at month end.",
         entry_table(e["recognized"])),
        ("Invoiced", t["invoiced"], "The invoice goes out on business day 2 and moves the unbilled receivable "
         "to billed AR.", entry_table(e["invoiced"])),
        ("Price concession", t["concession"], "Tela disputed test-environment event volume. The credit memo is a "
         "price concession, so it reduces February revenue, the period the price changed.",
         entry_table(e["concession"])),
        ("Cash", t["cash"], "Tela pays the invoice less the credit memo, on time.", entry_table(e["cash"])),
    ]
    items = "".join(
        f'<li class="dollar-step"><div class="dollar-head"><span class="dollar-name">{name}</span>'
        f'<span class="dollar-amt">{money(amount)}</span></div><p>{why}</p>{je}</li>'
        for name, amount, why, je in steps)
    return f"""
<section id="dollar">
  <p class="eyebrow">#N · Follow one dollar</p>
  <h2>Tela's January, from usage to cash</h2>
  <p>Six steps, each with the journal entry the model posted from the billing ledger. Two of them
  rightly post nothing.</p>
  <ol class="dollar">{items}</ol>
  <p class="small"><a href="{REPO}/blob/main/output/workpapers/sample_tieouts.md">See this invoice traced
  row by row in the sample tie-outs →</a></p>
</section>"""


def money_table(headers, rows):
    def cls(i):
        return ' class="num"' if i else ""  # first column is a label, the rest are amounts
    head = "".join(f"<th{cls(i)}>{h}</th>" for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f"<td{cls(i)}>{c}</td>" for i, c in enumerate(row)) + "</tr>"
                   for row in rows)
    return f'<table class="data"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def section_charts(f):
    months = [MONTH_NAMES[m] for m in MONTHS]
    revenue_rows = [[CUSTOMERS[c]] + [money(f["revenue_by_customer"][c][m]) for m in MONTHS]
                    for c in CUSTOMERS]
    revenue_rows.append(["<strong>Total</strong>"] + [f"<strong>{money(f['revenue_by_month'][m])}</strong>"
                                                     for m in MONTHS])
    mock_rows = [[MONTH_NAMES[m], money(f["mock"][m]["credit"]), money(f["mock"][m]["liability"])]
                 for m in MONTHS]
    return f"""
<section id="charts">
  <p class="eyebrow">#N · Where the revenue came from</p>
  <h2>Three customers, three ways to recognize revenue</h2>
  <div class="cards two">
    <figure class="card chart-card">
      <figcaption><h3>Revenue by month</h3>
        <p class="muted small">Stacked by customer. February is net of Tela's concession.</p></figcaption>
      <div class="chart-box"><canvas id="revenueChart" role="img"
        aria-label="Stacked bar chart of revenue by month and customer"></canvas></div>
      <details><summary>Show the numbers</summary>{money_table([""] + months, revenue_rows)}</details>
    </figure>
    <figure class="card chart-card">
      <figcaption><h3>Famous Mockingbird: credit vs contract liability</h3>
        <p class="muted small">Month-end balances. The liability is always the remaining credit
        × {f["credit_terms"]["per_dollar"]:.2f}, because the customer paid {money(f["credit_terms"]["per_dollar"])}
        for each {money(f["credit_terms"]["dollar"])} of credit.</p></figcaption>
      <div class="chart-box"><canvas id="mockChart" role="img"
        aria-label="Bar chart of credit balance at list and contract liability by month"></canvas></div>
      <details><summary>Show the numbers</summary>
        {money_table(["", "Credit at list", "Contract liability"], mock_rows)}</details>
    </figure>
  </div>
</section>"""


def section_waterfall(f):
    c = f["bridge_c_january"]
    steps = [(label, amount) for label, amount in c["lines"] if amount]
    zero = [label for label, amount in c["lines"] if not amount]
    scale = max(abs(sum(a for _, a in steps[: i + 1])) for i in range(len(steps)))
    running, rows = D("0"), []
    for i, (label, amount) in enumerate(steps):
        start, end = (running, running + amount)
        low, high = min(start, end), max(start, end)
        kind = "total" if i == 0 else ("down" if amount < 0 else "up")
        left = float(low / scale * 100)
        width = max(float((high - low) / scale * 100), 0.4)
        rows.append(f'<div class="wf-row"><div class="wf-label">{esc(clean_label(label))}</div>'
                    f'<div class="wf-track"><div class="wf-bar wf-{kind}" style="left:{left:.3f}%;width:{width:.3f}%">'
                    f'</div></div><div class="wf-amt">{money(amount, sign=i > 0)}</div></div>')
        running = end
    rows.append(f'<div class="wf-row wf-result"><div class="wf-label">Revenue per the revenue schedule</div>'
                f'<div class="wf-track"><div class="wf-bar wf-total" style="left:0%;'
                f'width:{float(c["schedule"] / scale * 100):.3f}%"></div></div>'
                f'<div class="wf-amt">{money(c["schedule"])}</div></div>')
    return f"""
<section id="reconciliation">
  <p class="eyebrow">#N · Every dollar accounted for</p>
  <h2>January: from usage at list to revenue</h2>
  <p>Bridge C of the monthly reconciliation. Usage priced at list becomes recognized revenue only through
  named reconciling items, each tied to a policy in the spec.</p>
  <div class="card waterfall" role="img" aria-label="Waterfall from usage at list to recognized revenue">
    {"".join(rows)}
    <p class="muted small">Also in the bridge, at {money(0)} this month: {esc(", ".join(clean_label(z).lower() for z in zero))}.</p>
  </div>
  <p class="unexplained">Unexplained difference: <strong>{money(c["unexplained"])}</strong></p>
  <p class="small"><a href="{REPO}/blob/main/output/reconciliation.md">All four bridges, all three months,
  in reconciliation.md →</a></p>
</section>"""


def clean_label(label):
    """'Lag estimate at month end (SPEC 3.2)' -> 'Lag estimate at month end'."""
    return re.sub(r"\s*\(SPEC [^)]*\)", "", label)


def section_judgment(sections):
    cards = []
    for number, ((title, blocks), position) in enumerate(zip(sections, POSITIONS), start=1):
        more = (f"<details><summary>Read the reasoning</summary>{blocks_to_html(blocks)}</details>" if blocks
                else '<p class="muted small">Full reasoning in MEMO.md (in progress).</p>')
        note = f'<p class="model-note">{esc(MODEL_NOTES[number])}</p>' if number in MODEL_NOTES else ""
        cards.append(f'<article class="card judgment"><p class="num-badge">{number}</p><h3>{esc(title)}</h3>'
                     f'<p class="position">{esc(position)}</p>{note}{more}</article>')
    return f"""
<section id="judgment">
  <p class="eyebrow">#N · Seven judgment calls</p>
  <h2>The parts a spreadsheet can't decide</h2>
  <p>Where I landed on each open question, from my policy memo. Some positions go further than the
  model does; where they do, the card says so.</p>
  <div class="cards two">{"".join(cards)}</div>
  <p class="small"><a href="{REPO}/blob/main/MEMO.md">Read the full memo, MEMO.md →</a></p>
</section>"""


def section_close(f):
    months = "".join(
        f'<div class="card month"><h3>{MONTH_NAMES[m]} close</h3>'
        f'<p class="big">{f["checklist"][m]["complete"]} of {f["checklist"][m]["total"]}</p>'
        f'<p class="small">steps complete. Outstanding: {esc(", ".join(f["checklist"][m]["outstanding"]))} '
        f"(manual: the Controller signs, the CFO reviews).</p></div>" for m in MONTHS)
    grid_rows = "".join(
        f"<tr><td>{esc(name)}</td>" + "".join(
            f'<td class="center">{badge(f["controls"][m][name])}</td>' for m in MONTHS) + "</tr>"
        for name in f["controls"][MONTHS[0]])
    return f"""
<section id="close">
  <p class="eyebrow">#N · Close and controls</p>
  <h2>Closed on schedule, checked every month</h2>
  <p>Every close step has a preparer, a different reviewer, a due day, and an automated check. The model
  never signs off for the Controller, so each month stops one step short by design.</p>
  <div class="cards three">{months}</div>
  <div class="card table-card">
    <h3>The eight controls, by month</h3>
    <table class="data grid"><thead><tr><th>Control</th>
      {"".join(f'<th class="center">{MONTH_NAMES[m]}</th>' for m in MONTHS)}</tr></thead>
      <tbody>{grid_rows}</tbody></table>
    <p class="muted small">All eight are detective controls. Preventive controls (rate card, mapping and
    credit memo approvals) are next.</p>
  </div>
  <p class="small"><a href="{REPO}/blob/main/output/workpapers/controls_matrix.md">Controls matrix →</a>
  &nbsp; <a href="{REPO}/blob/main/output/workpapers/sample_tieouts.md">Sample tie-outs →</a>
  &nbsp; <a href="{REPO}/blob/main/output/close_checklist.md">Close checklist →</a></p>
</section>"""


def badge(passed):
    return ('<span class="badge pass">✓ PASS</span>' if passed else '<span class="badge fail">✕ FAIL</span>')


def section_built(text):
    return f"""
<section id="built">
  <p class="eyebrow">#N · How I built it</p>
  <h2>Spec first, then code, one tested step at a time</h2>
  <p>{inline(text["how"])}</p>
  <p class="small"><a href="{REPO}/commits/main">Commit history →</a>
  &nbsp; <a href="{REPO}">The repository →</a></p>
</section>"""


def section_about():
    return f"""
<section id="about">
  <p class="eyebrow">#N · About me</p>
  <h2>Jonah Rice, CPA</h2>
  <p>{esc(ABOUT)}</p>
</section>"""


def number_sections(body):
    """Number the section eyebrows (#N) in page order, so reordering sections renumbers them."""
    counter = iter(range(1, 100))
    return re.sub(r"#N", lambda _: str(next(counter)), body)


def chart_data(f):
    return {
        "months": [MONTH_NAMES[m] for m in MONTHS],
        "revenue": [{"label": CUSTOMERS[c], "data": [str(f["revenue_by_customer"][c][m]) for m in MONTHS]}
                    for c in CUSTOMERS],
        "mock": [{"label": "Credit balance at list", "data": [str(f["mock"][m]["credit"]) for m in MONTHS]},
                 {"label": "Contract liability (× 0.80)", "data": [str(f["mock"][m]["liability"]) for m in MONTHS]}],
    }


def render(f, text, sections):
    body = number_sections("".join([
        section_hero(f, sections), "<main>",
        section_business(f, text),    # 1
        section_judgment(sections),   # 2
        section_dollar(f),            # 3
        section_waterfall(f),         # 4 every dollar accounted for
        section_charts(f),            # 5 where the revenue came from
        section_close(f),             # 6
        section_built(text),          # 7
        section_about(),              # 8
        "</main>"]))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Usage Revenue Case Study</title>
<meta name="description" content="A usage-based revenue recognition model on synthetic data: one quarter closed, reconciled, and tested.">
<!-- Generated by `python run.py` (revrec/site.py). Don't edit by hand: every figure comes from the model. -->
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{body}
<footer>
  <p><strong>Jonah Rice, CPA</strong></p>
  <p class="muted small">All data is synthetic: Hedgehog Metrics and its customers are fictional.
  <a href="{REPO}">View the repository on GitHub</a>.</p>
</footer>
</div>
<script type="application/json" id="chart-data">{json.dumps(chart_data(f), indent=1)}</script>
<script src="{CHART_JS}"></script>
<script>{JS}</script>
</body>
</html>
"""


def run_site(r, docs_dir, readme_path, memo_path):
    """Write docs/index.html from the model's results, README.md and MEMO.md."""
    facts = page_facts(r)
    text = readme_parts(Path(readme_path).read_text(encoding="utf-8"))
    sections = memo_sections(Path(memo_path).read_text(encoding="utf-8"))
    page = render(facts, text, sections)
    Path(docs_dir).mkdir(parents=True, exist_ok=True)
    (Path(docs_dir) / "index.html").write_text(page, encoding="utf-8", newline="\n")
    return {"facts": facts, "html": page, "sections": sections}


# --- Style and chart script (no figures in here) --------------------------------------------------

CSS = """
:root{color-scheme:light;--bg:#f9f9f7;--surface:#fcfcfb;--card:#ffffff;--ink:#0b0b0b;--ink-2:#52514e;
--muted:#898781;--line:#e1e0d9;--axis:#c3c2b7;--accent:#2a78d6;--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;
--good:#006300;--good-bg:#e6f4e6;--bad:#d03b3b;--bad-bg:#fbeaea;--down:#eb6834;--up:#1baf7a;--total:#2a78d6;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0d0d0d;
--surface:#1a1a19;--card:#1a1a19;--ink:#f0efec;--ink-2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--axis:#383835;
--accent:#6da7ec;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--good:#0ca30c;--good-bg:#132613;--bad:#e66767;
--bad-bg:#2a1414;--down:#d95926;--up:#199e70;--total:#3987e5;}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0d0d;--surface:#1a1a19;--card:#1a1a19;--ink:#f0efec;
--ink-2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--axis:#383835;--accent:#6da7ec;--s1:#3987e5;--s2:#d95926;
--s3:#199e70;--good:#0ca30c;--good-bg:#132613;--bad:#e66767;--bad-bg:#2a1414;--down:#d95926;--up:#199e70;
--total:#3987e5;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
a{color:var(--accent);text-underline-offset:3px}
h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.1;letter-spacing:-.02em;margin:.2em 0 .4em}
h2{font-size:clamp(1.5rem,3.2vw,2rem);line-height:1.2;letter-spacing:-.01em;margin:.1em 0 .5em}
h3{font-size:1.05rem;margin:0 0 .4em}
.sub{margin-top:2em}
p{margin:0 0 1em;max-width:70ch}
.eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.78rem;font-weight:600;color:var(--muted);margin:0}
.muted{color:var(--ink-2)}.small{font-size:.9rem}.center{text-align:center}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.hero{padding:72px 0 40px}
.lede{font-size:1.15rem;color:var(--ink-2)}
section{padding:56px 0;border-top:1px solid var(--line)}
footer{border-top:1px solid var(--line);padding:32px 0 56px}
.tiles,.cards{display:grid;gap:16px;margin-top:24px}
.tiles{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.cards.two{grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))}
.cards.three{grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr))}
.tile,.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px}
.tile-value{font-size:2.1rem;font-weight:700;letter-spacing:-.02em;line-height:1.15}
.tile-label{color:var(--ink-2);margin-top:4px}
.tile-note{font-size:.85rem;color:var(--muted);margin-top:14px}
.callout{font-size:1.1rem;font-style:italic;border-left:3px solid var(--accent);padding:4px 0 4px 14px;margin:20px 0}
.flow{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 12px}
.step{flex:1 1 120px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;
position:relative}
.step-name{font-weight:600;font-size:.9rem}
.step-math{color:var(--ink-2);font-size:.82rem;min-height:2.4em}
.step-amt{font-variant-numeric:tabular-nums;font-weight:600;margin-top:4px}
.step-free{border-style:dashed}
.step-total{border-color:var(--total);border-width:2px}
.step-cap{border-color:var(--down);border-width:2px}
.customer .plan{font-weight:600;color:var(--ink-2);font-size:.92rem}
.customer p{margin-bottom:.5em}
.dollar{list-style:none;padding:0;margin:24px 0;counter-reset:step}
.dollar-step{position:relative;padding:0 0 28px 44px;border-left:2px solid var(--line);margin-left:14px}
.dollar-step:last-child{border-left-color:transparent}
.dollar-step::before{counter-increment:step;content:counter(step);position:absolute;left:-15px;top:0;width:28px;
height:28px;border-radius:50%;background:var(--accent);color:#fff;font-weight:700;font-size:.85rem;
display:flex;align-items:center;justify-content:center}
.dollar-head{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap}
.dollar-name{font-weight:700;font-size:1.1rem}
.dollar-amt{font-weight:700;font-size:1.1rem;font-variant-numeric:tabular-nums}
.dollar-step p{margin:.2em 0 .6em;color:var(--ink-2)}
.je{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 12px;max-width:560px;
font-size:.88rem;overflow-x:auto}
.je-head{display:flex;justify-content:space-between;font-weight:600;margin-bottom:4px}
.je-none{color:var(--ink-2)}
table{border-collapse:collapse;width:100%}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:.8rem;color:var(--muted);font-weight:600}
.je td:first-child{padding-left:0}
.chart-card{margin:0}
.chart-box{position:relative;height:280px;margin:12px 0}
details{margin-top:12px}
summary{cursor:pointer;color:var(--accent);font-weight:600;font-size:.92rem}
details[open] summary{margin-bottom:10px}
.data{font-size:.88rem}
.waterfall{margin-top:20px}
.wf-row{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,2fr) auto;gap:12px;align-items:center;
padding:8px 0;border-bottom:1px solid var(--line)}
.wf-label{font-size:.92rem}
.wf-track{position:relative;height:22px;background:linear-gradient(to right,var(--axis) 1px,transparent 1px)}
.wf-bar{position:absolute;top:0;bottom:0;border-radius:4px;min-width:3px}
.wf-total{background:var(--total)}.wf-down{background:var(--down)}.wf-up{background:var(--up)}
.wf-amt{font-variant-numeric:tabular-nums;font-weight:600;text-align:right;min-width:7.5em}
.wf-result{border-bottom:none;font-weight:700}
.waterfall .small{margin:12px 0 0}
.unexplained{font-size:1.25rem;margin-top:20px}
.unexplained strong{color:var(--good)}
#judgment .cards{align-items:start}
.judgment{position:relative;padding-top:18px}
.num-badge{font-weight:700;color:var(--muted);margin:0 0 4px}
.position{font-size:1.05rem;font-weight:500}
.model-note{font-size:.88rem;color:var(--ink-2);border-left:3px solid var(--axis);padding-left:10px}
.judgment details p,.judgment details li{color:var(--ink-2);font-size:.95rem}
.judgment ul{padding-left:1.2em}
.month .big{font-size:1.8rem;font-weight:700;margin:0}
.table-card{margin-top:16px;overflow-x:auto}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.8rem;font-weight:700;white-space:nowrap}
.badge.pass{color:var(--good);background:var(--good-bg)}
.badge.fail{color:var(--bad);background:var(--bad-bg)}
@media (max-width:640px){body{font-size:16px}.hero{padding:44px 0 28px}section{padding:40px 0}
.wf-row{grid-template-columns:1fr auto}.wf-track{grid-column:1/-1;grid-row:2}
.dollar-step{padding-left:30px}.tile-value{font-size:1.8rem}}
"""

JS = """
(function () {
  if (!window.Chart) return;
  var data = JSON.parse(document.getElementById('chart-data').textContent);
  var css = getComputedStyle(document.documentElement);
  function v(name) { return css.getPropertyValue(name).trim(); }
  function usd(n) { return '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = v('--ink-2');
  var axes = {
    x: {grid: {display: false}, border: {color: v('--axis')}},
    y: {grid: {color: v('--line')}, border: {display: false}, beginAtZero: true,
        ticks: {maxTicksLimit: 6, callback: function (n) { return '$' + (n / 1000) + 'k'; }}}
  };
  var tooltip = {callbacks: {label: function (c) { return c.dataset.label + ': ' + usd(c.raw); }}};
  function bars(sets, colors) {
    return sets.map(function (s, i) {
      return {label: s.label, data: s.data.map(Number), backgroundColor: colors[i], borderColor: v('--surface'),
              borderWidth: {top: 2}, borderRadius: 4, borderSkipped: 'bottom', maxBarThickness: 64};
    });
  }
  new Chart(document.getElementById('revenueChart'), {
    type: 'bar',
    data: {labels: data.months, datasets: bars(data.revenue, [v('--s1'), v('--s2'), v('--s3')])},
    options: {maintainAspectRatio: false, interaction: {mode: 'index', intersect: false},
      scales: {x: Object.assign({stacked: true}, axes.x), y: Object.assign({stacked: true}, axes.y)},
      plugins: {legend: {position: 'bottom', labels: {usePointStyle: true, pointStyle: 'rectRounded'}},
        tooltip: Object.assign({footer: null}, tooltip, {callbacks: Object.assign({}, tooltip.callbacks, {
          footer: function (items) { var t = 0; items.forEach(function (i) { t += i.raw; }); return 'Total: ' + usd(t); }
        })})}}
  });
  new Chart(document.getElementById('mockChart'), {
    type: 'bar',
    data: {labels: data.months, datasets: bars(data.mock, [v('--s1'), v('--s3')])},
    options: {maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, scales: axes,
      plugins: {legend: {position: 'bottom', labels: {usePointStyle: true, pointStyle: 'rectRounded'}}, tooltip: tooltip}}
  });
  // Re-measure once layout settles, so a chart drawn before the page finished laying out isn't 0px wide.
  window.addEventListener('load', function () {
    Object.keys(Chart.instances).forEach(function (k) { Chart.instances[k].resize(); });
  });
})();
"""

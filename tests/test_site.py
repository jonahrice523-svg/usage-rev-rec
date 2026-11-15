"""The case study page, docs/index.html (SPEC 6, item 11; build step 12).

The page must show only the model's numbers. These tests:
1. recompute each fact on the page independently from the model's results;
2. check every dollar figure on the page is one of those facts;
3. check the charts' data, the judgment call cards (from MEMO.md), the links, and the CDN pin;
4. check the committed docs/index.html is what `python run.py` produces today, so it's never stale.
"""

import html
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

import run
from revrec.revenue import revenue_by
from revrec.rollforwards import MONTHS, closing
from revrec.site import ABOUT, INTRO, POSITIONS, REPO, memo_sections

D = Decimal
ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def quarter(tmp_path_factory):
    return run.close_quarter(tmp_path_factory.mktemp("site"))


@pytest.fixture(scope="module")
def page(quarter):
    return (quarter["root"] / "docs" / "index.html").read_text(encoding="utf-8")


def visible_text(page_html, drop_memo=True):
    """The page's text as a reader sees it, without scripts (and, by default, without the memo text)."""
    out = re.sub(r"<script.*?</script>", " ", page_html, flags=re.S)
    if drop_memo:
        out = re.sub(r'<details><summary>Read the reasoning</summary>.*?</details>', " ", out, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", out))


def all_values(facts):
    """Every Decimal anywhere in the facts dict."""
    if isinstance(facts, Decimal):
        yield facts
    elif isinstance(facts, dict):
        for value in facts.values():
            yield from all_values(value)
    elif isinstance(facts, (list, tuple)):
        for value in facts:
            yield from all_values(value)


# --- 1. Each fact, recomputed from the model ------------------------------------------------------

def test_headline_facts(quarter):
    f = quarter["site"]["facts"]
    by_month = revenue_by(quarter["schedule"], "month")
    assert f["q1_revenue"] == sum(by_month.values()) == D("55352.25")  # SPEC 5, scenario 6a
    assert f["bridge_count"] == 12  # four bridges x three months
    assert f["largest_unexplained"] == 0
    assert all(b.unexplained == 0 for m in MONTHS for b in quarter["reconciliation"][m])
    for month in MONTHS:
        assert len(f["controls"][month]) == 8 and all(f["controls"][month].values())
        assert (f["checklist"][month]["complete"], f["checklist"][month]["total"]) == (11, 12)
        assert f["checklist"][month]["outstanding"] == ["Close sign-off"]


def test_follow_one_dollar_ties_to_the_invoice_gl_and_cash(quarter):
    t = quarter["site"]["facts"]["tela"]
    lines = quarter["lines"][quarter["lines"].invoice_id == "INV-2026-01-TELA"]
    gl = quarter["gl"][quarter["gl"].customer_id == "TELA"]

    assert t["list"] == sum(D(a) for a in lines[lines.line_type == "usage"].amount) == D("6975.00")
    assert t["billing_limit"] == D("-525.00")  # SPEC 3.4
    january_revenue = gl[(gl.entry_date == "2026-01-31") & (gl.account == "4000")]
    assert t["recognized"] == sum(D(c) for c in january_revenue.credit) == D("6450.00")
    assert t["invoiced"] == quarter["invoices"].set_index("invoice_id").loc["INV-2026-01-TELA", "total"]
    concession = gl[gl.account == "4900"]
    assert t["concession"] == -sum(D(d) for d in concession.debit) == D("-1500.00")
    assert concession.entry_date.iloc[0].startswith("2026-02")  # SPEC 3.4: February, the period of change
    paid = quarter["payments"].set_index("invoice_id").amount
    assert t["cash"] == D(paid["INV-2026-01-TELA"]) == D("4950.00")  # SPEC 5, scenario 3b

    # The story adds up: list - cap = recognized = invoiced; invoiced - concession = cash.
    assert t["list"] + t["billing_limit"] == t["recognized"] == t["invoiced"]
    assert t["invoiced"] + t["concession"] == t["cash"]
    for entry in t["entries"].values():
        assert sum(line["debit"] for line in entry["lines"]) == sum(line["credit"] for line in entry["lines"])


def test_tier_diagram(quarter):
    t = quarter["site"]["facts"]["tiers"]
    assert [x["tier"] for x in t["tiers"]] == ["free", "1", "2", "3"]
    for tier in t["tiers"]:
        assert tier["units"] * tier["unit_price"] == tier["amount"]
    assert (t["list"], t["billing_limit"], t["billed"]) == (D("1525.00"), D("-525.00"), D("1000.00"))
    replay = quarter["ledger"][(quarter["ledger"].customer_id == "TELA") & (quarter["ledger"].usage_month == "2026-01")
                               & (quarter["ledger"]["product"] == "session_replay")]
    assert D(replay.amount.iloc[0]) == t["billed"]


def test_charts_and_waterfall(quarter):
    f = quarter["site"]["facts"]
    by = revenue_by(quarter["schedule"], "month", "customer_id")
    for customer, months in f["revenue_by_customer"].items():
        assert months == {m: by[(m, customer)] for m in MONTHS}
    for month in MONTHS:
        mock = f["mock"][month]
        assert mock["credit"] == closing(quarter["rollforwards"], "credit_balance_at_list", "MOCK", month)
        assert mock["liability"] == closing(quarter["rollforwards"], "contract_liability", "MOCK", month)
        assert mock["liability"] == mock["credit"] * D("0.80")  # SPEC 3.3
    terms = f["credit_terms"]  # SPEC 3.3: $100,000 of credit for $80,000
    assert (terms["credit_value"], terms["cash_price"], terms["per_dollar"]) == (D("100000.00"), D("80000.00"), D("0.8"))
    c = f["bridge_c_january"]
    assert c["lines"][0] == ("Usage at list price, after the free tier", D("21725.00"))
    assert sum(amount for _, amount in c["lines"]) == c["total"] == c["schedule"] == D("18927.25")
    assert c["unexplained"] == 0


# --- 2. Every dollar figure on the page is a model fact -------------------------------------------

def without_about(page_html):
    """The About me section is biography, not model output, so it's checked word for word instead."""
    return re.sub(r'<section id="about">.*?</section>', " ", page_html, flags=re.S)


def test_every_dollar_figure_on_the_page_comes_from_the_model(quarter, page):
    """Every $ figure (with or without cents, unit prices included) equals a model fact."""
    facts = quarter["site"]["facts"]
    allowed = {abs(v) for v in all_values(facts)}
    shown = re.findall(r"[−+]?\$\d[\d,]*(?:\.\d+)?", visible_text(without_about(page)))
    assert len(shown) > 50
    values = {figure: D(figure.lstrip("−+$").replace(",", "")) for figure in shown}
    assert [figure for figure, value in values.items() if value not in allowed] == []
    # And the key figures are really there.
    for figure in ["$0.00", "$6,975.00", "−$525.00", "$6,450.00", "−$1,500.00", "$4,950.00", "$21,725.00",
                   "$18,927.25", "$1,525.00", "$1,000.00", "$0.005", "$525"]:
        assert figure in shown, figure


def test_chart_data_matches_the_model(quarter, page):
    data = json.loads(re.search(r'<script type="application/json" id="chart-data">(.*?)</script>', page, re.S).group(1))
    by = revenue_by(quarter["schedule"], "month", "customer_id")
    customers = {"Harry Hood": "HOOD", "Famous Mockingbird": "MOCK", "Tela": "TELA"}
    assert data["months"] == ["January", "February", "March"]
    for series in data["revenue"]:
        assert [D(x) for x in series["data"]] == [by[(m, customers[series["label"]])] for m in MONTHS]
    credit, liability = data["mock"]
    rf = quarter["rollforwards"]
    assert [D(x) for x in credit["data"]] == [closing(rf, "credit_balance_at_list", "MOCK", m) for m in MONTHS]
    assert [D(x) for x in liability["data"]] == [closing(rf, "contract_liability", "MOCK", m) for m in MONTHS]


# --- 3. Text, cards, links, and the CDN pin --------------------------------------------------------

def flat(page_html):
    return " ".join(visible_text(page_html, drop_memo=False).split())


def test_headline_intro_and_tiles(page):
    hero = flat(re.search(r'<header class="hero">.*?</header>', page, re.S).group(0))
    assert "Usage-based revenue, closed and reconciled." in hero
    assert INTRO in hero
    tiles = re.findall(r'<div class="tile">(.*?)</div>\s*</div>', page, re.S)
    assert [" ".join(visible_text(t).split()) for t in tiles] == [
        "$0.00 unexplained difference in every reconciliation (12 bridges, 3 months)",
        "8 of 8 controls pass, every month",
        "7 judgment calls documented",
    ]
    assert "Q1 revenue" not in hero
    assert "Every number on this page is checked by the test suite." in hero


def test_cap_line_follows_the_billing_limit_example(page):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cap_line = re.search(r"\*\*Why I built this:\*\*\s*(.+)", readme).group(1).split(". ", 1)[1].strip()
    assert "$525 billing cap refuse to become revenue" in cap_line
    business = flat(re.search(r'<section id="business">.*?</section>', page, re.S).group(0))
    assert business.index("Billed and recognized") < business.index(cap_line)
    assert cap_line not in flat(re.search(r'<header class="hero">.*?</header>', page, re.S).group(0))


def test_sections_in_order(page):
    ids = re.findall(r'<section id="([^"]+)"', page)
    assert ids == ["business", "judgment", "dollar", "reconciliation", "charts", "close", "built", "about"]
    eyebrows = re.findall(r'<p class="eyebrow">(\d+) · ', page)
    assert eyebrows == [str(n) for n in range(1, 9)]


def test_no_spec_references_on_the_page(page):
    assert re.search(r"SPEC \d", flat(page)) is None


def test_about_me_and_footer(page):
    about = flat(re.search(r'<section id="about">.*?</section>', page, re.S).group(0))
    assert about == "8 · About me Jonah Rice, CPA " + ABOUT
    assert "Jonah Rice, CPA" in flat(re.search(r"<footer>.*?</footer>", page, re.S).group(0))


def test_judgment_cards_come_from_memo(page):
    memo = (ROOT / "MEMO.md").read_text(encoding="utf-8")
    sections = memo_sections(memo)
    assert len(sections) == len(POSITIONS) == 7
    text = " ".join(visible_text(page, drop_memo=False).split())
    for position in POSITIONS:
        assert position in text
    headings = re.findall(r"^### \d+\.\s*(.+)$", memo, flags=re.M)
    cards = re.findall(r'<article class="card judgment">.*?<h3>(.*?)</h3>', page, re.S)
    assert [html.unescape(c) for c in cards] == [h.strip() for h in headings]
    # The expanded text is MEMO.md's: the first paragraph of each section appears on the page.
    for _, blocks in sections:
        first = re.sub(r"[*_]|\[([^\]]+)\]\([^)]+\)", r"\1", blocks[0])
        assert " ".join(first.split())[:80] in text


def test_every_memo_paragraph_is_in_its_card(page):
    """Each card's expanded text holds the whole MEMO.md section, "From experience" included."""
    memo = (ROOT / "MEMO.md").read_text(encoding="utf-8")
    experience = re.findall(r"^\*\*From experience\.\*\*(.+)$", memo, flags=re.M)
    assert experience  # the memo has them, and they're checked with every other paragraph below
    cards = re.findall(r'<article class="card judgment">(.*?)</article>', page, re.S)
    for _, blocks in memo_sections(memo):
        for block in blocks:
            plain = re.sub(r"\*\*|\*|\[([^\]]+)\]\([^)]+\)", r"\1", re.sub(r"^- ", "", block, flags=re.M))
            assert any(" ".join(plain.split())[:60] in " ".join(visible_text(c, drop_memo=False).split())
                       for c in cards), block[:60]


def test_memo_figures_match_the_model(quarter):
    """Every $ and % figure in MEMO.md (shown in the cards) recomputed from the model.

    If the memo gains a new figure, this test fails until the figure is added here with its source.
    """
    import pandas as pd
    out = quarter["root"] / "output"
    lag = pd.read_csv(out / "lag_report.csv", dtype=str).set_index("usage_month")
    passed = quarter["close"]["passed_log"].iloc[0]
    f = quarter["site"]["facts"]
    terms, tela, by_month = f["credit_terms"], f["tela"], f["revenue_by_month"]
    drawdown = sum(D(a) for a in quarter["ledger"][quarter["ledger"].event_type == "credit_drawdown"].amount)

    def dollars(x, places=2):
        x = D(x).quantize(D(1) / 10 ** places) if places else D(x).quantize(D(1))
        return f"${x:,}"

    def pct(x, places):
        return f"{(D(x) * 100).quantize(D(1) / 10 ** places) if places else (D(x) * 100).quantize(D(1))}%"

    expected = {
        "$80,000": dollars(terms["cash_price"], 0),                       # SPEC 3.3
        "$100,000": dollars(terms["credit_value"], 0),
        "$0.80": dollars(terms["per_dollar"]),
        "$1.00": dollars(terms["dollar"]),
        "20%": pct(1 - terms["per_dollar"], 0),
        "$1,000": dollars(f["tiers"]["billed"], 0),                       # Tela's replay limit, SPEC 3.4
        "$525": dollars(-tela["billing_limit"], 0),
        "$1,500": dollars(-tela["concession"], 0),
        "23%": pct(-tela["concession"] / tela["invoiced"], 0),
        "2.7%": pct(-tela["concession"] / f["q1_revenue"], 1),
        "$13,240": dollars((drawdown / 3 / 10).quantize(D(1)) * 10, 0),   # "about": Q1 pace, nearest $10
        "1%": pct(lag.loc["2026-01", "lag_rate"], 0),                     # SPEC 3.2
        "$32.25": dollars(lag.loc["2026-01", "estimate"]),
        "$40": dollars(lag.loc["2026-01", "actual_late_usage"], 0),
        "1.24%": pct(D(lag.loc["2026-01", "actual_late_usage"]) / D(lag.loc["2026-01", "processed_usage_revenue"]), 2),
        "$0": dollars(lag.loc["2026-02", "actual_late_usage"], 0),
        "$7.75": dollars(lag.loc["2026-01", "change_in_estimate"]),
        "0.5%": pct(passed.threshold_pct, 1),
        "$50": dollars(passed.amount, 0),
        "0.26%": pct(D(passed.amount) / by_month["2026-01"], 2),
        "0.28%": pct(D(passed.amount) / by_month["2026-03"], 2),
    }
    memo = (ROOT / "MEMO.md").read_text(encoding="utf-8")
    found = set(re.findall(r"\$[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?%", memo))
    assert found == set(expected), "new or removed figure in MEMO.md"
    assert {k: v for k, v in expected.items() if k != v} == {}


def test_links_point_to_the_repo(page):
    for href in re.findall(r'href="([^"]+)"', page):
        assert href.startswith(REPO), href


def test_one_external_script_pinned_to_an_exact_version(page):
    sources = re.findall(r'<script[^>]*src="([^"]+)"', page)
    assert len(sources) == 1
    assert re.fullmatch(r"https://cdnjs\.cloudflare\.com/ajax/libs/Chart\.js/\d+\.\d+\.\d+/chart\.umd\.min\.js",
                        sources[0])
    assert "<link" not in page  # no external stylesheets or fonts


# --- 4. The committed page is current ----------------------------------------------------------------

def test_committed_page_matches_a_fresh_run(page):
    committed = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert committed.replace("\r\n", "\n") == page, "docs/index.html is stale: run `python run.py`"

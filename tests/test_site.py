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
from revrec.site import POSITIONS, REPO, memo_sections, money

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

def test_every_dollar_figure_on_the_page_comes_from_the_model(quarter, page):
    facts = quarter["site"]["facts"]
    allowed = {money(v) for v in all_values(facts)} | {money(v, sign=True) for v in all_values(facts)}
    allowed |= {money(0)}
    shown = re.findall(r"[−+]?\$[\d,]+\.\d{2}", visible_text(page))
    assert len(shown) > 50
    assert [figure for figure in shown if figure not in allowed] == []
    # And the headline figures are really there.
    for figure in ["$55,352.25", "$0.00", "$6,975.00", "−$525.00", "$6,450.00", "−$1,500.00", "$4,950.00",
                   "$21,725.00", "$18,927.25", "$1,525.00", "$1,000.00"]:
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

def test_tiles_intro_and_footer(page):
    text = " ".join(visible_text(page).split())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    why = re.search(r"\*\*Why I built this:\*\*\s*(.+)", readme).group(1).strip()
    assert why in text
    assert "Usage-based revenue, closed and reconciled." in text
    assert "8 of 8 controls pass, every month" in text
    assert "Every number on this page is checked by the test suite." in text
    assert "Jonah Rice, CPA" in text


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


def test_from_experience_paragraphs_stay_off_the_page(page):
    """They name real companies, and the page uses no real company names."""
    memo = (ROOT / "MEMO.md").read_text(encoding="utf-8")
    experience = re.findall(r"^\*\*From experience\.\*\*(.+)$", memo, flags=re.M)
    assert experience  # the memo has them
    text = " ".join(visible_text(page, drop_memo=False).split())
    assert "From experience" not in text
    for paragraph in experience:
        assert " ".join(paragraph.split())[:60] not in text


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

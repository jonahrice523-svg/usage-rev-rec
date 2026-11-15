"""Plain-language reply to Tela's billing question (SPEC 3.4; build step 9).

Tela asked in early February why January's invoice is higher than December's. The reply
is dated February 5, before Tela raised the dispute. It compares December and January
units and dollars by product, points out the jump in event volume, suggests Tela check
for a new environment or project sending events, and suggests a billing limit on events.
It promises no credit.

The wording is fixed; every number comes from the model's data, so the reply always ties
to the invoices. It's written for a customer, so it avoids accounting terms.
"""

from decimal import Decimal
from pathlib import Path

PRODUCT_NAMES = {"event_analytics": "Event analytics", "session_replay": "Session replay",
                 "feature_flags": "Feature flags"}
UNIT_NAMES = {"event_analytics": "events", "session_replay": "recordings", "feature_flags": "flag requests"}
TIER_NAMES = {"free": "Free allowance", "1": "Tier 1", "2": "Tier 2", "3": "Tier 3"}
DECEMBER, JANUARY = "INV-2025-12-TELA", "INV-2026-01-TELA"


def money(amount):
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def signed_money(amount):
    return money(amount) if amount < 0 else f"+{money(amount)}"


def change(before, after):
    return f"+{after - before:,}" if after >= before else f"{after - before:,}"


def build_reply(lines, limits):
    dec = lines[lines.invoice_id == DECEMBER]
    jan = lines[lines.invoice_id == JANUARY]
    caps = limits["TELA"]

    rows = []
    for product in PRODUCT_NAMES:
        d = dec[dec["product"] == product]
        j = jan[jan["product"] == product]
        dec_units = int(d.units.astype(int).sum())
        jan_units = int(j[j.line_type == "usage"].units.astype(int).sum())
        dec_amount = sum(Decimal(a) for a in d.amount)
        jan_amount = sum(Decimal(a) for a in j.amount)
        rows.append((product, dec_units, jan_units, dec_amount, jan_amount))

    dec_total = sum(r[3] for r in rows)
    jan_total = sum(r[4] for r in rows)
    events = next(r for r in rows if r[0] == "event_analytics")
    ratio = Decimal(events[2]) / Decimal(events[1])
    jan_events = jan[(jan["product"] == "event_analytics") & (jan.line_type == "usage")]
    replay_cap_line = jan[jan.line_type == "billing_limit"]
    capped = -sum(Decimal(a) for a in replay_cap_line.amount)
    replay_list = sum(Decimal(a) for a in jan[(jan["product"] == "session_replay") & (jan.line_type == "usage")].amount)
    replay_limit = caps["session_replay"]

    out = [
        "# Re: Why is our January invoice higher than December's?",
        "",
        "**To:** Tela finance team  ",
        "**From:** Hedgehog Metrics Billing Team  ",
        "**Date:** February 5, 2026  ",
        f"**Invoices:** {DECEMBER} (December usage) and {JANUARY} (January usage)",
        "",
        "Hi Tela team,",
        "",
        f"Thanks for asking. Your January invoice is **{money(jan_total)}**, up {money(jan_total - dec_total)} "
        f"from December's **{money(dec_total)}**. The short answer: **your event volume more than doubled**, "
        f"from {events[1]:,} events in December to {events[2]:,} in January ({ratio:.1f} times as many).",
        "",
        "## December and January side by side",
        "",
        "| Product | December usage | January usage | Change in usage | December charge | January charge | Change in charge |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for product, du, ju, da, ja in rows:
        out.append(f"| {PRODUCT_NAMES[product]} | {du:,} {UNIT_NAMES[product]} | {ju:,} {UNIT_NAMES[product]} | "
                   f"{change(du, ju)} | {money(da)} | {money(ja)} | {signed_money(ja - da)} |")
    out += [f"| **Total** | | | | **{money(dec_total)}** | **{money(jan_total)}** | **{signed_money(jan_total - dec_total)}** |",
            "",
            "## What drove the increase",
            "",
            f"**Event analytics ({money(events[4] - events[3])} of the increase).** Event volume went from "
            f"{events[1]:,} to {events[2]:,}. Pricing is tiered: the first 1,000,000 events each month are free, "
            "and each tier after that costs less per event. Most of January's extra volume was billed at the "
            "lowest tier rate, so the charge rose by less than the volume did. Here is how January's events were priced:",
            "",
            "| Tier | Events | Price per event | Charge |",
            "|---|---:|---:|---:|"]
    for row in jan_events.itertuples():
        out.append(f"| {TIER_NAMES[row.tier]} | {int(row.units):,} | ${Decimal(row.unit_price):f} | {money(Decimal(row.amount))} |")
    out += ["",
            f"**Session replay ({money(rows[1][4] - rows[1][3])}).** Recordings went from {rows[1][1]:,} to "
            f"{rows[1][2]:,}. At standard prices, January's recordings would have cost {money(replay_list)}. "
            f"Your monthly session replay limit of {money(replay_limit)} capped the charge, so you saved "
            f"{money(capped)}. That shows as a separate \"Monthly billing limit\" line on the invoice.",
            "",
            f"**Feature flags ({money(rows[2][4] - rows[2][3])}).** Flag requests went from {rows[2][1]:,} to "
            f"{rows[2][2]:,}.",
            "",
            "## Something worth checking",
            "",
            "A jump in event volume this size often means a new source started sending events. Could you check "
            "whether a new environment (for example a test or staging setup) or a new project began sending "
            "events to Hedgehog Metrics in January? If so, you can filter or turn off events from that source.",
            "",
            "To avoid surprises in future months, you can also set a **monthly billing limit on event analytics**, "
            "the same way you already have one on session replay. Once a limit is set, you're never charged more "
            "than that amount for the product in a month.",
            "",
            "## How usage is counted",
            "",
            "Usage is counted in the month our servers receive it, using UTC (Coordinated Universal Time). Events "
            "your devices send just before midnight in your time zone on the last day of a month can arrive after "
            "midnight UTC and count in the next month.",
            "",
            "If you'd like a day-by-day breakdown of January's usage, just reply and we'll send it.",
            "",
            "Best regards,  ",
            "Hedgehog Metrics Billing Team",
            ""]
    return "\n".join(out), {"dec_total": dec_total, "jan_total": jan_total, "rows": rows, "capped": capped}


def run_billing_reply(output_dir, lines, limits):
    text, figures = build_reply(lines, limits)
    Path(output_dir, "billing_reply_tela.md").write_text(text, encoding="utf-8", newline="\n")
    return text, figures

# Re: Why is our January invoice higher than December's?

**To:** Tela finance team  
**From:** Hedgehog Metrics Billing Team  
**Date:** February 5, 2026  
**Invoices:** INV-2025-12-TELA (December usage) and INV-2026-01-TELA (January usage)

Hi Tela team,

Thanks for asking. Your January invoice is **$6,450.00**, up $2,650.00 from December's **$3,800.00**. The short answer: **your event volume more than doubled**, from 90,000,000 events in December to 200,000,000 in January (2.2 times as many).

## December and January side by side

| Product | December usage | January usage | Change in usage | December charge | January charge | Change in charge |
|---|---:|---:|---:|---:|---:|---:|
| Event analytics | 90,000,000 events | 200,000,000 events | +110,000,000 | $2,100.00 | $4,300.00 | +$2,200.00 |
| Session replay | 287,500 recordings | 600,000 recordings | +312,500 | $900.00 | $1,000.00 | +$100.00 |
| Feature flags | 9,000,000 flag requests | 15,000,000 flag requests | +6,000,000 | $800.00 | $1,150.00 | +$350.00 |
| **Total** | | | | **$3,800.00** | **$6,450.00** | **+$2,650.00** |

## What drove the increase

**Event analytics ($2,200.00 of the increase).** Event volume went from 90,000,000 to 200,000,000. Pricing is tiered: the first 1,000,000 events each month are free, and each tier after that costs less per event. Most of January's extra volume was billed at the lowest tier rate, so the charge rose by less than the volume did. Here is how January's events were priced:

| Tier | Events | Price per event | Charge |
|---|---:|---:|---:|
| Free allowance | 1,000,000 | $0 | $0.00 |
| Tier 1 | 4,000,000 | $0.00005 | $200.00 |
| Tier 2 | 20,000,000 | $0.00003 | $600.00 |
| Tier 3 | 175,000,000 | $0.00002 | $3,500.00 |

**Session replay ($100.00).** Recordings went from 287,500 to 600,000. At standard prices, January's recordings would have cost $1,525.00. Your monthly session replay limit of $1,000.00 capped the charge, so you saved $525.00. That shows as a separate "Monthly billing limit" line on the invoice.

**Feature flags ($350.00).** Flag requests went from 9,000,000 to 15,000,000.

## Something worth checking

A jump in event volume this size often means a new source started sending events. Could you check whether a new environment (for example a test or staging setup) or a new project began sending events to Hedgehog Metrics in January? If so, you can filter or turn off events from that source.

To avoid surprises in future months, you can also set a **monthly billing limit on event analytics**, the same way you already have one on session replay. Once a limit is set, you're never charged more than that amount for the product in a month.

## How usage is counted

Usage is counted in the month our servers receive it, using UTC (Coordinated Universal Time). Events your devices send just before midnight in your time zone on the last day of a month can arrive after midnight UTC and count in the next month.

If you'd like a day-by-day breakdown of January's usage, just reply and we'll send it.

Best regards,  
Hedgehog Metrics Billing Team

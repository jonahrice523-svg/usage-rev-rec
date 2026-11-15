# Revenue accounting policy memo: Hedgehog Metrics, Q1 2026

## Purpose

This memo explains the accounting behind the model: the policies it applies, the judgment calls they required, and where I landed on each one. The model shows *what* happened each month. This memo shows *why*, and it's the best evidence that I understand usage-based billing and revenue recognition rather than just the code that produces the numbers.

## The business in one paragraph

Hedgehog Metrics is a fictional product-led analytics platform. Customers send it product data (events, session recordings, and feature flag requests) and pay for what they use. Each product has a monthly free allowance, then graduated tiers that get cheaper per unit as volume grows, and customers can cap their own monthly spend per product. Most customers pay monthly in arrears. Larger ones prepay for a year of credit at a 20% discount and draw it down as they go. That makes the revenue accounting more interesting than a typical subscription business:

- The price isn't known until the month is over.
- The data that sets the price can arrive late, or twice.
- Cash and revenue for prepaid customers move on completely different schedules.
- The customer, not the contract, decides where the ceiling is.

## Policies applied

Full detail is in [SPEC.md](SPEC.md) section 3.

- **Usage revenue.** Pay-as-you-go usage is a series of distinct monthly services. Each month's usage fee is recognized in that month, after the free tier, the graduated tiers, and any billing limit. Free usage is never revenue.
- **Cutoff and the lag estimate.** Usage belongs to the month HM receives it, in UTC. Duplicates are removed before pricing. Routine processing lag is estimated at close and trued up the next month. Unbilled usage at month end is a receivable, not a contract asset, because only the passage of time stands between HM and payment (ASC 606-10-45-4).
- **Prepaid credit and breakage.** The $80,000 invoice for $100,000 of credit is a contract liability. Revenue is recognized at $0.80 per $1.00 of credit consumed, so the liability always equals remaining credit × 0.80. Breakage is held at zero.
- **Billing limits and the concession.** Billing limits are applied before revenue, so capped usage is never billed or recognized. Tela's $1,500 credit for disputed January usage is a price concession, recorded as contra-revenue in February.

## Judgment calls

### 1. Allocation vs the right-to-invoice expedient

**Position.** I anchor on the standard ASC 606 approach for every contract. Pay-as-you-go usage fees are allocated to the month they relate to (RR 5.5.1.1, Example RR 5-9), and prepaid credit is recognized as it's consumed (RR 6.4.3).

**Why.** For pay-as-you-go usage billed monthly in arrears, the right-to-invoice expedient gives exactly the same numbers, so this isn't about the answer. It's about what holds up long term. The expedient only works when what we can invoice tracks the value we've delivered, and it's all or nothing for a contract. It already fails for prepaid credit: we invoice $80,000 up front on January 1, but the value is delivered through the year as usage comes in, so invoicing and revenue don't line up. I'd rather run one approach that works for every contract type, and keeps working when pricing changes, than a shortcut that covers some contracts and has to be re-checked every time someone adds an upfront fee or a minimum commitment.

**Billing limits.** Tela's $1,000 replay limit meant $525 of January usage was never billed. That doesn't weaken the argument. The limit is a price term the customer chose, value is measured at the contract price, not list, and the limit resets monthly, so no revenue shifts between periods. If capped usage became large or frequent, though, I'd watch it as a sign that billing was drifting from value delivered.

**What would change my mind.** A contract book that was entirely simple pay-as-you-go with consistent per-unit pricing. There, the expedient makes revenue equal billing, cuts documentation, and allows some disclosure relief. I'd consider electing it for those contracts while keeping the standard approach for prepaid credit and anything with upfront fees, minimums, or ramps. The expedient would also matter for any service that isn't a series of similar periods, such as a consulting project building toward one deliverable. There, allocating fees to each month isn't available (RR 3.3.2, RR 5.5.1.1), and the expedient can be the only simple route. HM's usage service is a series, so that case doesn't arise here.

**From experience.** I've worked on the other side of this choice. At User Interviews, customers bought an allotment of credits and spent them on research studies, with different study types costing different numbers of credits. Projects were lumpy, and the package bundled access to the participant panel, project coordination, and ongoing customer success, so we treated it as a stand-ready bundle and recognized revenue straight-line. As we planned the move to usage-based pricing, billing was going to follow the credits consumed each month. That meant mapping every project type to its credit cost and getting that usage data from the website, through the data warehouse, into Chargebee so monthly billing could run automatically. Once billing follows consumption, the recognition question changes with it, and that shift is what this model works through.

### 2. When breakage can move off zero

**Position.** Expected breakage is held at zero for now and reassessed every month.

**Why.** HM has no history with credit contracts, and limited experience is one of the factors the standard lists for constraining an estimate (ASC 606-10-32-11 and 32-12(c); RR 7.4). Recognizing breakage early on a guess risks booking revenue I'd have to reverse later in the year. The model's own data points the same way: at Famous Mockingbird's Q1 pace (about $13,240 of credit a month), its credit runs out around mid-August, so even an unconstrained estimate would be close to zero.

**What would change my mind.** A few years of history on credit contracts that have actually reached expiry, grouped by segment (contract size and terms), stable enough to estimate reliably. Contract terms are the precondition, since HM's credit expires at term end with no refund, but usage data is what tells you how much will go unused. Customer-specific evidence could also count: a large customer whose usage pace clearly can't consume the remaining balance before expiry. Before recognizing any breakage, I'd confirm unused credit isn't subject to unclaimed property (escheat) rules (RR 7.4).

**From experience.** At User Interviews, before the usage-based plan, unused credits rolled into the next term. Because revenue was recognized straight-line as a stand-ready bundle, unused credits didn't change revenue at all. Under a usage-based model, unused credits would have needed a much closer look as potential breakage.

### 3. Which clock defines the month

**Position.** Usage belongs to the month HM receives it, in UTC, regardless of when the customer's device generated it.

**Why.** HM's service is what happens to customer data once it arrives. HM ingests it (accepts it, validates it, and drops duplicates), processes it (ties it to the right user and session), stores it, and makes it usable in dashboards, reports, and session replays. All of that, and the computing and storage cost behind it, happens after receipt, so HM performs when the data arrives. The device timestamp records the customer's own activity, and it's set by a clock HM doesn't control. Receipt time is HM's own record, which makes it reliable and auditable. It also removes most "late usage" questions entirely. A customer importing a year of historical data in February is simply February usage: their activity happened over the year, but our service happened in February.

**HM's own delays are different.** If HM received data in January but its pipeline didn't process it until after the close, that's still January usage. If January is still open, it goes into January. If January is closed, it's recorded in the current month as a change in estimate, unless it's material. In the model, the lag batch (received January 31, processed February 6) is covered by the 1% estimate and trued up by $7.75 in February.

**The contract has to match.** Billing terms should define billable usage the same way ("events received during each calendar month, UTC"), so the invoice and revenue never follow different clocks.

**What I'd plan for up front.** At User Interviews we were still in the planning phase when I left, so we never ran a usage close. If I were planning it again, I'd settle three things before go-live: the timestamp that defines billable usage, written into the customer terms; a cutoff day for each close; and a monthly report of usage received but not processed by that cutoff.

### 4. Setting the lag rate and the close threshold

**Lag rate.** Usage processing is automated. A pipeline ingests events, removes duplicates, matches them to customers, totals them, and prices them. That pipeline has a small, routine lag: queues back up at month end, scheduled jobs only run so often, and failed jobs retry. So some usage HM received in a month isn't priced by the cutoff on business day 3. Because the lag comes from the same system every month, it's measurable, so I estimate it rather than hold the close open. I'd set the rate from the trailing three to six months of the lag report (usage received but not processed by the cutoff), leave outages and other one-off incidents out, and refresh it quarterly. In the model the rate is 1%, or $32.25 for Harry Hood each month. The actual was $40 (1.24%) for January and $0 for February.

**Close threshold.** Unusual items the estimate doesn't anticipate, like a bug fix that reprocesses a closed month, are measured across all customers for the month combined, so twenty small items can't each slip under the line. Below the threshold, they're recorded in the current month and logged with a running total. Above it, they aren't automatically a prior-period error. They go to a person to evaluate under ASC 250, and the outcome could still be a current-month adjustment. I'd agree the threshold with the auditors during planning and set it below their "clearly trivial" amount, so what we pass never adds up to something they'd want booked.

**Which month to measure against.** The model compares unusual items to 0.5% of the current month's revenue. The stronger policy, and the one I'd adopt, checks both the month the item belongs to and the month it's booked in, and uses the stricter result. March's $50 bug fix passes both easily: it's 0.26% of January's revenue and 0.28% of March's.

**Size isn't the only test.** An item under the threshold still gets escalated if it would change a number the board watches, such as monthly revenue growth, or if it points to a control failure that could happen again.

### 5. When concessions become a practice

**Position.** One concession is an event; a pattern is an estimate. Tela's $1,500 credit was the only one in the quarter (23% of Tela's January invoice, 2.7% of Q1 revenue). So it was recorded in February as a price concession, reducing revenue in the period the price changed (RR 4.3.3.1, RR 5.5.2), and wasn't reserved for in advance.

**Concession, not bad debt.** Tela could pay. The credit was about dissatisfaction with usage it hadn't intended, so it's contra-revenue, not a credit loss.

**What would make it a practice.** I'd watch how often credits are issued, whether the reasons repeat, whether Sales or CS promise them, and whether CS has standing authority to give them. Once credits are predictable, they're estimated up front: a monthly reserve based on the historical credit rate (debit contra-revenue, credit refund liability), trued up to actual credits (RR 4.3.3.1, Example RR 4-9).

**Look for the root cause.** Tela's dispute came from a misconfigured test environment, which HM's own February 5 billing reply helped Tela find. If that became a pattern, it's a product question as much as an accounting one: for example, should new projects start with a billing limit by default?

**From experience.** At User Interviews' stage, credits and concessions were infrequent enough that we handled them as they came rather than forecasting them. At a company with thousands of self-serve customers, credits are frequent enough that I'd expect to estimate them, and that's the point where this policy matters.

### 6. Controls: what an auditor would test, and who owns them

**Where the risk is.** In usage-based billing, the biggest audit risk isn't the journal entries. It's whether the usage data feeding them is complete and accurate. I'd expect an auditor to focus on:

- completeness and accuracy of the usage data, since reports a company produces from its own systems get tested for reliability
- the accuracy of the rate card and how pricing changes are approved
- the reconciliation from the billing ledger to the GL
- cutoff at month end
- the contract liability rollforward
- credit memo approvals and manual entries to revenue

**Who owns what.**

- **Billing engineering** owns the pipeline: ingestion completeness, removing duplicates, rate card configuration, and the IT controls around them.
- **Finance** owns the account mapping, the reconciliations and their review, journal entries, the lag estimate, and the credit memo approval policy.
- **Shared:** the reconciliation from usage to invoices (the model's controls matrix assigns it to revenue accounting).

The [controls matrix](output/workpapers/controls_matrix.md) lists each control's owner and reviewer. Every control passes in all three months.

**What's missing.** All eight controls in the model are detective: they catch problems after the fact. A real close also needs preventive controls that stop problems before they happen: approving rate card changes and account mapping changes before they take effect, and approval limits on credit memos. Those are first on my list for the next version.

**From experience.** As the main contact for our auditors at User Interviews, I saw where they spent their time on revenue. New products and pricing models that hadn't been tested in prior years got the most attention, and a move to usage-based billing would land squarely in that category. They tested the reports coming out of Chargebee, our source for revenue recognition data, and traced transactions back to signed contracts. They also tested capitalized commissions, checking that commission expense was recognized over the expected average customer life, which we broke out by customer segment.

### 7. When the billing ledger and the GL disagree

**Position.** Neither wins automatically. The billing ledger is the source and the GL reports it. In the model, the GL is generated only from the billing ledger, through an account mapping that finance owns, so a disagreement means something broke in between.

**What a difference means.** One of three things:

- a mapping error, where an event type posts to the wrong account or isn't mapped at all
- a sync that failed or only partly ran
- someone posting directly to revenue or AR in the GL

**How I'd fix it.** Find the cause at the source, fix it there, and re-sync. Never plug the GL: a plug fixes the report and hides the problem. I'd limit who can post manual entries to revenue and AR, so the third cause mostly can't happen. Finance owns the reconciliation and its resolution, and billing engineering fixes system issues.

**How the model catches it.** Every ledger row is either mapped or lands in exceptions, each GL account total ties to the ledger, and rerunning the export produces identical output.

**From experience.** At User Interviews we posted summary entries from Chargebee into QuickBooks to recognize revenue, and they generally tied. When they didn't, manual entries were almost always the cause, which is why I'd rather limit who can post manually than rely on catching it in the reconciliation. Part of our revenue was transactional, pay-as-you-go, and we ran an accrued revenue workflow for it, recognizing revenue as projects and sessions were completed. Delays in processing those completions sometimes surfaced as out-of-period adjustments. That's the same problem this model's lag estimate and close threshold are built to handle.

## What I'd do next

- **Close the gaps the model exposed.** Famous Mockingbird's credit runs out around mid-August, so the next version should model credit exhaustion and overage billing at pay-as-you-go rates. It should also add the preventive controls above, and tighten the close threshold to check both the month an item belongs to and the month it's booked in.
- **Finish the workpaper pack.** A revenue lead sheet and a tickmarked contract liability rollforward.

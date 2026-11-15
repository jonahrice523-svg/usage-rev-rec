"""Turn raw usage rows into monthly quantities to price (SPEC 3.2).

1. Remove duplicate rows on event_id; they become exceptions and are never billed.
2. Assign each row to a month by received_ts, in UTC.
3. Split each month's usage into:
   - processed by the close cutoff (business day 3 of the next month): priced at close
   - processed after the cutoff: HM-side lag, covered by the lag estimate
   - bug_fix_reprocess rows: unusual items, kept separate
"""

from dataclasses import dataclass

import pandas as pd

from revrec.dates import business_day, next_month


@dataclass
class UsageSummary:
    monthly: pd.DataFrame      # customer_id, month, product, quantity: processed by the cutoff
    duplicates: pd.DataFrame   # the extra copies removed (exceptions)
    lag: pd.DataFrame          # rows received in a month but processed after its cutoff
    reprocessed: pd.DataFrame  # bug_fix_reprocess rows


def load_usage(path):
    usage = pd.read_csv(path, dtype=str, keep_default_na=False)
    usage["quantity"] = usage["quantity"].astype(int)
    return usage


def cutoff_date(month, cutoff_business_day):
    """Close cutoff for a usage month "YYYY-MM": business day n of the following month."""
    year, number = int(month[:4]), int(month[5:7])
    return business_day(*next_month(year, number), cutoff_business_day)


def summarize(usage, cutoff_business_day=3):
    # SPEC 3.2: deduplicate on event_id before pricing; duplicates are logged, never billed.
    is_duplicate = usage.duplicated("event_id", keep="first")
    duplicates = usage[is_duplicate]
    rows = usage[~is_duplicate].copy()

    # SPEC 3.2: the period follows received_ts (UTC), whatever the client_ts.
    rows["month"] = rows["received_ts"].str[:7]

    # SPEC 3.2: processed by the end of business day 3 (UTC) is in the close; later is lag.
    cutoffs = rows["month"].map(lambda m: cutoff_date(m, cutoff_business_day).isoformat())
    on_time = rows["processed_ts"].str[:10] <= cutoffs

    # SPEC 3.2, 5: the bug-fix reprocess is an unusual item, not lag.
    reprocessed = rows[rows["source"] == "bug_fix_reprocess"]
    normal = rows["source"] == "normal"
    lag = rows[normal & ~on_time]

    monthly = (rows[normal & on_time]
               .groupby(["customer_id", "month", "product"], as_index=False)["quantity"].sum())
    return UsageSummary(monthly, duplicates, lag, reprocessed)

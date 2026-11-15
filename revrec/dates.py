"""Calendar helpers for the close."""

from datetime import date, timedelta


def business_day(year, month, n):
    """Return the nth business day of a month.

    SPEC 1: business days are weekdays, with no holidays in the model period.
    """
    day = date(year, month, 1)
    count = 0
    while True:
        if day.weekday() < 5:  # Monday=0 ... Friday=4
            count += 1
            if count == n:
                return day
        day += timedelta(days=1)


def next_month(year, month):
    """Return (year, month) for the month after the one given."""
    return (year + 1, 1) if month == 12 else (year, month + 1)

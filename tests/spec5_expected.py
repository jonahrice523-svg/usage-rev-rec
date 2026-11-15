"""SPEC 5 check-scenario usage, priced by product. Shared by the pricing and usage tests.

Billed amounts are after the billing limit. Product-level amounts were confirmed
independently by Jonah in a spreadsheet; the totals are in SPEC 5.
"""

# customer, month, (events, recordings, flags),
#   events $, replay list $, replay billed $, flags $, billed total $
SPEC_5_DOLLARS = [
    ("HOOD", 1, (30_000_000, 300_000, 20_000_000), "900", "925", "925", "1400", "3225"),
    ("HOOD", 2, (30_000_000, 300_000, 20_000_000), "900", "925", "925", "1400", "3225"),
    ("HOOD", 3, (30_000_000, 300_000, 20_000_000), "900", "925", "925", "1400", "3225"),
    ("MOCK", 1, (300_000_000, 1_000_000, 50_000_000), "6300", "2325", "2325", "2900", "11525"),
    ("MOCK", 2, (400_000_000, 1_500_000, 60_000_000), "8300", "3325", "3325", "3400", "15025"),
    ("MOCK", 3, (350_000_000, 1_200_000, 55_000_000), "7300", "2725", "2725", "3150", "13175"),
    ("TELA", 1, (200_000_000, 600_000, 15_000_000), "4300", "1525", "1000", "1150", "6450"),
    ("TELA", 2, (120_000_000, 400_000, 12_000_000), "2700", "1125", "1000", "1000", "4700"),
    ("TELA", 3, (100_000_000, 300_000, 10_000_000), "2300", "925", "925", "900", "4125"),
]

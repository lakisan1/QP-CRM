"""P1-T5a characterization: shared.utils.format_amount / format_date AS IS.

Captured from the unmodified app via tests/_capture.py. Pinned quirks:

* format_amount: European "12.312,00" style; None -> "0,00" (a missing
  value prints as zero, never empty); non-numeric strings -> "";
  NUMERIC strings are parsed ("12.5" -> "12,50"); negatives keep the
  sign; more than 2 decimals are rounded by the %-format.
* format_date: strictly splits on "-" and reassembles per fmt; a value
  that is not YYYY-MM-DD but contains dashes gets its parts RELABELED
  ("15-01-2026" -> "2026/01/15" for DD/MM/YYYY) instead of failing;
  garbage without dashes passes through unchanged; None/"" -> "".
"""

import pytest

from qp_crm.shared.utils import format_amount, format_date


class TestFormatAmount:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, "0,00"),          # None renders as zero, NOT empty
            (0, "0,00"),
            (12312, "12.312,00"),
            (1234.5, "1.234,50"),
            (-1234.5, "-1.234,50"),  # sign preserved
            ("abc", ""),             # non-numeric -> empty string
            ("12.5", "12,50"),       # numeric STRING is parsed
            (1234567.891, "1.234.567,89"),
            (0.005, "0,01"),
            (1000000.0, "1.000.000,00"),
        ],
    )
    def test_captured_cases(self, value, expected):
        assert format_amount(value) == expected


class TestFormatDate:
    @pytest.mark.parametrize(
        "date_str, fmt, expected",
        [
            ("2026-01-15", "DD/MM/YYYY", "15/01/2026"),
            ("2026-01-15", "MM/DD/YYYY", "01/15/2026"),
            ("2026-01-15", "DD.MM.YYYY", "15.01.2026"),
            ("2026-01-15", "YYYY-MM-DD", "2026-01-15"),
            ("2026-01-15", None, "2026-01-15"),          # unknown fmt -> passthrough
            ("15-01-2026", "DD/MM/YYYY", "2026/01/15"),  # parts silently RELABELED
            ("garbage", "DD/MM/YYYY", "garbage"),        # no dashes -> passthrough
            (None, "DD/MM/YYYY", ""),
            ("", "DD/MM/YYYY", ""),
        ],
    )
    def test_captured_cases(self, date_str, fmt, expected):
        assert format_date(date_str, fmt) == expected

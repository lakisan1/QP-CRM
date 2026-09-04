"""P1-T4 characterization: rent math -- pmt / calculate_rent / schedule AS IS.

Pure functions (no DB). Captured from the unmodified app via
tests/_capture.py and hand-checked against rent/app.py:61-157. Pinned
quirks:

* pmt replicates Excel PMT with sign conventions: caller passes
  pv NEGATIVE, fv positive; pmt_type=1 (annuity due) multiplies the
  denominator by (1+rate), giving a LOWER payment.
* nper == 0 raises ZeroDivisionError in BOTH branches -- live-contract
  poison input.
* zatvaranje (downpayment spread) is CONSTANT for every month:
  ucesce_bruto/period_months; rata_nakon never declines (the schedule
  prints the same value for month 1 and month 48).
* generate_schedule dates monthly rows on the LAST DAY of each month
  (contract date day is discarded); rows 0.1/0.2 sit on the contract date.
* An unparsable contract date silently falls back to date.today() --
  non-deterministic by design; pinned against date.today() at test time.
"""

from datetime import date, datetime

import pytest

from qp_crm.rent.app import _add_months, calculate_rent, generate_schedule, pmt

# Signature used by rent/_contract_form defaults and the golden contract:
# price 20 000, 48 months, 20% down, 20% salvage, 14% interest,
# 1.13% insurance, 5% guarantee, 20% VAT, 50 admin fee.
CALC_ARGS = (20000.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 20.0, 50.0)


class TestPmt:
    def test_zero_rate_is_straight_line(self):
        # -(pv + fv) / nper = -(-16000 + 4000) / 48
        assert pmt(0.0, 48, -16000.0, 4000.0) == 250.0

    def test_nonzero_rate_matches_excel_pmt(self):
        # captured literal from the unmodified app
        assert pmt(0.14 / 12, 48, -16000.0, 4000.0) == 374.58438460722857

    def test_pmt_type_1_annuity_due_is_lower(self):
        due = pmt(0.14 / 12, 48, -16000.0, 4000.0, 1)
        assert due == 370.26463058375145
        assert due < pmt(0.14 / 12, 48, -16000.0, 4000.0)

    def test_nper_zero_raises_zero_division_error(self):
        with pytest.raises(ZeroDivisionError):
            pmt(0.0, 0, -16000.0)
        with pytest.raises(ZeroDivisionError):
            pmt(0.1, 0, -16000.0)


class TestCalculateRent:
    @pytest.fixture(scope="class")
    def calc(self):
        return calculate_rent(*CALC_ARGS)

    def test_downpayment_block(self, calc):
        assert calc["ucesce"] == 4000.0
        assert calc["ucesce_pdv"] == 800.0
        assert calc["ucesce_bruto"] == 4800.0

    def test_salvage(self, calc):
        assert calc["ostatak"] == 4000.0

    def test_financing_rate(self, calc):
        # rata_fin == pmt(monthly_rate, n, -(price - ucesce), ostatak)
        expected_fin = pmt(14.0 / 100 / 12, 48, -(20000.0 - 4000.0), 4000.0)
        assert calc["rata_fin"] == expected_fin
        assert calc["rata_fin"] == 374.58438460722857

    def test_insurance_is_flat_monthly_price_share(self, calc):
        # 1.13% of price / 12 -- constant over the whole term
        assert calc["osiguranje"] == 18.833333333333332

    def test_guarantee_spread_over_months(self, calc):
        assert calc["garancija"] == 20.833333333333332

    def test_payment_block(self, calc):
        assert calc["rata_neto"] == 414.2510512738952
        assert calc["rata_pdv"] == 82.85021025477904
        assert calc["rata_bruto"] == 497.10126152867423

    def test_zatvaranje_is_constant_and_rata_nakon_never_declines(self, calc):
        # 4800 / 48 == 100 every month; rata_nakon == rata_bruto - zatvaranje
        assert calc["zatvaranje"] == 100.0
        assert calc["rata_nakon"] == 397.10126152867423

    def test_admin_fee_block(self, calc):
        assert calc["admin_fee"] == 50.0
        assert calc["admin_pdv"] == 10.0
        assert calc["admin_bruto"] == 60.0


class TestAddMonths:
    @pytest.mark.parametrize(
        "d, months, expected",
        [
            (date(2026, 1, 31), 1, date(2026, 2, 28)),   # clamped to month end
            (date(2026, 1, 15), 3, date(2026, 4, 15)),   # plain addition
            (date(2024, 1, 31), 1, date(2024, 2, 29)),   # leap year
            (date(2026, 12, 31), 2, date(2027, 2, 28)),  # year rollover + clamp
        ],
    )
    def test_clamping(self, d, months, expected):
        assert _add_months(d, months) == expected


class TestGenerateSchedule:
    @pytest.fixture(scope="class")
    def rows(self):
        calc = calculate_rent(*CALC_ARGS)
        return generate_schedule(calc, "2026-01-15", 3)

    def test_row_count_is_two_headers_plus_months(self, rows):
        assert len(rows) == 5  # 0.1 + 0.2 + months 1..3

    def test_header_rows_on_contract_date(self, rows):
        r01, r02 = rows[0], rows[1]
        assert r01["nr"] == "0.1" and r02["nr"] == "0.2"
        assert r01["datum"] == "15.01.2026" and r02["datum"] == "15.01.2026"
        assert r01["opis"] == "Uplata naknada za procenu boniteta"
        assert r01["druge"] == 50.0 and r01["pdv"] == 10.0 and r01["suma"] == 60.0
        assert r02["opis"] == "Uplata avansa"
        assert r02["avans"] == 4000.0 and r02["pdv"] == 800.0 and r02["suma"] == 4800.0

    def test_monthly_rows_last_day_of_month(self, rows):
        assert [r["datum"] for r in rows[2:]] == ["28.02.2026", "31.03.2026", "30.04.2026"]
        assert [r["nr"] for r in rows[2:]] == ["1", "2", "3"]
        assert all(r["opis"] == "Zakupnina" for r in rows[2:])

    def test_monthly_rows_exact_amounts(self, rows):
        for row in rows[2:]:
            assert row["neto"] == 414.2510512738952
            assert row["pdv"] == 82.85021025477904
            assert row["suma"] == 497.10126152867423
            assert row["zatvaranje"] == 100.0          # constant every month
            assert row["suma_nakon"] == 397.10126152867423

    def test_bad_date_falls_back_to_today(self):
        # rent/app.py:129-132 -- silent date.today() fallback
        calc = calculate_rent(*CALC_ARGS)
        rows = generate_schedule(calc, "not-a-date", 1)
        expected_today = date.today().strftime("%d.%m.%Y")
        assert rows[0]["datum"] == expected_today
        assert rows[2]["datum"] != expected_today  # +1 month, month-end shifted


def test_schedule_dates_parse_as_dd_mm_yyyy():
    # the printed schedule feeds the PDF plan -- dates must stay parseable
    calc = calculate_rent(*CALC_ARGS)
    rows = generate_schedule(calc, "2026-01-31", 2)
    for row in rows:
        datetime.strptime(row["datum"], "%d.%m.%Y")

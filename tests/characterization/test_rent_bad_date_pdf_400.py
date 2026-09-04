"""Regression for the phase-2 bug-fix stage (board card "BUG - rent
generate_schedule: bad contract date silently falls back to date.today()").

Before the fix, a contract whose contract_date is unparsable/empty produced
schedule PDFs dated from the DAY OF RENDERING -- two renders differed, and
nothing flagged the corrupt date. After the fix, generate_schedule raises
ValueError and the schedule PDF routes answer 400 with a clear message.

The pure-function side is pinned in test_rent_calc.py
(test_bad_date_raises_value_error); this file proves the user-visible
behavior end-to-end through the real /rent routes.
"""

import pytest


CONTRACT_SQL = """
    INSERT INTO rent_contracts (id, contract_number, contract_date, client_name,
        client_mb, client_pib, client_account, client_address,
        client_representative, client_email, rent_address, guarantor,
        delivery_time, delivery_date, equipment_model, price, vat_percent,
        period_months, downpayment_percent, salvage_value_percent,
        interest_rate, insurance_rate, guarantee_rate, admin_fee)
    VALUES (:cid, 'UGOVOR-BAD-DATE', :contract_date, 'Bad Date d.o.o.',
            '11111111', '101010101', '160-000000-01',
            'Zlatna ulica 15, 11000 Beograd', 'Marko Markovic',
            'bad@example.rs', 'Radionica 2, Novi Sad', '',
            '10 dana', '2026-01-25', 'CNC centar 500', 20000.0,
            20.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 50.0)
"""


@pytest.fixture
def bad_contract_id(temp_db, conn_factory):
    # temp_db is session-scoped: make the insert idempotent across tests.
    with conn_factory() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM rent_contracts WHERE id = 900100;")
        cur.execute(CONTRACT_SQL, {"cid": 900100, "contract_date": "not-a-date"})
        conn.commit()
    return 900100


def test_schedule_pdf_returns_400_on_bad_date(
        temp_db, conn_factory, rent_client, bad_contract_id):
    response = rent_client.get(f"/rent/contracts/pdf/schedule/{bad_contract_id}")
    assert response.status_code == 400
    assert b"Neispravan datum ugovora" in response.data


def test_schedule_fillable_pdf_returns_400_on_bad_date(
        temp_db, conn_factory, rent_client, bad_contract_id):
    response = rent_client.get(
        f"/rent/contracts/pdf/schedule_fillable/{bad_contract_id}")
    assert response.status_code == 400
    assert b"Neispravan datum ugovora" in response.data


def test_valid_date_still_renders_pdf(
        temp_db, conn_factory, rent_client, bad_contract_id):
    # Control: same contract with a repaired date renders a PDF again.
    with conn_factory() as conn:
        conn.execute(
            "UPDATE rent_contracts SET contract_date='2026-01-15' WHERE id=900100;")
        conn.commit()
    response = rent_client.get(f"/rent/contracts/pdf/schedule/{bad_contract_id}")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"

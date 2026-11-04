"""Offer item ordinals ("BR." / "Rb.") -- user report 2026-11-04.

line_order is both the ordering key and the user-visible ordinal (edit form
"BR." column, offer view page, PDFs order BY line_order, id). It used to be
append-only (MAX+1) and was copied verbatim when an offer was duplicated, so
add/delete cycles left holes ("1, 8, 17, 25" -- 16 of 83 live offers) and
every duplicate inherited them; a stale drag-and-drop list could even write
the same ordinal twice.

Pinned here:
* add item / delete item leave a contiguous 1..n sequence;
* a duplicate gets its own 1..n ordinals in the source order;
* the reorder route renumbers ALL items (partial/stale list safe);
* the boot repair (offer.init_db -> normalize_offer_item_orders) closes the
  holes of existing rows once, idempotently;
* the form and the view page print the POSITION, not the stored value.
"""

import re

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.db import get_db
from qp_crm.services.offer_service import (
    normalize_offer_item_orders,
    renumber_offer_items,
)


@pytest.fixture(autouse=True)
def _clean():
    conn = get_db()
    conn.execute("DELETE FROM offer_items")
    conn.execute("DELETE FROM offers")
    conn.commit()
    try:
        yield
    finally:
        conn.execute("DELETE FROM offer_items")
        conn.execute("DELETE FROM offers")
        conn.commit()
        conn.close()


def _offer(number="ORD-1"):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO offers (offer_number, date, client_name) VALUES (?, '2026-11-04', 'Kupac');",
        (number,))
    conn.commit()
    offer_id = cur.lastrowid
    conn.close()
    return offer_id


def _item(offer_id, name, order):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO offer_items (offer_id, line_order, item_name, quantity,
           unit_price, discount_percent, line_net)
           VALUES (?, ?, ?, 1, 100, 0, 100);""",
        (offer_id, order, name))
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def _orders(offer_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT item_name, line_order FROM offer_items WHERE offer_id = ? "
        "ORDER BY line_order, id;", (offer_id,)).fetchall()
    conn.close()
    return [(row["item_name"], row["line_order"]) for row in rows]


def _post(client, path, data):
    data = dict(data)
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data, follow_redirects=False)


def _add(client, offer_id, name):
    response = _post(client, f"/offer/offers/{offer_id}/edit", {
        "action": "add_item",
        "product_id": "",
        "item_name": name,
        "item_description": "",
        "quantity": "1",
        "unit_price": "100",
    })
    assert response.status_code == 302, response.data[:300]


# ---------------------------------------------------------------------------
# mutations keep 1..n
# ---------------------------------------------------------------------------

def test_adding_an_item_to_a_holed_offer_closes_the_holes():
    client = login_client(app.test_client(), "offer")
    offer_id = _offer()
    _item(offer_id, "A", 1)
    _item(offer_id, "B", 8)   # legacy hole
    _item(offer_id, "C", 17)

    _add(client, offer_id, "D")

    assert _orders(offer_id) == [("A", 1), ("B", 2), ("C", 3), ("D", 4)]


def test_deleting_a_middle_item_keeps_the_sequence():
    client = login_client(app.test_client(), "offer")
    offer_id = _offer()
    _item(offer_id, "A", 1)
    b = _item(offer_id, "B", 2)
    _item(offer_id, "C", 3)

    response = _post(client, f"/offer/offers/{offer_id}/edit", {
        "action": "delete_item", "item_id": str(b)})
    assert response.status_code == 302

    assert _orders(offer_id) == [("A", 1), ("C", 2)]


def test_duplicate_starts_a_clean_sequence_in_source_order():
    client = login_client(app.test_client(), "offer")
    offer_id = _offer("ORD-DUP")
    _item(offer_id, "A", 1)
    _item(offer_id, "B", 8)   # holes the copy used to inherit verbatim
    _item(offer_id, "C", 25)

    response = _post(client, f"/offer/offers/{offer_id}/duplicate", {})
    assert response.status_code == 302
    new_id = int(response.headers["Location"].split("/offers/")[1].split("/")[0])
    assert new_id != offer_id

    assert _orders(new_id) == [("A", 1), ("B", 2), ("C", 3)]
    # the source keeps its own (legacy) values until the boot repair / an edit
    assert _orders(offer_id) == [("A", 1), ("B", 8), ("C", 25)]


def test_reorder_with_a_stale_partial_list_has_no_duplicates():
    client = login_client(app.test_client(), "offer")
    offer_id = _offer()
    a = _item(offer_id, "A", 1)
    b = _item(offer_id, "B", 2)
    _item(offer_id, "C", 3)
    new_item = _item(offer_id, "NEW", 4)  # added in another tab, page is stale

    # stale page only knows A and B (C/NEW were added/deleted meanwhile)
    response = client.post(
        f"/offer/offers/{offer_id}/reorder",
        json={"item_ids": [b, a]},
        headers={"X-CSRF-Token": csrf_token_for(client)},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True

    rows = _orders(offer_id)
    assert [order for _, order in rows] == [1, 2, 3, 4]  # no gaps/duplicates
    assert [name for name, _ in rows] == ["B", "A", "C", "NEW"]
    assert new_item


# ---------------------------------------------------------------------------
# boot repair (offer.init_db) + idempotency
# ---------------------------------------------------------------------------

def test_normalize_is_idempotent_and_order_preserving():
    offer_id = _offer()
    _item(offer_id, "A", 1)
    _item(offer_id, "B", 8)
    _item(offer_id, "C", 9)

    conn = get_db()
    cur = conn.cursor()
    assert normalize_offer_item_orders(cur) == 1
    conn.commit()
    assert normalize_offer_item_orders(cur) == 0  # already clean -> no-op
    conn.close()

    assert _orders(offer_id) == [("A", 1), ("B", 2), ("C", 3)]


def test_offer_init_db_repairs_existing_rows(temp_db):
    """The boot/restore sequence must close the holes of rows nobody edits."""
    offer_id = _offer()
    _item(offer_id, "A", 2)
    _item(offer_id, "B", 11)

    from qp_crm.offer.app import init_db
    init_db()

    assert _orders(offer_id) == [("A", 1), ("B", 2)]


def test_renumber_fixes_duplicate_ordinals():
    offer_id = _offer()
    a = _item(offer_id, "A", 3)
    b = _item(offer_id, "B", 3)  # same ordinal, older reorder bug

    conn = get_db()
    cur = conn.cursor()
    renumber_offer_items(cur, offer_id)
    conn.commit()
    conn.close()

    rows = _orders(offer_id)
    assert [order for _, order in rows] == [1, 2]
    assert [name for name, _ in rows] == ["A", "B"]  # id breaks the tie
    assert b > a


# ---------------------------------------------------------------------------
# display: the position, not the stored value
# ---------------------------------------------------------------------------

def test_edit_form_and_view_print_the_position():
    client = login_client(app.test_client(), "offer")
    offer_id = _offer()
    _item(offer_id, "A", 1)
    _item(offer_id, "B", 8)  # legacy hole, not repaired in this test
    _item(offer_id, "C", 17)

    form = client.get(f"/offer/offers/{offer_id}/edit").data.decode()
    row_indexes = re.findall(r'class="row-index">(\d+)<', form)
    assert row_indexes == ["1", "2", "3"]

    view = client.get(f"/offer/offers/{offer_id}/view").data.decode()
    # the view table row starts with <td ...>{{ loop.index }}</td>, so the
    # rows print 1,2,3 even though line_order is 1,8,17
    view_indexes = re.findall(
        r'<tr>\s*<td style="text-align: center;">(\d+)</td>', view)
    assert view_indexes == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# adjacent list-logic fix: the Offers/Templates toggle under an item filter
# ---------------------------------------------------------------------------

def test_item_filter_respects_the_templates_toggle():
    client = login_client(app.test_client(), "offer")
    conn = get_db()
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Ordinal test product');").lastrowid
    plain = conn.execute(
        """INSERT INTO offers (offer_number, date, client_name, is_template)
           VALUES ('FILTER-PLAIN', '2026-11-04', 'Kupac', 0);""").lastrowid
    tpl = conn.execute(
        """INSERT INTO offers (offer_number, date, client_name, is_template)
           VALUES ('FILTER-TPL', '2026-11-04', 'Kupac', 1);""").lastrowid
    for offer_id in (plain, tpl):
        conn.execute(
            """INSERT INTO offer_items (offer_id, product_id, line_order, item_name,
               quantity, unit_price, discount_percent, line_net)
               VALUES (?, ?, 1, 'Stavka', 1, 100, 0, 100);""",
            (offer_id, product_id))
    conn.commit()
    conn.close()

    plain_page = client.get(f"/offer/offers?item={product_id}").data.decode()
    assert "FILTER-PLAIN" in plain_page
    assert "FILTER-TPL" not in plain_page

    tpl_page = client.get(f"/offer/offers?item={product_id}&view=templates").data.decode()
    assert "FILTER-TPL" in tpl_page
    assert "FILTER-PLAIN" not in tpl_page


# ---------------------------------------------------------------------------
# drag-and-drop: markdown TABLES inside item descriptions are nested <tr>
# ---------------------------------------------------------------------------

def test_drag_renumber_ignores_nested_description_table_rows():
    """The item description is rendered as markdown ('extra' extension), so a
    product spec table becomes a real <table><tr> inside the item row. The
    drag handler used a bare querySelectorAll('tr') and counted those nested
    rows -- after a drag the visible "BR." numbers jumped until a refresh
    recomputed them on the server (user report 2026-11-04)."""
    client = login_client(app.test_client(), "offer")
    offer_id = _offer()
    _item(offer_id, "A", 1)
    table_item = _item(offer_id, "B", 2)
    _item(offer_id, "C", 3)
    conn = get_db()
    conn.execute(
        "UPDATE offer_items SET item_description = ? WHERE id = ?",
        ("| Parametar | Specifikacija |\n|---|---|\n| Sistem | Android 9 |\n"
         "| RAM | 4 GB |", table_item))
    conn.commit()
    conn.close()

    page = client.get(f"/offer/offers/{offer_id}/edit").data.decode()

    # hazard: the description table puts extra <tr> inside the items body
    body_start = page.index('id="items-body"')
    body_end = page.index("</tbody>", body_start)
    rows_in_body = re.findall(r"<tr\b", page[body_start:body_end])
    assert len(rows_in_body) == 3 + 2  # 3 items + 2 spec-table rows

    # fix: the reorder handler only walks item rows (they carry data-id)
    assert "querySelectorAll('tr[data-id]')" in page
    assert "querySelectorAll('tr').forEach" not in page

"""Voucher / supplier invoice / supplier payment completeness per reservation (synthetic GetTrip/v3, no client data)."""

from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.myt.paperwork import paperwork_check
from myt_mcp.services import Services
from tests.test_reservations import FakeMYT, _res, _v3

TODAY = date(2026, 10, 15)

V3 = _v3(
    [
        _res(1, 10, "RateHawk", "Hotel Uno", 225.0, 1, 1, "2026-10-15"),
        _res(2, 10, "RateHawk", "Hotel Due", 281.0, 1, 2, "2026-10-16", "2026-10-18"),
        _res(3, 20, "Cooking Co", "Cooking workshop", 150.0, 2, 1, "2026-10-18"),
        _res(4, 30, "Car Co", "VW T-Cross", 600.0, 1, 1, "2026-10-15"),
    ],
    {1: "VoucherSent", 2: "ConfirmedByTo", 3: "NotSent", 4: "NotSent"},
    [],
)


def rows(result):
    return {r["order_id"]: r for r in result["rows"]}


def test_everything_present_and_equal_is_complete():
    result = paperwork_check(
        V3, TODAY,
        vouchers=[{"order_id": 1, "number": "V1"}],
        invoices=[{"order_id": 1, "amount": 225.0, "currency": "EUR"}],
        payments=[{"order_id": 1, "amount": 225.0, "currency": "EUR"}],
    )
    assert rows(result)[1]["complete"] and rows(result)[1]["voucher"]["numbers"] == ["V1"]
    assert result["totals"]["complete"] == 1 and result["totals"]["incomplete"] == 3


def test_missing_documents_are_listed_per_reservation():
    r = rows(paperwork_check(V3, TODAY, vouchers=[], invoices=[], payments=[]))
    assert r[3]["missing"] == ["voucher", "supplier invoice", "supplier payment"] and not r[3]["complete"]


def test_voucher_issued_status_without_a_voucher_is_flagged():
    r = rows(paperwork_check(V3, TODAY, [], [], []))
    assert any("Voucher Issued" in f for f in r[1]["flags"])          # order 1 is VoucherSent
    assert not any("Voucher Issued" in f for f in r[3]["flags"])


def test_invoice_amount_difference_and_payment_amounts():
    result = paperwork_check(
        V3, TODAY, [],
        invoices=[{"order_id": 4, "amount": 73.79}, {"order_id": 1, "amount": 225.0}],
        payments=[{"order_id": 1, "amount": 100.0}, {"order_id": 4, "amount": 800.0}],
    )
    r = rows(result)
    assert any("invoice 73.79 differs" in f for f in r[4]["flags"])
    assert any("LESS than the invoice 225.0" in f and "partial" in f for f in r[1]["flags"])
    assert any("MORE than the invoice 73.79" in f for f in r[4]["flags"])


def test_two_payments_are_added_up():
    r = rows(paperwork_check(V3, TODAY, [{"order_id": 1, "number": "V1"}], [{"order_id": 1, "amount": 225.0}], [{"order_id": 1, "amount": 100.0}, {"order_id": 1, "amount": 125.0}]))
    assert r[1]["supplier_payment"]["paid"] == 225.0 and not r[1]["flags"]


def test_rounding_inside_the_tolerance_is_fine():
    r = rows(paperwork_check(V3, TODAY, [{"order_id": 1, "number": "V1"}], [{"order_id": 1, "amount": 225.4}], [{"order_id": 1, "amount": 225.4}]))
    assert r[1]["flags"] == []


def test_match_by_supplier_name_and_amount_when_the_supplier_has_two_orders():
    r = rows(paperwork_check(V3, TODAY, [], [{"supplier": "RateHawk", "amount": 562.0}], []))
    assert r[2]["supplier_invoice"]["found"] and not r[1]["supplier_invoice"]["found"]


def test_ambiguous_or_unknown_documents_are_reported_not_guessed():
    result = paperwork_check(V3, TODAY, [{"supplier": "RateHawk", "number": "V9"}], [{"order_id": 999, "amount": 5.0}, {"supplier": "Nobody"}], [])
    text = " ".join(result["documents_not_matched"])
    assert "has 2 reservations" in text and "order 999" in text and "Nobody" in text
    assert not any(r["voucher"]["found"] for r in result["rows"])


def test_other_currency_is_not_compared():
    r = rows(paperwork_check(V3, TODAY, [], [{"order_id": 1, "amount": 771.59, "currency": "ILS"}], []))
    assert any("not in EUR" in f for f in r[1]["flags"])


def test_trip_without_reservations():
    result = paperwork_check({"trip": {"trip_id": 1}}, TODAY, [], [], [])
    assert result["rows"] == [] and result["totals"]["reservations"] == 0


@pytest.mark.anyio
async def test_tool_passes_screen_rows_through_and_refuses_other_trips():
    settings = Settings(allowed_trip_ids=frozenset({1001}))
    async with Client(create_server(settings, Services(settings, myt=FakeMYT(V3)))) as c:
        ok = await c.call_tool("check_reservation_paperwork", {"trip_id": 1001, "vouchers": [{"order_id": 1, "number": "V1"}]})
        other = await c.call_tool("check_reservation_paperwork", {"trip_id": 5})
    assert not ok.is_error and "V1" in ok.content[0].text and "supplier_invoice" in ok.content[0].text
    assert other.is_error and "outside the allowed test trips" in other.content[0].text


def test_screen_doc_accepts_the_order_id_as_the_screen_writes_it():
    from myt_mcp.tools.reservations import ScreenDoc

    assert ScreenDoc(order_id="R2342199").order_id == 2342199
    assert ScreenDoc(order_id="r2342199").order_id == 2342199
    assert ScreenDoc(order_id=2342199).order_id == 2342199
    assert ScreenDoc(order_id=" 2342199 ").order_id == 2342199
    assert ScreenDoc().order_id is None


def test_one_order_with_several_rows_matches_one_voucher_for_the_order_total():
    """Trip 435 (17 Oct 2026): Arbitrip is ONE order of six rows (ILS 12,043 in total) with ONE voucher of ILS 12,043."""
    def ils(r):
        return {**r, "currency": {"name": "ILS"}}
    arbitrip = [ils(_res(7, 70, "Arbitrip", f"Hotel night {n}", price, 1, 1, f"2026-09-{19 + n}")) for n, price in enumerate((3492.0, 3354.0, 725.0, 1378.0, 1272.0, 1822.0))]
    other = _res(8, 80, "Terreiro", "Dinner", 130.0, 1, 1, "2026-10-02")
    other2 = _res(9, 80, "Terreiro", "Dinner 2", 130.0, 1, 1, "2026-10-03")
    v3 = _v3(arbitrip + [other, other2], {7: "VoucherPaid", 8: "VoucherPaid", 9: "VoucherPaid"}, [])
    for r in v3["reservations"][:6]:
        r["order_id"] = 7          # six product rows of one order
    result = paperwork_check(v3, TODAY, vouchers=[{"supplier": "Arbitrip", "number": "V2295", "amount": 12043.0, "currency": "ILS"}], invoices=[], payments=[])
    r = rows(result)
    assert result["totals"]["orders"] == 3 and result["totals"]["product_rows"] == 8
    assert r[7]["items"] == 6 and r[7]["reservation_cost"] == 12043.0 and r[7]["voucher"] == {"found": True, "numbers": ["V2295"]}
    assert not result["documents_not_matched"]
    assert any("Voucher Paid" in f for f in r[8]["flags"])          # paid status without a voucher found is flagged for the others


def test_two_orders_of_one_supplier_with_the_same_amount_still_ask_for_the_order_id():
    v3 = _v3([_res(1, 10, "Terreiro", "Dinner", 130.0, 1, 1, "2026-10-02"), _res(2, 10, "Terreiro", "Dinner 2", 130.0, 1, 1, "2026-10-03")], {1: "VoucherPaid", 2: "VoucherPaid"}, [])
    result = paperwork_check(v3, TODAY, vouchers=[{"supplier": "Terreiro", "number": "V1", "amount": 130.0, "currency": "EUR"}], invoices=[], payments=[])
    assert result["documents_not_matched"] and "give the order id" in result["documents_not_matched"][0]

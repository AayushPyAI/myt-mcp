"""Supplier reservations, voucher flags and reconciliation. The payload is synthetic and shaped like GetTrip/v3
(no client data): reservations carry a unit price, quantity and duration; order_documents carry the status."""

from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.myt.client import MYTError
from myt_mcp.myt.reservations import reconcile, reservations_summary
from myt_mcp.services import Services

TODAY = date(2026, 10, 15)


def _d(iso: str) -> dict:
    return {"date": f"{iso}T00:00:00", "string": iso}


def _res(order, supplier_id, supplier, product, price, qty, duration, start, end=None):
    return {
        "order_id": order, "reservation_id": order + 1, "supplier_id": supplier_id, "supplier_name": supplier,
        "product_name": product, "price": {"amount": price}, "quantity": qty, "duration": duration,
        "currency": {"name": "EUR"}, "dates": {"start": _d(start), "end": _d(end or start)},
        "contact_info": {"email": "hidden@example.com"},
    }


def _line(supplier_id, supplier, product, unit, qty, nights, day, pricing="PS"):
    return {"name": product, "supplier_name": supplier, "supplier_id": supplier_id, "PP": pricing == "PP", "quantity": qty,
            "nights": nights, "unit_price": {"amount": unit}, "total_price": {"amount": round(unit * qty * nights, 2)},
            "start_date": _d(day), "type": {"name": "Lodging"}, "currency": {"name": "EUR"}}


def _v3(reservations, statuses, lines):
    return {
        "trip": {"trip_id": 1001},
        "reservations": reservations,
        "order_documents": [{"order_id": o, "status": {"name": s}} for o, s in statuses.items()],
        "quotation": {"number": "10-1", "version": 1, "status": "Draft", "currency": {"name": "EUR"},
                      "product_packages": [{"id": 1, "title": "Package 1", "pax_free": [{"pax": 2, "free": 0, "price": {"products": lines}}]}]},
    }


V3 = _v3(
    [
        _res(1, 10, "RateHawk", "Hotel Uno", 225.0, 1, 1, "2026-10-15"),
        _res(2, 10, "RateHawk", "Hotel Due", 281.0, 1, 2, "2026-10-16", "2026-10-18"),
        _res(3, 20, "Cooking Co", "Cooking workshop", 150.0, 2, 1, "2026-10-18"),
        _res(4, 30, "Car Co", "VW T-Cross", 600.0, 1, 1, "2026-10-15"),
        _res(5, 40, "Train Co", "Rome - Florence", 30.0, 2, 1, "2026-10-16"),
        _res(6, 50, "Far Away", "Late tour", 80.0, 1, 1, "2027-03-01"),
    ],
    {1: "VoucherSent", 2: "ConfirmedByTo", 3: "NotSent", 4: "NotSent", 5: "NotSent", 6: "NotSent"},
    [
        _line(10, "RateHawk", "Hotel Uno", 254.25, 1, 1, "2026-10-15"),
        _line(10, "RateHawk", "Hotel Due", 317.53, 1, 2, "2026-10-16"),
        _line(20, "Cooking Co", "Cooking workshop", 154.5, 2, 1, "2026-10-18", "PP"),
        _line(30, "Car Co", "VW T-Cross or similar", 83.38, 1, 1, "2026-10-15"),
        _line(40, "Train Co", "Rome - Florence, 09:10", 113.0, 1, 1, "2026-10-16"),
        _line(99, "No Reservation Ltd", "Dinner", 50.0, 2, 1, "2026-10-17", "PP"),
    ],
)


def test_amount_is_price_times_quantity_times_duration():
    rows = {r["order_id"]: r for r in reservations_summary(V3, TODAY)["reservations"]}
    assert rows[2]["total_cost"] == 562.0      # 281 x 2 nights
    assert rows[3]["total_cost"] == 300.0      # 150 x 2 people
    assert rows[5]["total_cost"] == 60.0


def test_statuses_use_the_screen_names_and_unknown_ones_pass_through():
    v3 = _v3([_res(1, 1, "S", "P", 10, 1, 1, "2027-01-01"), _res(2, 1, "S", "Q", 10, 1, 1, "2027-01-02")], {1: "VoucherSent", 2: "SomethingNew"}, [])
    rows = {r["order_id"]: r for r in reservations_summary(v3, TODAY)["reservations"]}
    assert rows[1]["status"] == "Voucher Issued" and rows[1]["status_api"] == "VoucherSent"
    assert rows[2]["status"] == "SomethingNew"


def test_voucher_flags_only_for_unsent_orders_that_start_soon():
    flags = reservations_summary(V3, TODAY, soon_days=7)["voucher_flags"]
    text = " ".join(flags)
    assert "Car Co" in text and "Train Co" in text and "Cooking Co" in text      # NotSent, starting within 7 days
    assert "RateHawk" not in text and "Far Away" not in text                     # voucher sent / confirmed, or far away
    assert "starts in 0 day(s)" in text


def test_a_service_in_the_past_is_flagged_as_started():
    v3 = _v3([_res(1, 1, "S", "P", 10, 1, 1, "2026-10-10")], {1: "NotSent"}, [])
    assert "started 5 day(s) ago" in reservations_summary(v3, TODAY)["voucher_flags"][0]


def test_no_contact_details_leave_the_summary():
    assert "hidden@example.com" not in str(reservations_summary(V3, TODAY)) and "hidden@example.com" not in str(reconcile(V3, TODAY))


def test_reconcile_accepts_usual_profits_and_flags_the_rest():
    result = reconcile(V3, TODAY)
    rows = {r["order_id"]: r for r in result["rows"]}
    assert rows[1]["verdict"] == "ok" and rows[1]["implied_profit_pct"] == 13.0
    assert rows[2]["verdict"] == "ok"                                  # 562 x 1.13 = 635.06
    assert rows[3]["verdict"] == "ok" and rows[3]["implied_profit_pct"] == 3.0
    assert rows[4]["verdict"] == "MISMATCH" and "implied profit" in rows[4]["notes"][0]
    assert rows[5]["verdict"] == "MISMATCH"
    assert result["totals"]["rows_ok"] == 3 and result["totals"]["rows_to_check"] == 2


def test_reconcile_flags_a_date_difference():
    v3 = _v3([_res(1, 10, "RateHawk", "Hotel Uno", 100.0, 1, 1, "2026-10-15")], {1: "NotSent"},
             [_line(10, "RateHawk", "Hotel Uno", 113.0, 1, 1, "2026-10-20")])
    row = reconcile(v3, TODAY)["rows"][0]
    assert row["verdict"] == "MISMATCH" and "date differs" in row["notes"][0]


def _ils(res):
    res["currency"] = {"name": "ILS"}
    return res


def test_a_shekel_reservation_against_a_euro_line_is_not_a_mismatch():
    """26 Oct 2026: all 19 shekel reservations of 13 real trips (lounges, guides) were flagged MISMATCH against euro lines: 1000 ILS at 3.53 is 283.28 EUR."""
    v3 = _v3([_ils(_res(1, 10, "Lounge Co", "TLV lounge", 1000.0, 1, 1, "2026-10-15")), _ils(_res(2, 11, "Guide Co", "Guide day", 400.0, 1, 1, "2026-10-16"))], {1: "NotSent", 2: "NotSent"},
             [_line(10, "Lounge Co", "TLV lounge", 283.28, 1, 1, "2026-10-15"), _line(11, "Guide Co", "Guide day", 128.06, 1, 1, "2026-10-16")])
    plain = reconcile(v3, TODAY)
    assert [r["verdict"] for r in plain["rows"]] == ["CURRENCY", "CURRENCY"] and plain["totals"]["rows_in_another_currency"] == 2
    assert "3.53 at 0% profit" in plain["rows"][0]["notes"][0] and "eur_to_ils" in plain["rows"][0]["notes"][0] and plain["rows"][0]["reservation_currency"] == "ILS"
    converted = reconcile(v3, TODAY, eur_to_ils=3.53)["rows"]
    assert converted[1]["verdict"] == "ok" and "= 113.31 EUR at 3.53" in converted[1]["notes"][0]          # 400 ILS = 113.31 EUR, line = cost + 13%
    assert converted[0]["verdict"] == "MISMATCH" and "implied profit 0.0%" in converted[0]["notes"][-1]    # no profit on the lounge line: a real difference to ask about


def test_reconcile_lists_what_has_no_partner():
    result = reconcile(V3, TODAY)
    assert any("Far Away" in x for x in result["reservations_without_quote_line"])
    assert any("No Reservation Ltd" in x for x in result["quote_lines_without_reservation"])


def test_two_lines_of_one_supplier_are_matched_by_product_name():
    rows = {r["order_id"]: r for r in reconcile(V3, TODAY)["rows"]}
    assert rows[1]["quote_line"] == "Hotel Uno" and rows[2]["quote_line"] == "Hotel Due"


def test_trip_without_a_quotation_reports_every_reservation_as_unmatched():
    v3 = {"trip": {"trip_id": 1}, "reservations": [_res(1, 1, "S", "P", 10, 1, 1, "2027-01-01")], "order_documents": []}
    result = reconcile(v3, TODAY)
    assert result["rows"] == [] and len(result["reservations_without_quote_line"]) == 1 and result["quotation"] is None


def test_trip_without_reservations_gives_empty_lists():
    result = reservations_summary({"trip": {"trip_id": 1}}, TODAY)
    assert result["reservations"] == [] and result["count"] == 0 and result["total_cost"] == 0


class FakeMYT:
    def __init__(self, v3, *, currencies=None, create_result=None, create_error=None, update_error=None,
                create_effect=None, update_effect=None):
        self.v3 = v3
        self.currencies = currencies or {"EUR": 3, "ILS": 1, "USD": 2}
        self.create_calls, self.update_calls, self.invalidate_calls = [], [], []
        self._create_result, self._create_error = create_result if create_result is not None else [999001], create_error
        self._update_error = update_error
        self._create_effect, self._update_effect = create_effect, update_effect   # optional: mutate self.v3 to simulate the write

    async def get_trip_v3(self, trip_id):
        return self.v3

    def invalidate_trip_cache(self, trip_id):
        self.invalidate_calls.append(trip_id)

    async def currency_code_id(self, code):
        code = code.strip().upper()
        if code not in self.currencies:
            raise MYTError(f"MYT's currency list has no code {code!r}.")
        return self.currencies[code]

    async def create_reservation(self, trip_id, products, *, external_id=None, comments=None):
        self.create_calls.append({"trip_id": trip_id, "products": products, "external_id": external_id, "comments": comments})
        if self._create_error:
            raise self._create_error
        if self._create_effect:
            self._create_effect(self.v3, products)
        return self._create_result

    async def update_reservation(self, order_doc_id, reservations, *, trip_id=None):
        self.update_calls.append({"order_doc_id": order_doc_id, "reservations": reservations})
        if self._update_error:
            raise self._update_error
        if self._update_effect:
            self._update_effect(self.v3, reservations)
        return order_doc_id

    async def aclose(self):
        pass


@pytest.mark.anyio
async def test_tools_read_the_allowed_trip_and_refuse_others():
    settings = Settings(allowed_trip_ids=frozenset({1001}))
    async with Client(create_server(settings, Services(settings, myt=FakeMYT(V3)))) as c:
        ok = await c.call_tool("get_supplier_reservations", {"trip_id": 1001})
        rec = await c.call_tool("reconcile_trip", {"trip_id": 1001})
        other = await c.call_tool("reconcile_trip", {"trip_id": 5})
        bad_days = await c.call_tool("get_supplier_reservations", {"trip_id": 1001, "soon_days": 400})
    assert not ok.is_error and "voucher_flags" in ok.content[0].text
    assert not rec.is_error and "MISMATCH" in rec.content[0].text
    assert other.is_error and "outside the allowed test trips" in other.content[0].text
    assert bad_days.is_error and "soon_days" in bad_days.content[0].text


def test_worklist_orders_by_urgency_and_gives_a_next_step():
    v3 = _v3(
        [
            _res(1, 10, "RateHawk", "Hotel Uno", 225.0, 1, 1, "2026-10-14"),      # started yesterday, not sent
            _res(2, 20, "Cooking Co", "Cooking workshop", 150.0, 2, 1, "2026-10-15"),  # today
            _res(3, 30, "Far Co", "Tour", 80.0, 1, 1, "2026-12-01"),                   # later
            _res(4, 40, "Done Co", "Hotel Due", 90.0, 1, 1, "2026-10-16"),            # voucher issued
            _res(5, 50, "Soon Co", "Dinner", 60.0, 1, 1, "2026-10-18"),               # in 3 days, confirmed
        ],
        {1: "NotSent", 2: "NotSent", 3: "NotSent", 4: "VoucherSent", 5: "ConfirmedByTo"},
        [],
    )
    out = reservations_summary(v3, TODAY, soon_days=7)
    by_id = {r["order_id"]: r for r in out["reservations"]}
    assert by_id[1]["urgency"] == "overdue" and by_id[1]["service_in_days"] == -1
    assert by_id[2]["urgency"] == "today"
    assert by_id[3]["urgency"] == "later"
    assert by_id[4]["urgency"] == "done"
    assert by_id[5]["urgency"] == "soon"
    assert [w["order_id"] for w in out["worklist"]] == [1, 2, 5, 3]          # the voucher-issued one is not on the list
    assert "Never Send Request" in by_id[1]["next_step"]
    assert "voucher" in by_id[5]["next_step"].lower()
    assert "payment" in by_id[4]["next_step"].lower()
    assert "API cannot show" in by_id[4]["next_step"] and "by status" in by_id[5]["next_step"]     # never claim an invoice or payment is missing: the API cannot see them


def test_statuses_seen_on_a_finished_trip_are_not_called_overdue():
    """Found on trip 435 (17 Oct 2026): Voucher Paid, Voucher In Payment Process and Rejected By Operator were all listed as overdue."""
    v3 = _v3(
        [_res(1, 10, "Paid Co", "Car", 212.71, 1, 1, "2026-09-21"),
         _res(2, 20, "Pay Co", "Car 2", 116.72, 1, 1, "2026-09-29"),
         _res(3, 30, "Rej Co", "Tour", 100.0, 1, 1, "2026-09-18"),
         _res(4, 40, "Rej Future Co", "Tour 2", 90.0, 1, 1, "2026-10-20")],
        {1: "VoucherPaid", 2: "VoucherInPayment", 3: "RejectedByTo", 4: "RejectedByTo"}, [])
    out = reservations_summary(v3, TODAY)
    by_id = {r["order_id"]: r for r in out["reservations"]}
    assert (by_id[1]["status"], by_id[1]["urgency"]) == ("Voucher Paid", "done") and "PAYMENTS tab" in by_id[1]["next_step"]
    assert by_id[2]["status"] == "Voucher In Payment Process" and by_id[2]["urgency"] == "overdue" and "Payment is in process" in by_id[2]["next_step"]
    assert (by_id[3]["status"], by_id[3]["urgency"]) == ("Rejected By Operator", "done")            # past and rejected: closed
    assert by_id[4]["urgency"] == "soon" and "re-request" in by_id[4]["next_step"]                     # future and rejected: surfaced
    assert [w["order_id"] for w in out["worklist"]] == [2, 4]


def test_totals_never_add_two_currencies():
    eur = _res(1, 10, "A", "Hotel", 100.0, 1, 1, "2026-10-20")
    ils = {**_res(2, 20, "B", "Tour", 1000.0, 1, 1, "2026-10-21"), "currency": {"name": "ILS"}}
    out = reservations_summary(_v3([eur, ils], {1: "NotSent", 2: "NotSent"}, []), TODAY)
    assert out["total_cost"] is None and out["total_cost_by_currency"] == {"EUR": 100.0, "ILS": 1000.0}
    assert out["count"] == 2 and out["orders"] == 2
    one = reservations_summary(_v3([eur], {1: "NotSent"}, []), TODAY)
    assert one["total_cost"] == 100.0 and one["total_cost_by_currency"] == {"EUR": 100.0}


def test_customer_invoices_from_the_trip_payload():
    """Shape seen on trip 435 (17 Oct 2026): a pro forma with 9 installments (600 + 8 x 4,212.25 = 34,298) and a single-payment add-on."""
    def day(iso):
        return {"date": f"{iso}T00:00:00", "string": iso}
    v3 = {"invoices": [
        {"invoice_id": 1, "invoice_number": 243, "description": "", "is_proforma": True, "total": {"amount": 34298.0}, "document_date": day("2026-02-01"),
         "payable_until": day("2026-01-28"), "installments": [{"amount": {"amount": 600.0, "string": "600.00"}, "currency": {"name": "ILS"}, "date": day("2026-01-06")}] + [{"amount": {"amount": 4212.25, "string": "4,212.25"}, "currency": {"name": "ILS"}, "date": day(f"2026-{m:02d}-26")} for m in range(1, 9)]},
        {"invoice_id": 2, "invoice_number": 271, "description": "Add on", "is_proforma": True, "total": {"amount": 1035.0}, "document_date": day("2026-05-18"), "payable_until": day("2026-05-18")},
    ]}
    from myt_mcp.myt.reservations import customer_invoices
    out = customer_invoices(v3)
    first, second = out["invoices"]
    assert out["count"] == 2 and out["total_of_invoices"] == 35333.0 and "Paid status" in out["not_in_api"]
    assert first["currency"] == "ILS" and first["installments"][0]["date"] == "2026-01-06"
    assert first["type"] == "pro forma" and first["installments_total"] == 34298.0 and first["installments_match_total"] is True and len(first["installments"]) == 9
    assert second["installments"] == [] and second["installments_match_total"] is None and second["description"] == "Add on"
    assert customer_invoices({})["invoices"] == []


# ---------- writing a reservation (reservations/Create and /Update) ----------

def _create_adds_reservation(v3, products, supplier_kind=None):
    p = products[0]
    kind = supplier_kind or {1: "transportation", 4: "lodging", 5: "attraction", 7: "dmc"}[p["TypeId"]]      # a supplier whose type matches the product
    v3["reservations"].append({"order_id": 500100, "reservation_id": 500200, "supplier_id": p["SupplierId"], "supplier_type": {kind: True},
                               "supplier_name": "Test Supplier", "product_name": p["Name"], "quantity": p["Quantity"],
                               "duration": p["Nights"], "price": {"amount": p["Price"]}, "currency": {"name": "EUR"},
                               "dates": {"start": _d(p["StartDate"])}})


def _update_changes_price(v3, reservations):
    row = reservations[0]
    for r in v3["reservations"]:
        if r["reservation_id"] == row["OrderReservationId"]:
            r["price"]["amount"] = row["Price"]
            r["quantity"] = row["Quantity"]
            r["duration"] = row["Duration"]


async def create_server_for(myt, settings=None):
    settings = settings or Settings(allowed_trip_ids=frozenset({1001}))
    return create_server(settings, Services(settings, myt=myt))


@pytest.mark.anyio
async def test_create_without_confirm_only_previews():
    myt = FakeMYT(_v3([], {}, []), create_effect=_create_adds_reservation)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 101768, "product_name": "Test transfer",
                                                               "start_date": "2027-03-01", "price": 50.0, "currency": "EUR"})
    d = r.structured_content
    assert not r.is_error and d["sent"] is False and myt.create_calls == [] and "confirm=true" in d["note"]
    assert d["product"]["Name"] == "Test transfer" and d["product"]["TypeId"] == 1 and d["product"]["PricingTypeId"] == 1
    assert d["product"]["CurrencyCodeId"] == 3


@pytest.mark.anyio
async def test_create_with_confirm_sends_and_reads_back():
    myt = FakeMYT(_v3([], {}, []), create_effect=_create_adds_reservation)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 101768, "product_name": "Test transfer",
                                                               "start_date": "2027-03-01", "price": 50.0, "pricing": "PP", "confirm": True})
    d = r.structured_content
    assert not r.is_error and d["sent"] is True and d["order_id"] == 500100 and d["reservation_id"] == 500200
    assert len(myt.create_calls) == 1 and myt.create_calls[0]["products"][0]["PricingTypeId"] == 2
    assert myt.create_calls[0]["products"][0]["Name"].startswith("Test transfer [") and d["confirmed_by_reading_the_trip_back"] is True


@pytest.mark.anyio
async def test_create_refuses_a_category_that_is_not_verified():
    r = (await create_and_call("create_supplier_reservation", trip_id=1001, supplier_id=1, product_name="x",
                               start_date="2027-03-01", price=10.0, category="Food"))
    assert r.is_error and "Transport" in r.content[0].text and "Lodging" in r.content[0].text and "SUPPLIER's type" in r.content[0].text


@pytest.mark.anyio
async def test_create_lodging_uses_type_id_4_and_reads_back_a_lodging_supplier():
    myt = FakeMYT(_v3([], {}, []), create_effect=_create_adds_reservation)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 102638, "product_name": "Hotel Vincci Liberdade",
                                                               "start_date": "2027-03-06", "price": 348.5, "nights": 2, "category": "Lodging", "confirm": True})
    assert not r.is_error and r.structured_content["sent"] is True
    assert myt.create_calls[0]["products"][0]["TypeId"] == 4 and myt.create_calls[0]["products"][0]["Nights"] == 2


@pytest.mark.anyio
async def test_create_lodging_with_a_supplier_of_another_type_is_refused():
    myt = FakeMYT(_v3([], {}, []), create_effect=lambda v3, products: _create_adds_reservation(v3, products, supplier_kind="transportation"))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 98182, "product_name": "Hotel X",
                                                               "start_date": "2027-03-06", "price": 100.0, "category": "Lodging", "confirm": True})
    assert r.is_error and "not a lodging supplier" in r.content[0].text


async def create_and_call(name, **args):
    myt = FakeMYT(_v3([], {}, []))
    async with Client(await create_server_for(myt)) as c:
        return await c.call_tool(name, args)


@pytest.mark.parametrize("extra,expected", [
    ({"pricing": "XX"}, "pricing"), ({"price": 0}, "price"), ({"quantity": 0}, "quantity"), ({"nights": 0}, "nights"),
    ({"start_date": "2020-01-01"}, "past"), ({"arrival_time": "25:99"}, "arrival_time"), ({"product_name": "  "}, "product_name"),
])
@pytest.mark.anyio
async def test_create_validates_input(extra, expected):
    base = {"trip_id": 1001, "supplier_id": 1, "product_name": "Test", "start_date": "2027-03-01", "price": 10.0}
    r = await create_and_call("create_supplier_reservation", **{**base, **extra})
    assert r.is_error and expected in r.content[0].text


@pytest.mark.anyio
async def test_create_reports_when_myt_silently_drops_it():
    myt = FakeMYT(_v3([], {}, []))     # no create_effect: the reservation never appears on read-back
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 1, "product_name": "Ghost",
                                                               "start_date": "2027-03-01", "price": 10.0, "confirm": True})
    assert r.is_error and "NOT visible" in r.content[0].text


@pytest.mark.anyio
async def test_create_rejects_an_unknown_currency():
    r = await create_and_call("create_supplier_reservation", trip_id=1001, supplier_id=1, product_name="Test",
                              start_date="2027-03-01", price=10.0, currency="XYZ")
    assert r.is_error and "XYZ" in r.content[0].text


def _fresh_transfer_v3():
    return _v3([_res(1, 10, "Lisbon Airport Transfers", "Old transfer", 80.0, 1, 1, "2027-03-05")], {1: "NotSent"}, [])


@pytest.mark.anyio
async def test_update_without_confirm_previews_with_current_values():
    myt = FakeMYT(_fresh_transfer_v3())
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("update_supplier_reservation", {"trip_id": 1001, "order_id": 1, "reservation_id": 2, "price": 95.0})
    d = r.structured_content
    assert not r.is_error and d["sent"] is False and myt.update_calls == []
    assert d["current"] == {"price": 80.0, "quantity": 1, "nights": 1, "start": "2027-03-05"}
    assert d["sending"] == {"OrderReservationId": 2, "ReservationDate": "2027-03-05", "Quantity": 1, "Duration": 1,
                            "Price": 95.0, "ArrivalTime": "10:00", "Comments": "", "IsActive": True}


@pytest.mark.anyio
async def test_update_with_confirm_sends_full_row_and_confirms():
    myt = FakeMYT(_fresh_transfer_v3(), update_effect=_update_changes_price)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("update_supplier_reservation", {"trip_id": 1001, "order_id": 1, "reservation_id": 2, "price": 95.0, "confirm": True})
    d = r.structured_content
    assert not r.is_error and d["sent"] is True and d["new"]["price"] == 95.0 and d["confirmed_by_reading_the_trip_back"] is True
    sent = myt.update_calls[0]["reservations"][0]
    assert sent["ReservationDate"] == "2027-03-05" and sent["Quantity"] == 1 and sent["Price"] == 95.0   # unchanged fields carried over


@pytest.mark.anyio
async def test_update_unknown_reservation_is_refused():
    myt = FakeMYT(_fresh_transfer_v3())
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("update_supplier_reservation", {"trip_id": 1001, "order_id": 1, "reservation_id": 999, "price": 10.0})
    assert r.is_error and "No reservation 999" in r.content[0].text


@pytest.mark.anyio
async def test_update_reports_when_myt_silently_fails_to_apply_it():
    myt = FakeMYT(_fresh_transfer_v3())   # no update_effect: price never changes
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("update_supplier_reservation", {"trip_id": 1001, "order_id": 1, "reservation_id": 2, "price": 95.0, "confirm": True})
    assert r.is_error and "does not read back" in r.content[0].text


@pytest.mark.anyio
async def test_write_tools_refuse_a_trip_outside_the_allowed_list():
    myt = FakeMYT(_v3([], {}, []))
    async with Client(await create_server_for(myt)) as c:
        create = await c.call_tool("create_supplier_reservation", {"trip_id": 5, "supplier_id": 1, "product_name": "x",
                                                                    "start_date": "2027-03-01", "price": 10.0})
        update = await c.call_tool("update_supplier_reservation", {"trip_id": 5, "order_id": 1, "reservation_id": 2, "price": 10.0})
    assert create.is_error and "outside the allowed test trips" in create.content[0].text
    assert update.is_error and "outside the allowed test trips" in update.content[0].text


# ---------- fresh=true: force a live read past the write-they-did-not-make cache gap ----------

@pytest.mark.anyio
@pytest.mark.parametrize("tool,args", [
    ("get_supplier_reservations", {"trip_id": 1001}),
    ("get_customer_invoices", {"trip_id": 1001}),
    ("reconcile_trip", {"trip_id": 1001}),
    ("get_quotation", {"trip_id": 1001}),
    ("get_trip", {"trip_id": 1001}),
])
async def test_fresh_true_invalidates_the_cache_first(tool, args):
    myt = FakeMYT(_v3([], {}, []))
    async with Client(await create_server_for(myt)) as c:
        without = await c.call_tool(tool, args)
        with_fresh = await c.call_tool(tool, {**args, "fresh": True})
    assert not without.is_error and not with_fresh.is_error
    assert myt.invalidate_calls == [1001]       # only the fresh=true call invalidated the cache


@pytest.mark.anyio
async def test_check_reservation_paperwork_fresh_true_invalidates_the_cache():
    myt = FakeMYT(_v3([], {}, []))
    async with Client(await create_server_for(myt)) as c:
        await c.call_tool("check_reservation_paperwork", {"trip_id": 1001})
        await c.call_tool("check_reservation_paperwork", {"trip_id": 1001, "fresh": True})
    assert myt.invalidate_calls == [1001]


@pytest.mark.anyio
async def test_create_attraction_uses_type_id_5_and_reads_back_an_attraction_supplier():
    myt = FakeMYT(_v3([], {}, []), create_effect=_create_adds_reservation)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 114469, "product_name": "Arouca Bridge tour",
                                                               "start_date": "2027-03-03", "price": 92.0, "category": "Attraction", "confirm": True})
    assert not r.is_error and r.structured_content["sent"] is True and myt.create_calls[0]["products"][0]["TypeId"] == 5


@pytest.mark.anyio
async def test_create_dmc_uses_type_id_7_and_reads_back_a_dmc_supplier():
    myt = FakeMYT(_v3([], {}, []), create_effect=_create_adds_reservation)
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 85936, "product_name": "Private transfer",
                                                               "start_date": "2027-03-01", "price": 81.0, "category": "DMC", "confirm": True})
    assert not r.is_error and r.structured_content["sent"] is True and myt.create_calls[0]["products"][0]["TypeId"] == 7


@pytest.mark.anyio
async def test_create_transport_under_a_dmc_supplier_is_accepted():
    myt = FakeMYT(_v3([], {}, []), create_effect=lambda v3, products: _create_adds_reservation(v3, products, supplier_kind="dmc"))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 85936, "product_name": "Transfer FCO to hotel",
                                                               "start_date": "2027-03-01", "price": 81.0, "category": "Transport", "confirm": True})
    assert not r.is_error and r.structured_content["sent"] is True and myt.create_calls[0]["products"][0]["TypeId"] == 1


@pytest.mark.anyio
async def test_create_attraction_under_a_dmc_supplier_is_accepted():
    myt = FakeMYT(_v3([], {}, []), create_effect=lambda v3, products: _create_adds_reservation(v3, products, supplier_kind="dmc"))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("create_supplier_reservation", {"trip_id": 1001, "supplier_id": 48039, "product_name": "Vatican tour",
                                                               "start_date": "2027-03-03", "price": 227.0, "category": "Attraction", "confirm": True})
    assert not r.is_error and r.structured_content["sent"] is True and myt.create_calls[0]["products"][0]["TypeId"] == 5


# ---------- supplier directory ----------

async def call_with(tool, args):
    async with Client(await create_server_for(FakeMYT(_v3([], {}, [])))) as c:
        return await c.call_tool(tool, args)


@pytest.mark.anyio
async def test_find_supplier_returns_id_type_and_the_categories_it_fits():
    r = await call_with("find_supplier", {"name": "arbitrip"})
    d = r.structured_content
    assert not r.is_error and d["matches"][0]["id"] == 102638 and d["matches"][0]["type"] == "lodging"
    assert d["matches"][0]["fits_categories"] == ["Lodging"]
    d = (await call_with("find_supplier", {"name": "ratehawk"})).structured_content
    assert d["matches"][0]["id"] == 85936 and d["matches"][0]["fits_categories"] == ["Transport", "Attraction", "DMC"]


@pytest.mark.anyio
async def test_find_supplier_keeps_only_suppliers_that_fit_the_category_and_never_guesses():
    assert (await call_with("find_supplier", {"name": "sixt", "category": "Lodging"})).structured_content["matches"] == []
    d = (await call_with("find_supplier", {"name": "sixt", "category": "Transport"})).structured_content
    assert d["matches"][0]["id"] == 98182
    d = (await call_with("find_supplier", {"name": "zzz unknown hotel"})).structured_content
    assert d["matches"] == [] and "do not guess" in d["note"]


@pytest.mark.anyio
async def test_find_supplier_flags_a_supplier_whose_type_was_never_confirmed():
    d = (await call_with("find_supplier", {"name": "lisbon airport transfers"})).structured_content
    assert d["matches"][0]["id"] == 101768 and d["matches"][0]["type_known"] is False and "type_known=false" in d["note"]


# ---------- plan_supplier_reservations ----------

def _counting_effect(supplier_kinds, drop=()):
    """Create effect that gives each product its own reservation id and the supplier type from the supplier id; `drop` ids vanish silently."""
    counter = {"n": 0}

    def effect(v3, products):
        for p in products:
            if p["SupplierId"] in drop:
                continue
            counter["n"] += 1
            v3["reservations"].append({"order_id": 700000 + (p["SupplierId"] % 1000), "reservation_id": 800000 + counter["n"], "supplier_id": p["SupplierId"],
                                       "supplier_type": {supplier_kinds[p["SupplierId"]]: True}, "supplier_name": "S", "product_name": p["Name"],
                                       "quantity": p["Quantity"], "duration": p["Nights"], "price": {"amount": p["Price"]}, "currency": {"name": "EUR"},
                                       "dates": {"start": _d(p["StartDate"])}})
    return effect


KINDS = {102638: "lodging", 85936: "dmc", 98182: "transportation"}
PLAN = [
    {"supplier": "Arbitrip", "category": "Lodging", "product_name": "Hotel Vincci Liberdade - Triple Superior", "start_date": "2027-03-06", "price": 348.5, "nights": 2},
    {"supplier": "Arbitrip", "category": "Lodging", "product_name": "Terra Nostra Garden Hotel", "start_date": "2027-03-08", "price": 245.33, "nights": 3},
    {"supplier": "RateHawk", "category": "Transport", "product_name": "Transfer FCO airport - Room Mate Mia", "start_date": "2027-03-01", "price": 81.0},
]


@pytest.mark.anyio
async def test_plan_groups_by_supplier_totals_per_currency_and_sends_nothing_without_confirm():
    myt = FakeMYT(_v3([], {}, []), create_effect=_counting_effect(KINDS))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": PLAN})
    d = r.structured_content
    assert not r.is_error and d["sent"] is False and myt.create_calls == [] and d["problems"] == []
    by = {o["supplier"]: o for o in d["orders"]}
    assert len(d["orders"]) == 2 and len(by["Arbitrip"]["products"]) == 2 and by["Arbitrip"]["totals"] == {"EUR": round(348.5 * 2 + 245.33 * 3, 2)}
    assert d["total_by_currency"] == {"EUR": round(697 + 735.99 + 81, 2)} and d["reservations"] == 3


@pytest.mark.anyio
async def test_plan_with_confirm_creates_every_product_and_reads_the_trip_back_once():
    myt = FakeMYT(_v3([], {}, []), create_effect=_counting_effect(KINDS))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": PLAN, "confirm": True})
    d = r.structured_content
    assert not r.is_error and d["sent"] is True and len(d["created"]) == 3 and d["all_supplier_types_ok"] is True
    assert [p["products"][0]["TypeId"] for p in myt.create_calls] == [4, 4, 1] and len({x["reservation_id"] for x in d["created"]}) == 3
    assert not any("[" in p["products"][0]["Name"] for p in myt.create_calls)      # real names, no test tag


@pytest.mark.anyio
async def test_plan_refuses_an_unknown_supplier_a_wrong_category_and_a_past_date_and_sends_nothing():
    lines = [{"supplier": "Hotel That Is Not In MYT", "category": "Lodging", "product_name": "x", "start_date": "2027-03-06", "price": 100},
             {"supplier": "Sixt", "category": "Lodging", "product_name": "y", "start_date": "2027-03-06", "price": 100},
             {"supplier": "Arbitrip", "category": "Lodging", "product_name": "z", "start_date": "2020-01-01", "price": 100}]
    myt = FakeMYT(_v3([], {}, []), create_effect=_counting_effect(KINDS))
    async with Client(await create_server_for(myt)) as c:
        preview = (await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": lines})).structured_content
        r = await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": lines, "confirm": True})
    text = " ".join(preview["problems"])
    assert "no supplier called" in text and "none of which fits category Lodging" in text and "in the past" in text
    assert r.is_error and "Nothing was sent" in r.content[0].text and myt.create_calls == []


@pytest.mark.anyio
async def test_plan_refuses_a_reservation_that_already_exists_and_a_duplicate_line():
    existing = _res(2353695, 102638, "Arbitrip", "Terra Nostra Garden Hotel", 245.33, 1, 3, "2027-03-08")
    lines = [PLAN[1], PLAN[0], PLAN[0]]
    myt = FakeMYT(_v3([existing], {}, []), create_effect=_counting_effect(KINDS))
    async with Client(await create_server_for(myt)) as c:
        d = (await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": lines})).structured_content
    text = " ".join(d["problems"])
    assert "already exists (order 2353695" in text and "appear twice" in text


@pytest.mark.anyio
async def test_plan_reports_a_product_that_mYT_silently_dropped_and_names_what_was_created():
    myt = FakeMYT(_v3([], {}, []), create_effect=_counting_effect(KINDS, drop={85936}))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": PLAN, "confirm": True})
    text = r.content[0].text
    assert r.is_error and "NOT visible" in text and "RateHawk" in text and "line 1 order" in text and "never resend" in text


@pytest.mark.anyio
async def test_plan_stops_at_the_first_failed_write():
    myt = FakeMYT(_v3([], {}, []), create_error=MYTError("MYT said no"))
    async with Client(await create_server_for(myt)) as c:
        r = await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": PLAN, "confirm": True})
    assert r.is_error and "MYT refused line 1" in r.content[0].text and len(myt.create_calls) == 1


@pytest.mark.anyio
async def test_plan_limits_the_number_of_lines():
    lines = [{**PLAN[2], "product_name": f"Transfer {i}"} for i in range(13)]
    async with Client(await create_server_for(FakeMYT(_v3([], {}, [])))) as c:
        d = (await c.call_tool("plan_supplier_reservations", {"trip_id": 1001, "lines": lines})).structured_content
    assert any("at most 12" in p for p in d["problems"])

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

def _create_adds_reservation(v3, products):
    p = products[0]
    v3["reservations"].append({"order_id": 500100, "reservation_id": 500200, "supplier_id": p["SupplierId"],
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
async def test_create_refuses_a_category_other_than_transport():
    r = (await create_and_call("create_supplier_reservation", trip_id=1001, supplier_id=1, product_name="x",
                               start_date="2027-03-01", price=10.0, category="Lodging"))
    assert r.is_error and "Transport" in r.content[0].text and "silently drop" in r.content[0].text


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

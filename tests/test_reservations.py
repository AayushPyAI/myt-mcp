"""Supplier reservations, voucher flags and reconciliation. The payload is synthetic and shaped like GetTrip/v3
(no client data): reservations carry a unit price, quantity and duration; order_documents carry the status."""

from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
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
    def __init__(self, v3):
        self.v3 = v3

    async def get_trip_v3(self, trip_id):
        return self.v3

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

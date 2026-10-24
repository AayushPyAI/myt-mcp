"""MYT read tools for supplier reservations: statuses, voucher flags and the reservation-vs-quote reconciliation."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field, field_validator
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.myt import supplier_directory
from myt_mcp.myt.paperwork import paperwork_check
from myt_mcp.myt.reservation_plan import build_plan
from myt_mcp.myt.summaries import _amount, _date
from myt_mcp.myt.reservations import (CATEGORY_NOTE, KNOWN_CREATE_CATEGORIES, SUPPLIER_KIND, _key, build_create_product, build_update_row,
                                      customer_invoices, find_reservation, reconcile, reservations_summary)
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
WRITE_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def _today() -> date:
    return date.today()


class ScreenDoc(BaseModel):
    """One row read from a MYT screen (a voucher, a supplier invoice or a supplier payment)."""

    order_id: int | None = Field(default=None, description="The order id as the screen shows it (R2342258 or 2342258) when the row shows it; best way to match")
    supplier: str | None = Field(default=None, description="Supplier name as the row shows it")
    number: str | None = Field(default=None, description="Voucher or invoice number, e.g. V2324")
    amount: float | None = Field(default=None, description="Amount on the row")
    currency: str | None = Field(default=None, description="EUR, ILS or USD")

    @field_validator("order_id", mode="before")
    @classmethod
    def _order_id_from_screen(cls, value: Any) -> Any:
        """The screen writes the order id as "R2342258"; accept that form as well as the bare number."""
        if isinstance(value, str):
            digits = value.strip().lstrip("Rr").strip()
            if digits.isdigit():
                return int(digits)
        return value


class PlanLine(BaseModel):
    """One supplier reservation the operator has approved."""

    supplier: str = Field(description="Supplier name as MYT knows it, e.g. 'Arbitrip', 'RateHawk', 'Sixt' (find_supplier shows the matches)")
    category: Literal["Transport", "Lodging", "Attraction", "DMC"] = Field(
        description="Transport (flight, train, transfer, car; also a RateHawk transfer), Lodging (hotel; Arbitrip), Attraction (tour, ticket; also a Get your guide tour). Not DMC.")
    product_name: str = Field(description="What is booked, e.g. 'Hotel Vincci Liberdade - Triple Superior Room, breakfast'")
    start_date: date
    price: float = Field(description="NET price per unit (per night for a hotel). Never add profit: it belongs to the quote")
    quantity: float = Field(default=1, description="Rooms, vehicles or travellers (with pricing PP)")
    nights: int = Field(default=1, description="Nights for a hotel, days for a car, else 1")
    pricing: Literal["PS", "PP"] = Field(default="PS", description="PS: the price covers the whole booking; PP: per person")
    currency: str = "EUR"
    supplier_id: int | None = Field(default=None, description="Only when the name matches several suppliers (from find_supplier)")
    arrival_time: str | None = Field(default=None, description="HH:MM, 24-hour")
    comments: str | None = None


def register(mcp: MCPServer, services: Services) -> None:
    async def trip_v3(trip_id: int, fresh: bool = False) -> dict[str, Any]:
        services.check_trip(trip_id)
        if fresh:
            services.myt().invalidate_trip_cache(trip_id)
        v3 = await services.myt().get_trip_v3(trip_id)
        got = (v3.get("trip") or {}).get("trip_id")
        ensure("MYT", [] if got == trip_id else [f"MYT returned trip {got} instead of {trip_id}"])
        return v3

    def check_days(soon_days: int) -> None:
        if not 0 <= soon_days <= 60:
            raise ToolError("soon_days must be between 0 and 60.")

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def get_supplier_reservations(trip_id: int, soon_days: int = 7, fresh: bool = False) -> Any:
        """Supplier reservations of a trip, by trip_id (from find_trip; NOT the trip number) (הזמנות ספקים, שוברים): every
        reservation with supplier, product, dates, quantity, the cost the MYT screen shows and the supplier order's
        STATUS (Ready To Send, Voucher Issued, Reservation Confirmed), plus `voucher_flags`: orders whose voucher is
        not sent although the service starts within `soon_days` days. Voucher numbers, supplier invoices and payments
        are not in the API (see not_in_api). Pass fresh=true right after a status move made via Claude in Chrome (Skip To
        COR, Print Voucher...): a read within 60 seconds of a screen change can still show the old status. Read only."""
        check_days(soon_days)
        return reservations_summary(await trip_v3(trip_id, fresh), date.today(), soon_days)

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def get_customer_invoices(trip_id: int, fresh: bool = False) -> Any:
        """The customer's invoices of a trip (חשבוניות פרופורמה, לקוח), by trip_id: pro forma or tax invoice number, total, document date, payable-until
        date and the payment schedule (installments with dates and amounts, and whether they add up to the total). The API does not give the paid
        status or the currency: read them on the MYT screen (Balance by trip > Customer invoice, trip filtered). Read only. Never copy the customer's name."""
        return customer_invoices(await trip_v3(trip_id, fresh))

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def reconcile_trip(trip_id: int, soon_days: int = 7, fresh: bool = False) -> Any:
        """Reconciliation of a trip (התאמה): each supplier reservation against its line in the selected quotation. Shows
        per reservation: cost, quote line total, the profit the quote adds (3%, 13% or 15% is normal), and a verdict
        (ok / MISMATCH, also when the dates differ); reservations with no quote line, quote lines with no reservation,
        and voucher flags. Pass fresh=true right after a quote-line or reservation change made via Claude in Chrome, to
        force a live read instead of one that may still show the pre-change data (the cache lasts 60 seconds). Read only:
        it changes nothing in MYT. Report mismatches; do not fix them without the operator's approval."""
        check_days(soon_days)
        return reconcile(await trip_v3(trip_id, fresh), date.today(), soon_days)

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def find_supplier(name: str, category: str | None = None) -> dict[str, Any]:
        """Find a MYT supplier id by name BEFORE creating a reservation or a quote line. Reads only a local directory of suppliers seen
        on real trips (id, type, subtype, the categories it fits); it calls nothing on MYT. `name` can be a word or two ("arbitrip",
        "ratehawk", "sixt"); `category` ("Transport", "Lodging", "Attraction", "DMC") keeps only suppliers that fit it. A supplier that
        is not listed is NOT guessed and never created: ask the operator for the exact name used in MYT, or read it on the MYT screen."""
        want = SUPPLIER_KIND.get(category) if category else None
        if category and not want:
            raise ToolError(f"category must be one of {', '.join(SUPPLIER_KIND)}.")
        found = supplier_directory.find_suppliers(name)
        rows = []
        for s in found:
            fits = [c for c, kinds in SUPPLIER_KIND.items() if s.get("type") in kinds]
            if want and s.get("type") is not None and s["type"] not in want:
                continue
            rows.append({"id": s["id"], "name": s["name"], "private_name": s.get("private_name"), "type": s.get("type"), "subtype": s.get("subtype"),
                         "fits_categories": fits or None, "type_known": s.get("type") is not None, "seen_on_trips": s.get("trips")})
        note = ("Not in the directory: do not guess an id. Ask the operator for the supplier's exact name in MYT or read it on the MYT screen; "
                "never create a supplier." if not rows else
                "type_known=false: the supplier was seen on a quote line only, so its type (and which category fits) is not confirmed; "
                "check it on the MYT screen before creating a reservation." if any(not r["type_known"] for r in rows) else
                "Use the id of the supplier whose type fits the category.")
        return {"query": name, "category": category, "matches": rows, "directory_size": len(supplier_directory.load()), "note": note}

    @mcp.tool(annotations=WRITE)
    @tool_errors
    @with_checked_at
    async def plan_supplier_reservations(trip_id: int, lines: list[PlanLine], confirm: bool = False) -> dict[str, Any]:
        """Plan (and, after the operator's yes, create) the supplier reservations of a trip. Reservations come BEFORE the quote: the operator
        approves the lines (supplier, product, date, quantity, NET price), the reservations are created, and the quote is made from them.
        Without confirm=True nothing is sent: it shows the plan grouped by supplier (MYT puts one supplier's products into one order),
        totals per currency, `problems` (unknown or ambiguous supplier, category that does not fit the supplier's type, past date, a
        reservation that already exists, more than 12 lines) and `warnings`. Show it to the operator and wait for a clear yes.
        With confirm=True and no problems it creates the products one by one, then reads the trip back ONCE and reports the order id
        and reservation id of each, or an error naming the ones that are missing. Test trips only unless the operator names another trip.
        It never creates a supplier, never sends a request to a supplier (status stays Ready To Send) and never deletes anything.
        Categories: see PlanLine; the supplier's type decides what MYT keeps, so use find_supplier for the id and type first."""
        services.check_trip(trip_id)
        before = await trip_v3(trip_id, fresh=True)
        plan = build_plan([line.model_dump() for line in lines], before.get("reservations") or [], _today())
        base = {"trip_id": trip_id, **plan}
        if not confirm:
            return {**base, "sent": False,
                    "note": "Nothing was sent. Show this plan to the operator; call again with the same lines and confirm=true only after their explicit yes."}
        if plan["problems"]:
            raise ToolError("Nothing was sent. Fix these first: " + "; ".join(plan["problems"]))
        myt = services.myt()
        known_ids = {r.get("reservation_id") for r in before.get("reservations") or []}     # taken before anything is sent
        sent, failed = [], None
        for order in plan["orders"]:
            for p in order["products"]:
                tag = uuid.uuid4().hex[:10]
                product = build_create_product(
                    supplier_id=order["supplier_id"], start_date=p["start_date"], name=p["product"], price=p["unit_price"],
                    currency_code_id=await myt.currency_code_id(p["currency"]), pricing_type_id=1 if p["pricing"] == "PS" else 2,
                    type_id=KNOWN_CREATE_CATEGORIES[p["category"]], quantity=p["quantity"], nights=p["nights"],
                    arrival_time=p["arrival_time"] or "10:00", comments=p["comments"] or "")
                try:
                    await myt.create_reservation(trip_id, [product], external_id=f"claude-{tag}", comments=p["comments"])
                except Exception as e:      # stop at the first failure: never keep writing after an error
                    failed = f"line {p['line']} ({order['supplier']} / {p['product']}): {e}"
                    break
                sent.append((order, p))
            if failed:
                break
        after = await trip_v3(trip_id, fresh=True)
        taken: set[Any] = set()
        results, missing = [], []
        for order, p in sent:
            hit = next((r for r in after.get("reservations") or []
                        if r.get("reservation_id") not in known_ids | taken and r.get("supplier_id") == order["supplier_id"]
                        and _key(r.get("product_name")) == _key(p["product"])
                        and ((r.get("dates") or {}).get("start") or {}).get("date", "")[:10] == p["start_date"]), None)
            if not hit:
                missing.append(f"line {p['line']} ({order['supplier']} / {p['product']})")
                continue
            taken.add(hit["reservation_id"])
            kinds = SUPPLIER_KIND[p["category"]]
            results.append({"line": p["line"], "order_id": hit["order_id"], "reservation_id": hit["reservation_id"], "supplier": order["supplier"],
                            "product": p["product"], "supplier_type_ok": any((hit.get("supplier_type") or {}).get(k) for k in kinds)})
        if failed or missing:
            raise ToolError(("MYT refused " + failed + ". " if failed else "") + ("Created and confirmed: " + (", ".join(
                f"line {r['line']} order {r['order_id']}" for r in results) or "nothing") + ". ") +
                (("NOT visible when the trip is read back (MYT may have silently dropped them): " + "; ".join(missing) + ". ") if missing else "") +
                "Nothing more was sent. Tell the operator before trying again; never resend a line that is listed as created.")
        return {**base, "sent": True, "created": results, "all_supplier_types_ok": all(r["supplier_type_ok"] for r in results),
                "next_step": "Status starts at Ready To Send; confirm or voucher it on the MYT screen (never Send Request: it emails the supplier). "
                             "Then the quote is made from these reservations."}

    @mcp.tool(annotations=WRITE)
    @tool_errors
    @with_checked_at
    async def create_supplier_reservation(
        trip_id: int, supplier_id: int, product_name: str, start_date: date, price: float, currency: str = "EUR",
        pricing: str = "PS", quantity: float = 1, nights: int = 1, arrival_time: str | None = None,
        comments: str | None = None, category: str = "Transport", confirm: bool = False,
    ) -> dict[str, Any]:
        """Create ONE supplier reservation (a supplier order) on a trip through MYT's write API (reservations/Create): the
        object the Supplier Reservations screen shows, separate from the quotation's cost lines (writing a quote line is a
        different, UI-only flow). category is "Transport" (flights, trains, transfers, car rental; supplier of type transportation, or a DMC supplier such as RateHawk for its transfers) or
        "Lodging" (hotels; supplier of type lodging such as Arbitrip) or "Attraction" (tours, tickets; supplier of type attraction, or a DMC supplier such as Get your guide for its tours) or "DMC" (supplier of type dmc, e.g. RateHawk). The supplier's type must match the category, or MYT answers 200 and silently drops the product
        (this tool then refuses the result). Other categories are refused here; use Claude in Chrome for them.
        `supplier_id` must be an existing MYT supplier id (from this trip's suppliers or quotation); never invent one.
        `pricing` is "PS" (the price covers the whole booking) or "PP" (per person; MYT multiplies by travellers).
        Without confirm=True this only shows exactly what would be sent and changes nothing: show it to the operator first.
        With confirm=True, after the operator's explicit yes, it sends the write, reads the trip back, and reports the new
        order id and reservation id, or an error if MYT did not actually create it (MYT can answer success while silently
        dropping a product it does not support). If ALLOWED_TRIP_IDS lists trips only those can be touched; when it is empty, any trip the operator names. The new order starts as
        "Ready To Send" like any manual reservation; moving its status on is a separate, screen-only action."""
        services.check_trip(trip_id)
        if category not in KNOWN_CREATE_CATEGORIES:
            raise ToolError(f"category must be {', '.join(KNOWN_CREATE_CATEGORIES)!r} for now. {CATEGORY_NOTE}")
        if pricing not in ("PS", "PP"):
            raise ToolError("pricing must be 'PS' (the price covers the whole booking) or 'PP' (per person).")
        if price <= 0:
            raise ToolError("price must be more than 0.")
        if quantity <= 0 or nights <= 0:
            raise ToolError("quantity and nights must be more than 0.")
        if start_date < _today():
            raise ToolError("start_date is in the past.")
        if arrival_time and not TIME_RE.fullmatch(arrival_time):
            raise ToolError("arrival_time must be 24-hour HH:MM.")
        if not product_name.strip():
            raise ToolError("product_name is empty.")
        tag = uuid.uuid4().hex[:10]
        tagged_name = f"{product_name.strip()} [{tag}]"
        currency_code_id = await services.myt().currency_code_id(currency)
        product = build_create_product(supplier_id=supplier_id, start_date=start_date.isoformat(), name=tagged_name, price=price,
                                       currency_code_id=currency_code_id, pricing_type_id=1 if pricing == "PS" else 2,
                                       type_id=KNOWN_CREATE_CATEGORIES[category], quantity=quantity, nights=nights,
                                       arrival_time=arrival_time or "10:00", comments=comments or "")
        preview = {"trip_id": trip_id, "category": category, "pricing": pricing, "currency": currency,
                  "product": {**product, "Name": product_name.strip()}}
        if not confirm:
            return {**preview, "sent": False,
                   "note": "Nothing was sent. Show this to the operator; call again with confirm=true only after their explicit yes."}
        await services.myt().create_reservation(trip_id, [product], external_id=f"claude-{tag}", comments=comments)
        after = await services.myt().get_trip_v3(trip_id)
        match = find_reservation(after, name_contains=tagged_name)
        if not match:
            raise ToolError("MYT answered success but the reservation is NOT visible when the trip is read back; nothing more "
                            "was sent. This can happen when a field MYT silently rejects. Tell the operator before trying again.")
        kinds = SUPPLIER_KIND[category]
        if not any((match.get("supplier_type") or {}).get(k) for k in kinds):
            raise ToolError(f"The reservation was created (order {match['order_id']}) but its supplier is not a {' or '.join(kinds)} supplier, "
                            f"so it is not a proper {category} reservation. Tell the operator; supplier_id {supplier_id} does not fit {category}.")
        return {**preview, "sent": True, "order_id": match["order_id"], "reservation_id": match["reservation_id"],
               "confirmed_by_reading_the_trip_back": True,
               "next_step": "Status starts at Ready To Send; move it on (Skip To COR, Print Voucher...) on the MYT screen."}

    @mcp.tool(annotations=WRITE_IDEMPOTENT)
    @tool_errors
    @with_checked_at
    async def update_supplier_reservation(
        trip_id: int, order_id: int, reservation_id: int, price: float | None = None, quantity: float | None = None,
        nights: int | None = None, start_date: date | None = None, arrival_time: str | None = None,
        comments: str | None = None, confirm: bool = False,
    ) -> dict[str, Any]:
        """Change the price, quantity, nights, date, arrival time or comment of ONE EXISTING supplier reservation
        (order_id, reservation_id from get_supplier_reservations) through MYT's write API (reservations/Update). It cannot
        move an order's status (Ready To Send, Voucher Issued...): that is screen-only. Only pass the fields that change;
        anything left out keeps its current value (MYT's Update needs the whole row, so this fills the rest in for you).
        Without confirm=True this only shows what would be sent. With confirm=True, after the operator's explicit yes, it
        sends the write and reads the trip back to confirm the new values really took. If ALLOWED_TRIP_IDS lists trips only those
        can be touched; when it is empty, any trip the operator names."""
        services.check_trip(trip_id)
        if price is not None and price <= 0:
            raise ToolError("price must be more than 0.")
        if quantity is not None and quantity <= 0:
            raise ToolError("quantity must be more than 0.")
        if nights is not None and nights <= 0:
            raise ToolError("nights must be more than 0.")
        if start_date and start_date < _today():
            raise ToolError("start_date is in the past.")
        if arrival_time and not TIME_RE.fullmatch(arrival_time):
            raise ToolError("arrival_time must be 24-hour HH:MM.")
        v3 = await trip_v3(trip_id)
        current = find_reservation(v3, order_id=order_id, reservation_id=reservation_id)
        if not current:
            raise ToolError(f"No reservation {reservation_id} in order {order_id} on trip {trip_id}; check get_supplier_reservations.")
        row = build_update_row(current, price=price, quantity=quantity, nights=nights,
                               start_date=start_date.isoformat() if start_date else None, arrival_time=arrival_time, comments=comments)
        preview = {"trip_id": trip_id, "order_id": order_id, "reservation_id": reservation_id,
                  "current": {"price": _amount(current.get("price")), "quantity": current.get("quantity"), "nights": current.get("duration"),
                             "start": _date((current.get("dates") or {}).get("start"))},
                  "sending": row}
        if not confirm:
            return {**preview, "sent": False,
                   "note": "Nothing was sent. Show this to the operator; call again with confirm=true only after their explicit yes."}
        await services.myt().update_reservation(order_id, [row], trip_id=trip_id)
        after = await trip_v3(trip_id)
        match = find_reservation(after, order_id=order_id, reservation_id=reservation_id)
        if not match or round(_amount(match.get("price")) or 0, 2) != round(row["Price"], 2):
            raise ToolError("MYT answered success but the reservation does not read back with the new values; nothing more "
                            "was sent. Tell the operator before trying again.")
        return {**preview, "sent": True, "confirmed_by_reading_the_trip_back": True,
               "new": {"price": _amount(match.get("price")), "quantity": match.get("quantity"), "nights": match.get("duration")}}

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def check_reservation_paperwork(
        trip_id: int,
        vouchers: list[ScreenDoc] | None = None,
        supplier_invoices: list[ScreenDoc] | None = None,
        supplier_payments: list[ScreenDoc] | None = None,
        fresh: bool = False,
    ) -> Any:
        """For every supplier reservation of a trip, is there a voucher, a supplier invoice and a supplier payment, and do
        the amounts agree (שוברים, חשבוניות ספקים, תשלומים)? Read the reservations from MYT; YOU read the vouchers, supplier
        invoices and supplier payments of THIS trip from its MYT screens (quote_guide("reservations")) and pass them in. Returns one row per
        reservation with found / missing, amount differences, partial or double payments, and documents that match no
        reservation. Pass fresh=true right after a reservation change made via Claude in Chrome, to force a live read.
        Pass an empty list [] when you READ that screen and found nothing; leave it out only when you did not read it: then
        it is reported as NOT CHECKED, never as missing. Read only: it creates or changes nothing."""
        return paperwork_check(
            await trip_v3(trip_id, fresh), date.today(),
            None if vouchers is None else [d.model_dump() for d in vouchers],
            None if supplier_invoices is None else [d.model_dump() for d in supplier_invoices],
            None if supplier_payments is None else [d.model_dump() for d in supplier_payments],
        )

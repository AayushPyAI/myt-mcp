"""MYT read tools for supplier reservations: statuses, voucher flags and the reservation-vs-quote reconciliation."""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field, field_validator
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.myt.paperwork import paperwork_check
from myt_mcp.myt.summaries import _amount, _date
from myt_mcp.myt.reservations import (CATEGORY_NOTE, KNOWN_CREATE_CATEGORIES, build_create_product, build_update_row,
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
        different, UI-only flow). Only category="Transport" (flights, trains, transfers, car rental) is supported: """ + CATEGORY_NOTE.split("other categories")[0] + """other categories
        are refused here rather than silently failing; use Claude in Chrome for them.
        `supplier_id` must be an existing MYT supplier id (from this trip's suppliers or quotation); never invent one.
        `pricing` is "PS" (the price covers the whole booking) or "PP" (per person; MYT multiplies by travellers).
        Without confirm=True this only shows exactly what would be sent and changes nothing: show it to the operator first.
        With confirm=True, after the operator's explicit yes, it sends the write, reads the trip back, and reports the new
        order id and reservation id, or an error if MYT did not actually create it (MYT can answer success while silently
        dropping a product it does not support). Only the trips in ALLOWED_TRIP_IDS can be touched. The new order starts as
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
        sends the write and reads the trip back to confirm the new values really took. Only the trips in ALLOWED_TRIP_IDS
        can be touched."""
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

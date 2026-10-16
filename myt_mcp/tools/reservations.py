"""MYT read tools for supplier reservations: statuses, voucher flags and the reservation-vs-quote reconciliation."""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.myt.paperwork import paperwork_check
from myt_mcp.myt.reservations import reconcile, reservations_summary
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


class ScreenDoc(BaseModel):
    """One row read from a MYT screen (a voucher, a supplier invoice or a supplier payment)."""

    order_id: int | None = Field(default=None, description="The order id (R2342258 -> 2342258) when the row shows it; best way to match")
    supplier: str | None = Field(default=None, description="Supplier name as the row shows it")
    number: str | None = Field(default=None, description="Voucher or invoice number, e.g. V2324")
    amount: float | None = Field(default=None, description="Amount on the row")
    currency: str | None = Field(default=None, description="EUR, ILS or USD")


def register(mcp: MCPServer, services: Services) -> None:
    async def trip_v3(trip_id: int) -> dict[str, Any]:
        services.check_trip(trip_id)
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
    async def get_supplier_reservations(trip_id: int, soon_days: int = 7) -> Any:
        """Supplier reservations of a trip, by trip_id (from find_trip; NOT the trip number) (הזמנות ספקים, שוברים): every
        reservation with supplier, product, dates, quantity, the cost the MYT screen shows and the supplier order's
        STATUS (Ready To Send, Voucher Issued, Reservation Confirmed), plus `voucher_flags`: orders whose voucher is
        not sent although the service starts within `soon_days` days. Voucher numbers, supplier invoices and payments
        are not in the API (see not_in_api). Read only."""
        check_days(soon_days)
        return reservations_summary(await trip_v3(trip_id), date.today(), soon_days)

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def reconcile_trip(trip_id: int, soon_days: int = 7) -> Any:
        """Reconciliation of a trip (התאמה): each supplier reservation against its line in the selected quotation. Shows
        per reservation: cost, quote line total, the profit the quote adds (3%, 13% or 15% is normal), and a verdict
        (ok / MISMATCH, also when the dates differ); reservations with no quote line, quote lines with no reservation,
        and voucher flags. Read only: it changes nothing in MYT. Report mismatches; do not fix them without the
        operator's approval."""
        check_days(soon_days)
        return reconcile(await trip_v3(trip_id), date.today(), soon_days)

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def check_reservation_paperwork(
        trip_id: int,
        vouchers: list[ScreenDoc] | None = None,
        supplier_invoices: list[ScreenDoc] | None = None,
        supplier_payments: list[ScreenDoc] | None = None,
    ) -> Any:
        """For every supplier reservation of a trip, is there a voucher, a supplier invoice and a supplier payment, and do
        the amounts agree (שוברים, חשבוניות ספקים, תשלומים)? Read the reservations from MYT; YOU read the vouchers, supplier
        invoices and supplier payments of THIS trip from its MYT screens (quote_guide("reservations")) and pass them in. Returns one row per
        reservation with found / missing, amount differences, partial or double payments, and documents that match no
        reservation. Read only: it creates or changes nothing."""
        return paperwork_check(
            await trip_v3(trip_id), date.today(),
            [d.model_dump() for d in vouchers or []], [d.model_dump() for d in supplier_invoices or []],
            [d.model_dump() for d in supplier_payments or []],
        )

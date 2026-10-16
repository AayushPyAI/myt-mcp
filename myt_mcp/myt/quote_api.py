"""Writes into an MYT quotation (COST lines, Margin Prices, totals, mini-site).

The public API has no endpoints for any of this (checked 13 Oct 2026 against the documentation's own endpoint list:
the only writes are Reservations Create/Update (trip-level supplier reservations, not quotation lines), Product
CreateProductCatalog, Customer/Organization/Participant/Tag/History create, and the trip copy calls DuplicateTripWebToLead,
DuplicateTripToTenant, CopyTripToTenant, GenerateTrip, ChangeTripStatus). An undocumented
`/api/Quotation/GetQuotation` controller exists and appears to need a logged-in
web session, so the web app most likely uses an internal API.

Next step (plan step 0): log in to MYT with the client's operator account, add
one line in a test quotation's COST tab, and record the network calls in
DevTools. Implement the methods below against those calls, or against vendor
endpoints if MYT support grants quotation API access.
"""

from __future__ import annotations

from typing import Any

from myt_mcp.quote.calc import CostLine

NOT_CONNECTED = (
    "Writing to MYT quotations is not connected yet: the MYT public API has no "
    "quotation endpoints. Use calculate_quote to prepare the lines and let the "
    "operator enter them in MYT for now."
)


class QuoteAPI:
    """Interface for the quotation write path. Methods raise until implemented."""

    async def get_quotation(self, quotation_id: int) -> dict[str, Any]:
        raise NotImplementedError(NOT_CONNECTED)

    async def add_cost_lines(self, quotation_id: int, version: str, lines: list[CostLine]) -> Any:
        raise NotImplementedError(NOT_CONNECTED)

    async def update_cost_line(self, quotation_id: int, line_id: int, line: CostLine) -> Any:
        raise NotImplementedError(NOT_CONNECTED)

    async def remove_cost_line(self, quotation_id: int, line_id: int) -> Any:
        raise NotImplementedError(NOT_CONNECTED)

    async def set_markups(self, quotation_id: int, markups: dict[str, float]) -> Any:
        raise NotImplementedError(NOT_CONNECTED)

    async def get_totals(self, quotation_id: int) -> dict[str, Any]:
        raise NotImplementedError(NOT_CONNECTED)

    async def get_quote_link(self, trip_id: int) -> str:
        raise NotImplementedError(NOT_CONNECTED)

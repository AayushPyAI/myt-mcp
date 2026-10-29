"""Daily exchange rate for the operator: the Bank of Israel representative rate as reference, and a check of the Bank Hapoalim cash sale the client wants in MYT. Prepares the number only; MYT is never changed."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.boi.client import PAGE, parse_rate
from myt_mcp.checks import with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
CURRENCIES = ("EUR", "USD", "GBP", "CHF")
CASH_SALE_BAND = (0.5, 6.0)      # % above the representative rate; Hapoalim EUR was +2.7% on 23 Oct 2026 (3.5800 over 3.4844)
MYT_PLACE = "MYT: Settings > Accounting Settings > MY CURRENCIES > Fixing the exchange rate (EUR to ILS row, field Exchange Rate, then SAVE)"


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def daily_exchange_rate(currency: str = "EUR", myt_current_rate: float | None = None, hapoalim_cash_sale: float | None = None) -> dict[str, Any]:
        """The daily shekel rate task. Gives the Bank of Israel representative rate ("Yatzig", שער יציג) as a reference. The number the client enters in MYT is
        NOT that: it is the EUR **cash sale (מזומנים מכירה)** of Bank Hapoalim's table (bankhapoalim.co.il/forms/he/foreign-currency/exchange-rates), which no server can
        read (bot check). Read it in the operator's Chrome (read only; the operator passes the page's "I am human" check themselves, never you) and pass it as
        `hapoalim_cash_sale`: this tool then checks it against the Yatzig and compares it with `myt_current_rate` (the MYT field). Only PREPARES the number: saving
        it in MYT needs the client's written approval and the operator's yes."""
        code = currency.strip().upper()
        if code not in CURRENCIES:
            raise ToolError(f"currency must be one of: {', '.join(CURRENCIES)}.")
        if myt_current_rate is not None and not 0.5 < myt_current_rate < 20:
            raise ToolError("myt_current_rate must be the shekel rate you read in MYT (for example 3.53).")
        if hapoalim_cash_sale is not None and not 0.5 < hapoalim_cash_sale < 20:
            raise ToolError("hapoalim_cash_sale must be the shekel value of the cash-sale (מזומנים מכירה) cell of the currency's row (for example 3.58).")
        rows = await services.boi().rates()
        if code not in rows:
            raise ToolError(f"The Bank of Israel feed has no row for {code} today; read it on {PAGE}.")
        rate = parse_rate(rows[code])
        answer: dict[str, Any] = {
            "currency": code, "ils_per_1": rate["ils_per_unit"], "change_pct_vs_previous_day": rate["change_pct_vs_previous"],
            "published_utc": rate["published_utc"], "source": "Bank of Israel representative rate (boi.org.il feed), same as the Yatzig column on bankhapoalim.co.il",
            "source_url": PAGE, "enter_in_myt_at": MYT_PLACE,
            "decimals_note": "MYT showed 3.53 (two decimals) on 17 Oct 2026; the bank gives four. Ask the client which to enter; this tool never rounds for you.",
            "prepare_only": "Nothing was changed in MYT. Show this to the operator; entering it needs the client's written approval and the operator's yes.",
        }
        if rate["age_days"] > 3:
            answer["warning"] = f"The newest rate is {rate['age_days']} days old (the bank publishes on business days). Say so and check the bank's page."
        to_enter = rate["ils_per_unit"]
        if hapoalim_cash_sale is None:
            answer["client_wants"] = ("The rate for MYT is Bank Hapoalim's cash sale (מזומנים מכירה), not this representative rate: read it in the operator's Chrome and call this tool "
                                      "again with `hapoalim_cash_sale`. Until then do not offer the number above as the rate to enter.")
        else:
            above = (hapoalim_cash_sale / rate["ils_per_unit"] - 1) * 100
            answer["hapoalim_cash_sale"] = {"value": hapoalim_cash_sale, "pct_above_representative": round(above, 2), "source": "Bank Hapoalim exchange-rate table, read by the assistant in the operator's Chrome",
                                            "note": "Enter this one in MYT (client's column, 26 Oct 2026), after the written approval and the operator's yes."}
            if not CASH_SALE_BAND[0] <= above <= CASH_SALE_BAND[1]:
                answer["warning_cash_sale"] = (f"The cash sale is {above:.1f}% from the representative rate; it was +2.7% on 23 Oct 2026 and is normally {CASH_SALE_BAND[0]:g} to {CASH_SALE_BAND[1]:g}%. "
                                               "Read the cell again (right row, right column, same date) before it is used.")
            to_enter = hapoalim_cash_sale
        if myt_current_rate is not None:
            diff = to_enter - myt_current_rate
            answer["against_myt"] = {"myt_rate": myt_current_rate, "difference": round(diff, 4), "difference_pct": round(diff / myt_current_rate * 100, 2),
                                     "compared_with": "Hapoalim cash sale" if hapoalim_cash_sale is not None else "Bank of Israel representative rate",
                                     "note": "Positive = the bank's rate is higher than the rate in MYT."}
        return answer

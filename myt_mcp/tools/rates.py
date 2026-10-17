"""Daily exchange rate for the operator: the Bank of Israel representative rate. Prepares the number only; MYT is never changed."""

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
MYT_PLACE = "MYT: Settings > Accounting Settings > MY CURRENCIES > Fixing the exchange rate (EUR to ILS row, field Exchange Rate, then SAVE)"


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def daily_exchange_rate(currency: str = "EUR", myt_current_rate: float | None = None) -> dict[str, Any]:
        """Today's official shekel rate for the daily exchange-rate task: the Bank of Israel representative rate ("Yatzig", שער יציג), shekel per 1 EUR
        (or USD, GBP, CHF), with its publication time. It is the same number as the "Yatzig" column on Bank Hapoalim's exchange-rate page. Pass
        `myt_current_rate` (the value you read in MYT's "Fixing the exchange rate" field) to get the difference. This only PREPARES the number: show it to
        the operator. Entering it in MYT is a financial setting change that needs the client's written approval; never save it yourself."""
        code = currency.strip().upper()
        if code not in CURRENCIES:
            raise ToolError(f"currency must be one of: {', '.join(CURRENCIES)}.")
        if myt_current_rate is not None and not 0.5 < myt_current_rate < 20:
            raise ToolError("myt_current_rate must be the shekel rate you read in MYT (for example 3.53).")
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
        if myt_current_rate is not None:
            diff = rate["ils_per_unit"] - myt_current_rate
            answer["against_myt"] = {"myt_rate": myt_current_rate, "difference": round(diff, 4), "difference_pct": round(diff / myt_current_rate * 100, 2),
                                     "note": "Positive = the bank's rate is higher than the rate in MYT."}
        return answer

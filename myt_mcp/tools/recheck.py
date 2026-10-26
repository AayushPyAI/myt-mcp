"""Re-check the prices of an existing quotation (read only): recheck_quote lists the lines and who can price them again, recheck_report compares what compose_answer found."""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.composed import COMPOSED
from myt_mcp.errors import tool_errors
from myt_mcp.quote.recheck import plan, report
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _today() -> date:
    return date.today()


class PriceCheck(BaseModel):
    line: int = Field(description="The line number from recheck_quote")
    option: str = Field(description="The option's text exactly as the compose_answer table shows it (a part of the row is enough, but it must identify the row)")
    price: float = Field(description="That row's price exactly as compose_answer shows it, for the whole group")
    currency: str = Field("EUR", description="EUR, USD...")


def register(mcp: MCPServer, services: Services) -> None:
    async def trip_v3(trip_id: int, fresh: bool = False) -> dict[str, Any]:
        services.check_trip(trip_id)
        if fresh:
            services.myt().invalidate_trip_cache(trip_id)
        v3 = await services.myt().get_trip_v3(trip_id)
        got = (v3.get("trip") or {}).get("trip_id")
        ensure("MYT", [] if got == trip_id else [f"MYT returned trip {got} instead of {trip_id}"])
        return v3

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def recheck_quote(trip_id: int, fresh: bool = False) -> Any:
        """FIRST STEP when the operator asks whether the prices of an existing quotation are still right ("check trip 168's prices", "what changed"). By trip_id (from find_trip). Reads the
        selected quotation and the trip's supplier reservations and lists every cost line with: the net on its reservation, what kind of line it is, which tools can price it again,
        and what to ask the operator first. Read only: nothing is changed in MYT. Then run those tools, call compose_answer for each kind, and finish with recheck_report."""
        return plan(await trip_v3(trip_id, fresh), _today())

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def recheck_report(trip_id: int, checks: list[PriceCheck], fresh: bool = False) -> Any:
        """LAST STEP of a re-check: the comparison, built by the server. For each line you re-priced pass the row you chose from the compose_answer table (its option text and its price).
        A price that is not in a compose_answer of the last 3 hours is refused: never type or read a price yourself. The answer lists, per line, the old net, today's price and the
        difference, then the counts and every line not checked with its reason. Show its `answer` exactly as written and call check_answer on it. Read only."""
        return report(await trip_v3(trip_id, fresh), [c.model_dump() for c in checks], COMPOSED, _today())

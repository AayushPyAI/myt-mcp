"""Quote preview: MYT's pricing, computed locally."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.composed import COMPOSED
from myt_mcp.errors import tool_errors
from myt_mcp.quote.calc import CostLine, QuoteTotals, calculate
from myt_mcp.quote.compare import QuoteComparison, QuoteSnapshot, compare


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def calculate_quote(
        lines: list[CostLine],
        paying_pax: int,
        free_pax: int = 0,
        conversion_pct: float = 5,
        fixed_markups_pp: dict[str, float] | None = None,
        percent_markups: dict[str, float] | None = None,
    ) -> QuoteTotals:
        """Preview a quote the way MYT prices it, without writing anything. Returns net, margin and gross per
        category and per person plus the publish price. conversion_pct is MYT's 'Conversion difference' (5% by
        default); fixed_markups_pp are the per-person amounts on the Margin Prices tab, e.g. {"Other": 230}. PP lines are multiplied by ALL
        travellers (paying + free) whatever the qty; use PS with qty = number of travellers when the price differs by
        age. percent_markups are the 'Markup %' boxes per category on the Margin Prices tab, e.g. {"Lodging": 10} or
        {"General": 5}: the category total after profits x (1 + %), checked once on MYT; repeat the returned notes and compare
        with MYT after entering them. net_pg is the group net of all lines: it must equal the sum of the tools' group totals."""
        if not lines:
            raise ToolError("Give at least one cost line.")
        if free_pax < 0 or not 0 <= conversion_pct <= 100:
            raise ToolError("free_pax must be 0 or more and conversion_pct between 0 and 100.")
        try:
            totals = calculate(lines, paying_pax, free_pax, conversion_pct, fixed_markups_pp, percent_markups)
        except ValueError as e:
            raise ToolError(str(e)) from e
        # only the totals are remembered for check_answer: the line prices were passed in by the assistant, so they must prove themselves against the compose_answer texts
        COMPOSED.remember("quote", " ".join(f"{x:,.2f}" for x in (totals.net_pp, totals.net_pg, totals.margin_pp, totals.gross_pp, totals.gross_pg, totals.publish_pp, totals.publish_pg)))
        return totals

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def compare_quotes(before: QuoteSnapshot, after: QuoteSnapshot) -> QuoteComparison:
        """Compare two versions of a quotation (e.g. V1 and V2) and say exactly what changed and what it did to the
        price: lines added, removed or changed (date, supplier price, profit %, qty, nights), profit per line,
        cost per category, markup changes and, when the Margin Prices tab of both versions is given, the selling price
        change with a bridge (supplier costs vs our margin). The API gives no supplier price, profit % or markup,
        so read both versions in the MYT website (read-only, see quote_guide('versions')) and pass them here;
        the selected version's lines can come from get_quotation. Show everything the tool returns, and explain
        the difference only from its answer."""
        if not before.lines and not after.lines:
            raise ToolError("Both versions have no cost lines: nothing to compare.")
        return compare(before, after)

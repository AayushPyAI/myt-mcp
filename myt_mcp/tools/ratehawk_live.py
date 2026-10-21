"""ratehawk_hotels: the server reads RateHawk itself, in the automation Chrome (Playwright), and returns the finished answer.

Claude makes ONE call. The same tested page script as the Chrome recipe (myt_mcp/sites/ratehawk_hotels.js) runs in the server's own logged-in
browser, its rows never pass through Claude (no clicks, no copying, no cut answers), and compose_answer's rules build the text.
The automation Chrome (scripts/start_all.sh, port 9333) must be logged in to RateHawk once by the operator; the server never types a password.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.browser import BrowserError
from myt_mcp.compose import NotChecked, apply_wishes, compose
from myt_mcp.errors import tool_errors
from myt_mcp.services import Services
from myt_mcp.sites import convert_all
from myt_mcp.sites.ratehawk_hotels import ratehawk_hotels_recipe

log = logging.getLogger("myt_mcp")
ORIGIN = "https://www.ratehawk.com"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


async def read_page(services: Services, recipe: dict[str, Any]) -> list[str]:
    """Opens the recipe's url in the server's browser, runs its script and returns every part of the script's answer."""
    script = recipe["script"]
    start = script.index("await (async () => {")        # the script's header comments come first; evaluate() takes an expression, so drop the top-level `await`
    body = script[start + len("await "):].strip()

    async def act(page: Any) -> list[str]:
        await page.goto(recipe["url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
        if "/accounts/login" in page.url:
            raise BrowserError("RateHawk is not logged in in the automation Chrome. Ask the operator to sign in once in that window (scripts/start_all.sh opens it); nothing was typed.")
        first = await page.evaluate(body)
        parts = await page.evaluate("window.__mytParts || []")
        return parts or [first]

    return await services.browser().run(ORIGIN, ORIGIN + "/", act)


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def ratehawk_hotels(country: str, city: str, check_in: date, check_out: date, adults: int = 2, children_ages: list[int] | None = None,
                              breakfast: bool = False, free_cancellation: bool = False, stars: int | None = None, pages: int = 3, show: int = 12,
                              myt_supplier: dict[str, str] | None = None) -> dict[str, Any]:
        """HOTELS ON RATEHAWK IN ONE CALL: the server opens RateHawk in its own logged-in browser, reads the price-sorted list (`pages` x 20 hotels)
        and the rating-sorted list, checks sort, page and count, and returns `answer`: the finished table with Cheapest / Best fit / Most flexible /
        Recommended, cautions and links. Show `answer` unchanged; do not rewrite it. `country` and `city` are the words in RateHawk's address
        (portugal, lisbon). `stars` = minimum stars; `show` = rows in the table (the picks always use every row read). Arbitrip is not read by this tool: read it in Claude in Chrome and say so in your reply.
        If it says RateHawk is not logged in, tell the operator to sign in once in the automation Chrome window; never try another route."""
        try:
            price_run = ratehawk_hotels_recipe(country, city, check_in, check_out, adults, "price_asc", breakfast, free_cancellation, stars, pages, children_ages)
            rating_run = ratehawk_hotels_recipe(country, city, check_in, check_out, adults, "rating", breakfast, free_cancellation, stars, 1, children_ages)
        except ValueError as e:
            raise ToolError(str(e)) from None
        items = [{"site": "ratehawk_hotels", "result": part, "url": price_run["url"]} for part in await read_page(services, price_run)]
        items += [{"site": "ratehawk_hotels", "result": part, "url": rating_run["url"]} for part in await read_page(services, rating_run)]
        wishes = {"breakfast": breakfast, "free_cancellation": free_cancellation, "stars_min": stars}
        offers, sources, problems, by_price, notes = convert_all(items, wishes)
        if problems:
            log.info("CHECK ratehawk_hotels refused: %s", "; ".join(dict.fromkeys(problems))[:800])
            return {"ok": False, "problems": list(dict.fromkeys(problems)),
                    "next": "Tell the operator what failed; if RateHawk was not read, do not quote from memory. The Chrome recipe (ratehawk_hotels_recipe) is the fallback."}
        filters = [f"{label} (operator)" for on, label in ((breakfast, "Breakfast included"), (free_cancellation, "Free cancellation")) if on]
        filters += [f"{stars}+ stars (operator)"] if stars else []
        filters.append("Guests: " + " and ".join([f"{adults} adults"] + [f"child {a}" for a in children_ages or []]) + " (operator)")
        for src in sources:
            src.link = f"{price_run['url']} (price-sorted) and {rating_run['url']} (rating-sorted)"
        apply_wishes(offers, wishes)
        out = compose("hotels", filters, sources, [NotChecked(name="Arbitrip", reason="no browser tool for Arbitrip in this tool: read it separately")],
                      offers, myt_supplier or {}, None, by_price, " ".join(notes), max_rows=show)
        log.info("CHECK ratehawk_hotels ok=%s offers=%s problems=%s", out.get("ok"), len(offers), "; ".join(out.get("problems", []))[:600])
        return out

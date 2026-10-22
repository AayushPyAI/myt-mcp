"""ratehawk_hotels: the server reads RateHawk itself, in the automation Chrome (Playwright), and returns the finished answer.

Claude makes ONE call. The server opens the price-sorted pages (one tab per page, at the same time) and the rating-sorted page by their own
addresses, reads every card in Python, checks sort, page, count and order, and compose's rules build the text. No page script, no clicks on
"next" (a click read a stale page in a test: 40 unique hotels in 60 rows), no copying through Claude. The automation Chrome
(scripts/start_all.sh, port 9333) is logged in to RateHawk once by the operator; the server never types a password.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.browser import BrowserError
from myt_mcp.compose import NotChecked, apply_wishes, compose
from myt_mcp.errors import tool_errors
from myt_mcp.services import Services
from myt_mcp.sites import convert_all
from myt_mcp.sites.ratehawk_hotels import RATEHAWK_SORTS, ask_gate, limits, ratehawk_hotels_recipe

log = logging.getLogger("myt_mcp")
ORIGIN = "https://www.ratehawk.com"
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
CARD = ".zen-hotelcard-wrapper"
BLOCK = re.compile(r"captcha|verify (that )?you are|not a robot|access denied|too many requests|unusual traffic|temporarily blocked|rate limit", re.I)
CACHE_SECONDS = 600       # the same search again within 10 minutes is answered from the last read: fewer requests to RateHawk, and faster
STAGGER_SECONDS = 0.7     # tabs start one after the other, not all in the same instant
_cache: dict[tuple, tuple[float, list[dict[str, Any]], str]] = {}
MAX_TABS = 4
CARDS_JS = """[...document.querySelectorAll('.zen-hotelcard-wrapper')].map(c => ({
    name: c.querySelector('.zen-hotelcard-name')?.innerText?.trim() || null,
    stars: c.querySelectorAll('.zen-ui-stars-star').length || null,
    href: c.querySelector('.zen-hotelcard-name-link')?.getAttribute('href') || null,
    text: c.innerText}))"""
PAGE_JS = """({sort: (document.querySelector('.zen-sorter')?.innerText || '').replace(/^\\s*Sort by\\s*/i, '').trim(),
    header: (document.body.innerText.match(/[A-Za-z\\u00C0-\\u00FF' .-]+:\\s*([\\d,]+)\\s+accommodation options available/) || [])[0] || null,
    page: new URL(location.href).searchParams.get('page'), url: location.href})"""


def parse_card(raw: dict[str, Any]) -> dict[str, Any]:
    """One hotel card (its text, name, star count and link) as the same row the Chrome script returns; a field the card does not show is None."""
    lines = [x.strip() for x in (raw.get("text") or "").split("\n") if x.strip()]

    i = next((k for k, x in enumerate(lines) if re.fullmatch(r"\d+ / \d+", x)), -1)
    tail = lines[i + 1:] if i >= 0 else lines[1:]          # meal and cancellation come after the room line; the name ("... Bed & Breakfast ...") must not match

    def first(rx: str, among: list[str] | None = None) -> str | None:
        return next((x for x in (lines if among is None else among) if re.search(rx, x, re.I)), None)

    bed = lines[i + 2] if i >= 0 and len(lines) > i + 2 and not re.search(r"(meals|breakfast|cancellation|^Pay |^EUR|^[A-Z]{3}\s)", lines[i + 2], re.I) else None
    href = raw.get("href")
    return {
        "name": raw.get("name") or (lines[0] if lines else None), "stars": raw.get("stars"),
        "distance": first(r"from the .* center"), "score": next((x for x in lines if re.fullmatch(r"\d+(\.\d)?", x)), None),
        "reviews": first(r"^\d[\d,]*\s+reviews?"), "room": lines[i + 1] if i >= 0 and len(lines) > i + 1 else None, "bed": bed,
        "meal": first(r"(meals|breakfast|half board|full board|all inclusive)", tail), "cancellation": first(r"cancellation", tail), "payment": first(r"^Pay ", tail),
        "price": next((x for x in lines if re.fullmatch(r"[A-Z]{3}\s?[\d,]+(\.\d+)?", x)), None), "basis": first(r"^for \d+ nights?"),
        "path": href.split("?")[0] if href else None,
    }


async def _read_one(page: Any, url: str, want_page: int, want_sort: str) -> dict[str, Any]:
    """One results page: opened by its address, checked (login, sort label, page number), every card parsed."""
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        if "ERR_ABORTED" not in str(e):      # RateHawk redirects its own address (adds q=<id>) and Chrome reports the first load as aborted: the page still comes
            raise
    if "/accounts/login" in page.url:
        raise BrowserError("RateHawk is not logged in in the automation Chrome. Ask the operator to sign in once in that window (scripts/start_all.sh opens it); nothing was typed.")
    try:
        await page.wait_for_selector(CARD, timeout=45000)
    except Exception:
        text = await page.evaluate("document.body ? document.body.innerText.slice(0, 800) : ''")
        if BLOCK.search(text or ""):          # a block or captcha is never worked around and never retried
            raise BrowserError("RateHawk is showing a block or a captcha. Stop: do not retry and do not try another route. Tell the operator to open the automation Chrome window and look at the page.") from None
        raise
    await page.wait_for_function("p => new URL(location.href).searchParams.get('page') === String(p)", arg=want_page, timeout=20000)
    await page.wait_for_timeout(700)
    info = await page.evaluate(PAGE_JS)
    if info["sort"] != want_sort:
        raise BrowserError(f"RateHawk shows the list sorted by '{info['sort']}', not '{want_sort}': nothing was read from it.")
    cards = await page.evaluate(CARDS_JS)
    return {"info": info, "rows": [parse_card(c) | {"p": want_page} for c in cards]}


async def read_lists(services: Services, jobs: list[tuple[str, int, str]]) -> list[dict[str, Any]]:
    """jobs: (url, page number, expected sort label). The pages open at the same time, one tab each (at most MAX_TABS); results come back in job order."""
    async def act(page: Any) -> list[dict[str, Any]]:
        extra = [await page.context.new_page() for _ in range(min(len(jobs), MAX_TABS) - 1)]
        tabs = [page] + extra
        try:
            queue: asyncio.Queue = asyncio.Queue()
            for k, job in enumerate(jobs):
                queue.put_nowait((k, job))
            results: list[Any] = [None] * len(jobs)

            async def worker(tab: Any, delay: float) -> None:
                await asyncio.sleep(delay)
                while not queue.empty():
                    k, (url, n, sort) = queue.get_nowait()
                    try:
                        results[k] = await _read_one(tab, url, n, sort)
                    except BrowserError:
                        raise
                    except Exception as e:                       # one fresh try for a page that came slowly or half-loaded
                        log.info("CHECK ratehawk_hotels: page %s failed (%s), trying once more", n, str(e).splitlines()[0][:120])
                        results[k] = await _read_one(tab, url, n, sort)

            await asyncio.gather(*[worker(t, k * STAGGER_SECONDS) for k, t in enumerate(tabs)])
            return results
        finally:
            for t in extra:
                await t.close()

    key = tuple(jobs)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    results = await services.browser().run(ORIGIN, ORIGIN + "/", act)
    _cache[key] = (time.time(), results, datetime.now().strftime("%d %b %Y %H:%M"))
    for old_key in [k for k, v in _cache.items() if time.time() - v[0] > CACHE_SECONDS]:
        del _cache[old_key]
    return results


def checked_at(jobs: list[tuple[str, int, str]]) -> str:
    hit = _cache.get(tuple(jobs))
    return hit[2] if hit else datetime.now().strftime("%d %b %Y %H:%M")


def answer_json(runs: list[dict[str, Any]], sort_label: str) -> str:
    """The pages of one sorted list as the script-shaped JSON that the RateHawk converter checks and reads (see sites/ratehawk_hotels.py)."""
    rows = [r for run in runs for r in run["rows"]]
    prices = [float(re.sub(r"[^\d.]", "", r["price"])) for r in rows if r.get("price")]
    asc, desc = prices == sorted(prices), prices == sorted(prices, reverse=True)
    return json.dumps({"ok": True, "header": next((r["info"]["header"] for r in runs if r["info"]["header"]), None), "sort": sort_label, "start_page": 1,
                       "pages_read": len(runs), "rows_read": len(rows), "stopped": None, "price_order": "ascending" if asc else "descending" if desc else "mixed", "rows": rows})


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def ratehawk_hotels(country: str, city: str, check_in: date, check_out: date, adults: int = 2, children_ages: list[int] | None = None,
                              breakfast: bool = False, free_cancellation: bool = False, stars: int | None = None, budget_per_night: float | None = None,
                              max_distance_km: float | None = None, operator_answered: bool = False, pages: int = 3, show: int = 12,
                              myt_supplier: dict[str, str] | None = None) -> dict[str, Any]:
        """HOTELS ON RATEHAWK IN ONE CALL: the server opens RateHawk in its own logged-in browser, reads the price-sorted list (`pages` x 20 hotels)
        and the rating-sorted list, checks sort, page and count, and returns `answer`: the finished table with Cheapest / Best fit / Most flexible /
        Recommended, cautions and links. Show `answer` unchanged; do not rewrite it. `country` and `city` are the words in RateHawk's address
        (portugal, lisbon). ASK FIRST: if the operator has not given minimum `stars`, `budget_per_night` (EUR) and `max_distance_km` from the centre, the
        tool does not search: it returns `ask_operator`; ask those questions in ONE message, wait for the reply, then call again with the answers.
        Set `operator_answered`=true (for "no preference") ONLY after the operator replied in this chat. `show` = rows in the table (the picks always use every row read). Arbitrip is not read by this
        tool: read it in Claude in Chrome and say so in your reply. If it says RateHawk is not logged in, tell the operator to sign in once in the
        automation Chrome window; never try another route."""
        asked = ask_gate(stars, budget_per_night, max_distance_km, operator_answered)
        if asked:
            return asked
        try:
            price_run = ratehawk_hotels_recipe(country, city, check_in, check_out, adults, "price_asc", breakfast, free_cancellation, stars, pages, children_ages)
            rating_run = ratehawk_hotels_recipe(country, city, check_in, check_out, adults, "rating", breakfast, free_cancellation, stars, 1, children_ages)
        except ValueError as e:
            raise ToolError(str(e)) from None
        price_label, rating_label = RATEHAWK_SORTS["price_asc"][1], RATEHAWK_SORTS["rating"][1]
        jobs = [(price_run["url"].replace("page=1", f"page={n}"), n, price_label) for n in range(1, pages + 1)] + [(rating_run["url"], 1, rating_label)]
        runs = await read_lists(services, jobs)
        price_runs, rating_runs = runs[:pages], runs[pages:]
        items = [{"site": "ratehawk_hotels", "result": answer_json(price_runs, price_label), "url": price_run["url"]},
                 {"site": "ratehawk_hotels", "result": answer_json(rating_runs, rating_label), "url": rating_run["url"]}]
        nights = (check_out - check_in).days
        wishes, filters = limits(stars, budget_per_night, max_distance_km, breakfast, free_cancellation, nights)
        offers, sources, problems, by_price, notes = convert_all(items, wishes)
        if problems:
            log.info("CHECK ratehawk_hotels refused: %s", "; ".join(dict.fromkeys(problems))[:800])
            return {"ok": False, "problems": list(dict.fromkeys(problems)),
                    "next": "Tell the operator what failed; if RateHawk was not read, do not quote from memory. The Chrome recipe (ratehawk_hotels_recipe) is the fallback."}
        for src in sources:
            src.link = f"{price_run['url']} (price-sorted) and {rating_run['url']} (rating-sorted)"
        filters.append("Guests: " + " and ".join([f"{adults} adults"] + [f"child {a}" for a in children_ages or []]) + " (operator)")
        apply_wishes(offers, wishes)
        out = compose("hotels", filters, sources, [NotChecked(name="Arbitrip", reason="no browser tool for Arbitrip in this tool: read it separately")],
                      offers, myt_supplier or {}, None, by_price, " ".join(notes), max_rows=show, checked_at=f"RateHawk read at {checked_at(jobs)} (server time; the same search is reused for {CACHE_SECONDS // 60} minutes)")
        log.info("CHECK ratehawk_hotels ok=%s offers=%s problems=%s", out.get("ok"), len(offers), "; ".join(out.get("problems", []))[:600])
        return out


def register_redirect(mcp: MCPServer) -> None:
    """The name `ratehawk_hotels` stays known when the server-browser tool is off: claude.ai keeps the tool list it saw when the connector was added, so a
    removed name would only answer 'Unknown tool'. This one points to the Chrome recipe, which asks the operator first."""
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_hotels(country: str = "", city: str = "", check_in: date | None = None, check_out: date | None = None, adults: int = 2,
                              children_ages: list[int] | None = None, breakfast: bool = False, free_cancellation: bool = False, stars: int | None = None,
                              budget_per_night: float | None = None, max_distance_km: float | None = None, operator_answered: bool = False,
                              pages: int = 3, show: int = 12, myt_supplier: dict[str, str] | None = None) -> dict[str, Any]:
        """NOT USED in this setup (RateHawk is read with Claude in Chrome): call ratehawk_hotels_recipe with the same values. It asks the operator first."""
        return {"ok": False, "searched": False, "next": "This tool is off. Call ratehawk_hotels_recipe with the same values (it asks the operator for stars, budget and distance first, "
                                                         "then gives the url and the script for Claude in Chrome)."}

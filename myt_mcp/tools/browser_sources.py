"""Tools for the price sources that have no live data tool.

They fetch no prices. Their job is to be the first thing Claude finds for a hotel, transfer or unsupported-site
request: they validate the search, hand over the search values in each site's own format and the playbook, and tell
Claude not to use web search or other connectors. Prices then come from the operator's browser (Claude in Chrome).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.errors import tool_errors
from myt_mcp.guide import sections

PLAN_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
MEALS = {"RO": "room only", "BB": "breakfast included", "HB": "half board", "FB": "full board", "AI": "all inclusive"}
NO_BROWSER = 'If no browser tool is available in this chat, say exactly: "Please turn on Claude in Chrome for this chat." Do not offer other sites.'

# site or topic keyword -> (what it is, the connected source to offer instead)
CONNECTED = ("tap", "israir", "mozio", "kiwitaxi")   # these have their own tool: say so instead of "not connected"
BROWSER_READ = ("skyscanner", "el al", "elal")   # no tool, but read in the operator's Chrome (quote_guide("flights")): not "not connected"
OTHER_SOURCES: dict[str, tuple[str, str]] = {
    "tripadvisor": ("activities and reviews", "Viator and GetYourGuide tools (viator_search_activities, getyourguide_find_activities)"),
    "booking.com": ("hotels", "RateHawk and Arbitrip via the hotel_prices tool"),
    "airbnb": ("hotels and rentals", "RateHawk and Arbitrip via the hotel_prices tool"),
    "agoda": ("hotels", "RateHawk and Arbitrip via the hotel_prices tool"),
    "marriott": ("hotels (a hotel's own website)", "RateHawk and Arbitrip via the hotel_prices tool"),
    "hilton": ("hotels (a hotel's own website)", "RateHawk and Arbitrip via the hotel_prices tool"),
    "pestana": ("hotels (a hotel's own website)", "RateHawk and Arbitrip via the hotel_prices tool"),
    "bensaude": ("hotels (a hotel's own website)", "RateHawk and Arbitrip via the hotel_prices tool"),
    "skyscanner": ("flights (comparison only, read in the operator's Chrome)", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "tap": ("flights (connected)", "tap_flight_prices and tap_fare_calendar"),
    "israir": ("flights (connected)", "israir_flight_prices"),
    "el al": ("flights (read in the operator's Chrome)", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "elal": ("flights (read in the operator's Chrome)", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "ryanair": ("flights", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "easyjet": ("flights", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "ita airways": ("flights", "sata_flight_prices (Azores), tap_flight_prices (TAP Air Portugal), israir_flight_prices (Israir, from or to Tel Aviv); other airlines are not connected yet"),
    "sixt": ("car rental (needs login)", "ofran_car_prices"),
    "europcar": ("car rental", "ofran_car_prices"),
    "rentalcars": ("car rental", "ofran_car_prices"),
    "hertz": ("car rental", "ofran_car_prices"),
    "sicilybycar": ("car rental", "ofran_car_prices"),
    "priority pass": ("airport lounges", "lounge_prices (Aspire)"),
    "loungereview": ("airport lounges", "lounge_prices (Aspire)"),
    "mozio": ("transfers (connected)", "mozio_transfer_prices"),
    "kiwitaxi": ("transfers (connected)", "kiwitaxi_transfer_prices"),
    "iway": ("transfers (needs login)", "kiwitaxi_transfer_prices or mozio_transfer_prices (the connected transfer sources; iway needs the operator's login)"),
}


def _same_day_in_year(day: date, year: int) -> date:
    try:
        return day.replace(year=year)
    except ValueError:                      # 29 February in a non-leap year
        return day.replace(year=year, day=28)


def _next_occurrence(check_in: date, check_out: date, today: date) -> tuple[date, date] | None:
    """The same dates in the next year(s), when the operator gave no year and this year's dates have passed."""
    for add in (1, 2):
        start = _same_day_in_year(check_in, check_in.year + add)
        if start >= today:
            if (start - today).days > 540:
                return None
            return start, start + (check_out - check_in)
    return None


def _clean_text(value: str, what: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ToolError(f"{what} is empty.")
    return text[:200]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=PLAN_ONLY)
    @tool_errors
    async def hotel_prices(
        hotel_or_city: str,
        check_in: date,
        check_out: date,
        adults: int = 2,
        children_ages: list[int] | None = None,
        rooms: int = 1,
        meal_plan: Literal["BB", "RO", "HB", "FB", "AI"] = "BB",
    ) -> dict[str, Any]:
        """Hotel or room question: call task_plan('hotels') FIRST, then call ratehawk_hotels (RateHawk, one call, finished answer): find a hotel, room price, hotel availability, breakfast,
        cancellation terms, "find hotel X for these dates" (מלון). Hotel prices come from RateHawk and Arbitrip, which
        are websites read in the operator's Chrome with Claude in Chrome (never Booking.com, web search or other
        connectors). This tool returns NO prices: it checks the search and returns the exact search values for both
        sites and the playbook to follow; then do the search in the browser. Dates are the stay: check_in and
        check_out as YYYY-MM-DD. If the operator gave no year, pass the next future occurrence of those dates; a date
        in the past is moved to the next year and reported in `date_note`: repeat that note to the operator."""
        name = _clean_text(hotel_or_city, "hotel_or_city")
        today = date.today()
        if check_out <= check_in:
            raise ToolError("check_out must be after check_in.")
        date_note = None
        if check_in < today:
            moved = _next_occurrence(check_in, check_out, today)
            if moved is None:
                raise ToolError(f"check_in {check_in} is in the past (today is {today}) and the next occurrence is too far away. Ask the operator for the dates.")
            date_note = (f"{check_in} to {check_out} is in the past (today is {today}), so the next occurrence was used: "
                         f"{moved[0]} to {moved[1]}. Say which year you searched at the top of your answer.")
            check_in, check_out = moved
        nights = (check_out - check_in).days
        if nights > 30:
            raise ToolError("More than 30 nights: confirm the dates with the operator.")
        ages = list(children_ages or [])
        if not 1 <= adults <= 10 or not 1 <= rooms <= 5 or any(not 0 <= a <= 17 for a in ages):
            raise ToolError("adults must be 1-10, rooms 1-5 and children's ages 0-17.")
        rh_dates = f"{check_in.strftime('%d.%m.%Y')}-{check_out.strftime('%d.%m.%Y')}"
        ab_dates = f"check_in={check_in.strftime('%y%m%d')}&check_out={check_out.strftime('%y%m%d')}"
        plan: dict[str, Any] = {
            "required_next": "Call task_plan('hotels') if you have not, then ratehawk_hotels (the server reads RateHawk and returns the finished answer: show its `answer` unchanged). Only if it says RateHawk is not logged in, fall back to ratehawk_hotels_recipe. Arbitrip is read in Claude in Chrome.",
            "no_prices_here": "This tool gives no prices. Search RateHawk and Arbitrip in Claude in Chrome with the values below.",
            "search": {
                "destination": name, "check_in": check_in.isoformat(), "check_out": check_out.isoformat(), "nights": nights,
                "adults": adults, "children_ages": ages, "rooms": rooms, "meal_plan": f"{meal_plan} ({MEALS[meal_plan]})",
            },
            "ratehawk": {"site": "https://www.ratehawk.com/", "citizenship": "Israel (assumed; set it in the form unless the operator says otherwise)",
                         "dates_in_url": rh_dates},
            "arbitrip": {"site": "https://app.arbitrip.com/", "dates_in_url": ab_dates},
            "must_follow": [
                "Read ALL rates on BOTH sites (open every 'Show N more rates'); if you cannot, say 'N of M read' and never call a result 'the cheapest'.",
                "Match the request: a double room means a double, queen or king bed; Twin / 2 beds / bed type not guaranteed gets a warning and is not 'the cheapest double'.",
                "Compare on one basis: say for every row whether taxes are included or paid at the hotel, and the meal plan; anything you add up is 'calculated'.",
                "Label Cheapest, Best fit, Most flexible and one Recommended (with a one-line reason) for each site, side by side; see quote_guide('answer_format').",
                "Not found is not sold out: say a hotel is unavailable only when the site's own hotel page says so; if a search failed or the page was empty, write 'could not be read' and what failed.",
                "Say the 'On the spot' amount exactly as the page words it, on top of the NET price; do not name the tax and never write 'taxes included' next to it.",
            ],
            "browser": NO_BROWSER,
            "playbook": sections().get("hotels", ""),
            "end_your_answer_with": "Citizenship used, number of rates read, the time checked, and the link of each site you read.",
        }
        if date_note:
            plan["date_note"] = date_note
        return plan

    @mcp.tool(annotations=PLAN_ONLY)
    @tool_errors
    async def transfer_prices(from_place: str, to_place: str, transfer_date: date, passengers: int = 2) -> dict[str, Any]:
        """Private transfer, airport transfer, taxi or shuttle price question (call task_plan('transfers') first; for example
        "airport to hotel"). It returns NO price: it returns the playbook and points to kiwitaxi_transfer_prices and mozio_transfer_prices, the live
        price tools (Kiwitaxi first, Mozio where Kiwitaxi has no transfer or as a second price). Never estimate a transfer price or use web search."""
        return {
            "no_prices_here": "This returns no price. Call kiwitaxi_transfer_prices for live Kiwitaxi prices and mozio_transfer_prices for Mozio (use it where Kiwitaxi has no transfer). Never estimate a price and never use web search.",
            "request": {"from": _clean_text(from_place, "from_place"), "to": _clean_text(to_place, "to_place"),
                        "date": transfer_date.isoformat(), "passengers": passengers},
            "playbook": sections().get("transfers", ""),
        }

    @mcp.tool(annotations=PLAN_ONLY)
    @tool_errors
    async def other_source_prices(site_or_topic: str) -> dict[str, Any]:
        """USE THIS FIRST when the operator names a website or provider that has no tool here (Tripadvisor,
        Booking.com, Airbnb, Agoda, Skyscanner, El Al, Ryanair, easyJet, Sixt, Europcar, Rentalcars, Priority Pass,
        a hotel's own site, and similar; TAP, Israir, Mozio and Kiwitaxi have their own tools; Skyscanner and El Al are read in the operator's Chrome) or asks you to check "the web". It tells you what is not
        connected and which connected source to offer instead. It returns no prices. Never use web search or
        another connector to get a price."""
        wanted = _clean_text(site_or_topic, "site_or_topic").lower()
        hit = next((key for key in OTHER_SOURCES if key in wanted), None)
        what, instead = OTHER_SOURCES[hit] if hit else ("not in the agency's list", "the connected source for the same need")
        if hit in CONNECTED:
            return {"no_prices_here": "This returns no price: this source IS connected, call its tool. Never use web search or another connector for a price.",
                    "asked_for": site_or_topic.strip()[:200], "category": what, "offer_instead": instead, "playbook": sections().get("other_sources", "")}
        if hit in BROWSER_READ:
            return {"no_prices_here": "This returns no price. This source is read in the operator's own Chrome with Claude in Chrome (Skyscanner is comparison only), not by a tool. "
                                      "Never use web search or another connector for a price.",
                    "asked_for": site_or_topic.strip()[:200], "category": what, "offer_instead": instead,
                    "how": "Follow quote_guide('flights'): the Skyscanner and El Al sections. If no browser tool is available in this chat, say exactly: Please turn on Claude in Chrome for this chat.",
                    "playbook": sections().get("flights", "")}
        return {
            "no_prices_here": "This source is not connected. Do not use web search, another connector or a third-party site for prices.",
            "asked_for": site_or_topic.strip()[:200],
            "category": what,
            "offer_instead": instead,
            "also_offer": "The operator pastes the price, or (with her OK) you read that site in Claude in Chrome: search and read only, never book, stop at a login, captcha or block.",
            "playbook": sections().get("other_sources", ""),
        }

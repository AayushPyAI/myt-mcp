"""task_plan: the short, concrete work plan for ONE price request, built from the playbook and (when given) the trip.

The playbook is long and a language model reads parts of it. This tool is the part that cannot be skipped: it returns the
sources to read, the filters, the fields to collect, what to ask once, the shape of the answer and the final check, and when a
trip is given it fills in what MYT already holds (dates, travellers, flight legs and which sources can serve each leg).
It reads only the trip (never writes) and gives no prices.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.errors import tool_errors
from myt_mcp.myt.summaries import trip_summary
from myt_mcp.services import Services

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"]
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

ANSWER_SHAPE = [
    'Line 1: "Sources checked: <every source you read> | Not checked: <source> (reason: no browser tool in this chat / login, captcha or block / route not served) ".',
    'Line 2: "Filters used: <each filter> (operator | trip: what)".',
    "A table per leg or item with the fields below, 'not shown' or 'not read' for every field you do not have, and 'N of M read' per source.",
    "Picks: Cheapest, Best fit, Most flexible, Recommended (four rows; 'not determined: why' if one cannot be filled); every reason from a source, else 'my judgement'.",
    '"In MYT supplier?" for the Cheapest, Best fit and Recommended supplier (yes / no / not checked: why), by typing its name in Search supplier (trip 906 if no trip).',
    "Last: 'Sources:' one exact link per source and per leg (the tool's source/url or the Chrome page address), never a home page.",
    "Then call check_answer(draft, kind) and fix every item under `missing`; call it again until ok is true; only then send.",
]

COMMON_ASK = "Ask ONCE, in one message, for what MYT does not hold; never answer for the operator and never guess."

PLANS: dict[str, dict[str, Any]] = {
    "flights": {
        "ask_once": ["adults and children with their ages (MYT has only the number of travellers)", "direct only or connections allowed", "checked bag needed"],
        "sources": [
            {"name": "TAP Air Portugal", "how": "tap_flight_prices (and tap_fare_calendar)", "use": "legs touching Portugal and many European routes"},
            {"name": "SATA / Azores Airlines", "how": "sata_flight_prices", "use": "Azores, Madeira and mainland Portugal"},
            {"name": "Israir", "how": "israir_flight_prices", "use": "ONLY flights from or to Tel Aviv on its network; never Lisbon, Porto, Madeira or the Azores"},
            {"name": "El Al", "how": "Claude in Chrome (elal.com)", "use": "legs touching Israel"},
            {"name": "ITA Airways", "how": "Claude in Chrome (via RateHawk Air or Skyscanner)", "use": "legs touching Italy"},
            {"name": "RateHawk Air tickets", "how": "Claude in Chrome", "use": "EVERY leg"},
            {"name": "Skyscanner", "how": "Claude in Chrome, comparison only", "use": "EVERY leg: Best and Cheapest tabs together; price to quote comes from the airline's page"},
        ],
        "fields": ["flight number and operating airline", "times and stops", "the whole fare ladder (code and name)", "cabin bag and checked bag", "change and refund terms (only if the tool or page shows them)",
                   "price per adult and per child", "group total", "link"],
        "filters": "direct flights for a short leg (trip default) unless the operator says otherwise; the same filter on every source; show connecting flights only when no direct exists, marked 'connecting'.",
        "never": ["write a change fee, refund amount or bag weight a tool did not return (TAP returns none)", "retry a tool that timed out more than twice (try the city code once: PAR not CDG, then use the other sources)", "write what an airline 'typically' charges: say 'not shown'", "price a BATCH seat from a public fare", "call Israir for Lisbon, Porto, Madeira or the Azores"],
    },
    "hotels": {
        "ask_once": ["stars, budget per night and area / longest distance from the centre (when the trip has no hotel yet)", "meal plan and free cancellation: required or not", "adults and children's ages"],
        "sources": [
            {"name": "RateHawk", "how": "ratehawk_hotels_recipe (it asks the operator first, then you open its url and run its script in Claude in Chrome: 30 hotels a batch, offset for more), compose_answer with its wishes and filters_used", "use": "always"},
            {"name": "Arbitrip", "how": "arbitrip_hotels_recipe (same questions and wishes as RateHawk; open its url, run its script in Claude in Chrome; its rows are comparison only: the list price can be a non-refundable room, so read the hotel page of the hotels the operator wants)", "use": "always"},
            {"name": "the hotel's own site", "how": "Claude in Chrome, only for a hotel the operator names and with her OK", "use": "optional"},
        ],
        "fields": ["stars, score and reviews", "distance from the centre", "room and bed type", "meal plan", "cancellation (free until when)", "price basis (net or list, taxes, 'on the spot')", "availability", "link"],
        "filters": "only the operator's filters or the trip's hotels (stars, meal, budget); NEVER a review-score filter she did not name; the same filters on both sites; check every row against them.",
        "never": ["add a 'review 8+' filter", "call a hotel the cheapest when you read only part of the list or only the rating-sorted list (read the price-sorted list too)", "show a score without its number of reviews", "open detail pages before the operator picks hotels", "make a Cheapest outside the area the Recommended"],
    },
    "cars": {
        "ask_once": ["pick-up and return place and TIMES (from the trip's flights if it has them, else ask)", "gearbox, seats, excess cover required or not", "driver age"],
        "sources": [
            {"name": "Ofran", "how": "Claude in Chrome, the operator's logged-in tab", "use": "always; read the company from the logo's alt text; price is the agent price only if the results header shows the agent's name"},
            {"name": "RateHawk Car rental", "how": "Claude in Chrome", "use": "always"},
        ],
        "fields": ["rental company", "car and class", "gearbox", "seats and bags", "mileage", "excess and insurance", "fuel policy", "deposit", "pick-up place and hours", "cancellation", "total price", "link"],
        "filters": "the operator's (gearbox, excess) or the trip's car line; the same filters and the same times on both sites.",
        "never": ["choose a pick-up time yourself", "call a logged-out Ofran price 'net' or 'agent'", "copy a traveller's name"],
    },
    "transfers": {
        "ask_once": ["pick-up time (from the trip's flight, else ask)", "passengers: adults and children's ages (child seats)", "luggage"],
        "sources": [
            {"name": "RateHawk Transfers", "how": "Claude in Chrome", "use": "always"},
            {"name": "Kiwitaxi", "how": "kiwitaxi_transfer_prices", "use": "always; check matched_from and matched_to"},
            {"name": "Mozio", "how": "mozio_transfer_prices (pass pickup_time)", "use": "always"},
        ],
        "fields": ["vehicle and capacity (people, bags)", "price per vehicle", "waiting time", "cancellation", "provider", "meeting point", "pick-up time used"],
        "filters": "vehicles that fit the whole group and its bags; the same pick-up time on every source.",
        "never": ["let Mozio's default 12:00 decide the time", "type '3 adults' for '3 passengers'", "say 'roomier' when the capacities are equal"],
    },
    "trains": {
        "ask_once": ["adults and children's ages", "earliest departure time", "class"],
        "sources": [
            {"name": "Trenitalia", "how": "train_prices (use the city station, e.g. Roma Termini)", "use": "Italy"},
            {"name": "RateHawk Train tickets", "how": "Claude in Chrome", "use": "always"},
        ],
        "fields": ["train numbers and times", "class and fare", "change and refund terms", "seats left", "group total with the child rule", "link"],
        "filters": "direct first; the leg's day and cities from the itinerary.",
        "never": ["treat a 400 as 'too far ahead' (it can be the station pair)"],
    },
    "activities": {
        "ask_once": ["adults and children's ages", "time of day or duration wish"],
        "sources": [
            {"name": "GetYourGuide", "how": "getyourguide_find_activities and getyourguide_activity_details", "use": "always"},
            {"name": "Viator", "how": "viator_search_activities and viator_activity_details", "use": "always"},
        ],
        "fields": ["title", "duration", "start times for the date", "private or group", "language", "meeting point", "inclusions", "cancellation", "price by age for the group", "link"],
        "filters": "the activity named in the itinerary; free cancellation and rating only if the operator or the trip says so.",
        "never": ["describe an option from another option's answer"],
    },
    "lounges": {
        "ask_once": ["flight departure time", "adults and children"],
        "sources": [{"name": "Aspire Lounges", "how": "lounge_prices", "use": "always"}],
        "fields": ["lounge and terminal", "entry window against the flight", "length of stay", "adult and child price", "link"],
        "filters": "the entry window must fit the flight time.",
        "never": ["write opening hours or a menu the tool did not return"],
    },
}

ISRAEL = ("ben gurion", "tel aviv", "tlv")   # one airport: the only place name this planner matches; every other route is left to the tools' own answers


def _has(text: str, words: tuple[str, ...]) -> bool:
    low = f" {text.lower()} "
    return any(w in low for w in words)


def leg_sources(leg: dict[str, Any], israir_cities: list[str] | None = None) -> dict[str, Any]:
    """The sources to read for one flight leg of the trip. No list of countries or airports is kept here: every tool answers for itself
    (an honest "route not sold" is the reason for 'Not checked'), and Israir's live list of cities is passed in."""
    a, b = str(leg.get("from") or ""), str(leg.get("to") or "")
    both = f"{a} / {b}"
    read = ["RateHawk Air tickets (Chrome)", "Skyscanner (Chrome, comparison)",
            "tap_flight_prices (if it does not sell the route its answer says so: that is the reason)",
            "sata_flight_prices (same)"]
    if _has(both, ISRAEL):
        read += ["El Al (Chrome)", "israir_flight_prices ONLY if the other end's city code is in `israir_sells`; if it is not, write 'Israir does not sell it'"]
    out: dict[str, Any] = {"leg": f"{a} -> {b}", "flight_in_mytrip": leg.get("flight"), "departure": leg.get("departure"), "read": read,
                           "also": "If either end is in Italy also read ITA Airways (through RateHawk Air or Skyscanner); read every source that can serve this route, not only these."}
    if israir_cities is not None and _has(both, ISRAEL):
        out["israir_sells"] = israir_cities
    if "batch" in str(leg.get("note") or "").lower():
        out["batch_seat"] = "agency block seat: public fares are comparison only; the price comes from the operator"
    return out


def trip_block(trip: dict[str, Any]) -> dict[str, Any]:
    return {"trip_number": trip.get("number"), "name_is_not_to_be_copied": True, "dates": f"{trip.get('start')} to {trip.get('end')}",
            "paying_travellers": trip.get("paying_participants"), "ages_known": False, "status": trip.get("status"),
            "quotation": trip.get("quotation"),
            "first_check": "get_supplier_reservations: if there are none, say so at the top (Planning and reservations are the operator's step before the quote)"}


def build_plan(kind: str, trip: dict[str, Any] | None = None, israir_cities: list[str] | None = None) -> dict[str, Any]:
    plan = PLANS[kind]
    out: dict[str, Any] = {
        "kind": kind, "follow_this": "This plan is part of the rules: do every step. Details of each rule: quote_guide(...) topics named below.",
        "ask_once": {"rule": COMMON_ASK, "questions": plan["ask_once"]},
        "sources_to_read": plan["sources"], "filters": plan["filters"], "fields_to_read_for_every_option": plan["fields"],
        "never": plan["never"], "answer_shape": ANSWER_SHAPE,
        "more": ["quote_guide('answer_format')", "quote_guide('source_data')", f"quote_guide('{ {'flights': 'flights', 'hotels': 'hotels', 'cars': 'cars', 'transfers': 'transfers', 'trains': 'trains', 'activities': 'activities', 'lounges': 'lounges'}[kind] }')"],
        "final_step": f'check_answer(draft, kind="{kind}") until ok is true',
    }
    if trip:
        out["trip"] = trip_block(trip)
        if kind == "flights":
            out["legs_of_the_trip"] = [leg_sources(f, israir_cities) for f in trip.get("flights", [])]
            out["legs_note"] = "Price every leg; for a leg with no direct flight on any source, show connecting options marked 'connecting'."
    else:
        out["trip"] = "No trip given: ask the operator for the dates, travellers and places, or pass trip_id (from find_trip) to fill them in."
    return out


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def task_plan(kind: Kind, trip_id: int | None = None) -> dict[str, Any]:
        """CALL THIS FIRST for any price request (flights, hotels, cars, transfers, trains, activities, lounges) and follow it step by step.
        It returns, for that kind of request: what to ask the operator once, EVERY source to read (tools and Chrome sites), the filters,
        the fields to collect for each option, what never to do, the shape of the answer, and the final step (check_answer). With
        `trip_id` (from find_trip) it also fills in the trip's dates, travellers and, for flights, each leg with the sources that can and
        cannot serve it. It gives no prices and changes nothing."""
        trip = None
        if trip_id is not None:
            services.check_trip(trip_id)
            v3 = await services.myt().get_trip_v3(trip_id)
            if (v3.get("trip") or {}).get("trip_id") != trip_id:
                raise ToolError(f"MYT returned another trip than {trip_id}; nothing was planned.")
            trip = trip_summary(v3)
        cities: list[str] | None = None
        if kind == "flights" and trip:
            try:
                cities = sorted((await services.israir().cities()).keys())
            except Exception:    # Israir down or switched off: the plan still works, the tool will say what it sells
                cities = None
        return build_plan(kind, trip, cities)

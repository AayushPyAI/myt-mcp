"""Private airport and city transfers (Kiwitaxi, Mozio)."""

from __future__ import annotations

import re
from datetime import date, time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.kiwitaxi.parse import check_results
from myt_mcp.mozio.parse import check_offers, parse_polls
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _today() -> date:
    return date.today()


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def kiwitaxi_transfer_prices(from_place: str, to_place: str, travel_date: date, passengers: int = 2,
                                       from_match: int = 0, to_match: int = 0) -> dict[str, Any]:
        """Private transfer prices (airport to hotel, hotel to airport, city to city) from Kiwitaxi: every vehicle class with its
        price for the WHOLE vehicle one way in EUR, how many passengers and standard bags it takes, and its free-cancellation rule.
        `from_place` and `to_place` are free text: an airport name or code ("Fiumicino", "PDL"), a hotel name or a street address
        with the city ("Hotel Berchielli Florence"). The answer says which place Kiwitaxi matched for each (`matched_from`,
        `matched_to`, with address): check them against the trip's hotel, and if one is wrong call again with the next
        number in `from_match` / `to_match` (0 = first suggestion, `other_from` / `other_to` list the alternatives).
        `passengers` = everyone travelling (children included). The price does not depend on the pick-up time here; the time is
        chosen when booking. Nothing is booked."""
        if not from_place.strip() or not to_place.strip():
            raise ToolError("from_place and to_place need a place name, e.g. 'Fiumicino' and 'Room Mate Collection Mia Rome'.")
        if len(from_place) > 120 or len(to_place) > 120:
            raise ToolError("from_place and to_place are too long; use a short name or address.")
        if travel_date < _today():
            raise ToolError("travel_date is in the past.")
        if not 1 <= passengers <= 16:
            raise ToolError("passengers must be between 1 and 16.")
        if not 0 <= from_match <= 4 or not 0 <= to_match <= 4:
            raise ToolError("from_match and to_match must be between 0 and 4.")
        found = await services.kiwitaxi().search(from_place, to_place, travel_date, passengers, from_match, to_match)
        matched = {"matched_from": {"name": found["chosen_from"]["title"], "address": found["chosen_from"].get("address")},
                   "matched_to": {"name": found["chosen_to"]["title"], "address": found["chosen_to"].get("address")},
                   "other_from": found["other_from"], "other_to": found["other_to"]}
        if not found["offers"] and not found["route"]["date"]:
            return {"date": travel_date.isoformat(), "passengers": passengers, **matched, "offers": [], "source": found["url"],
                    "note": "Kiwitaxi shows no private transfer between these two places (for example a long ride to a village). Check that the places matched are the "
                            "right ones (`other_from` / `other_to` list the alternatives); if they are, Kiwitaxi cannot price this leg: ask the operator for another source."}
        ensure("Kiwitaxi", check_results(found, travel_date, passengers))
        offers = sorted([o for o in found["offers"] if o["price"] is not None], key=lambda o: (o["price"], -(o["max_passengers"] or 0)))
        fits = [o for o in offers if (o["max_passengers"] or 0) >= passengers]
        for o in offers:
            o["fits_group"] = (o["max_passengers"] or 0) >= passengers
        route = found["route"]
        answer: dict[str, Any] = {
            "date": travel_date.isoformat(), "passengers": passengers, "prices_are": "per vehicle (the whole group), one way, in EUR",
            **matched, "approx_driving_time": (route.get("driving_time") or "").replace("~", "").strip() or None, "offers": offers,
            "at_a_glance": {"cheapest_that_fits": fits[0] if fits else None,
                            "note": "Among the vehicles that take all passengers; luggage is not counted: check `max_standard_bags` against the group's bags."},
            "payment_note": "Kiwitaxi may ask for a small prepayment online and the rest in cash to the driver; the page's own wording decides: check it at booking.",
            "source": found["url"],
        }
        if not fits:
            answer["note"] = "No vehicle class on the page takes this many passengers; ask the operator about two vehicles."
        if route.get("to_address") and route["to_address"] != found["chosen_to"].get("address"):
            answer["page_destination"] = route["to_address"]
        return answer

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def mozio_transfer_prices(from_place: str, to_place: str, travel_date: date, passengers: int = 2, pickup_time: str | None = None,
                                    max_results: int = 12) -> dict[str, Any]:
        """Private transfer prices from Mozio (mozio.com, a marketplace of local providers): every vehicle offer (sedan, van, bus,
        business class) with the price for the WHOLE booking one way in EUR, passengers and bags it takes, provider and rating,
        driving time, free-cancellation rule, waiting time included and what is included. Use it where Kiwitaxi has no transfer
        (for example Ponta Delgada airport <-> Furnas) or as a second price. `from_place` / `to_place`: an airport code ("PDL",
        "FCO"), or a place, hotel name or address with the town ("Terra Nostra Garden Hotel, Furnas, Portugal"). The answer says
        what Mozio matched for each (`matched_from`, `matched_to`): check it is the right place; `only_the_town` true means Mozio
        priced to the centre of the town, not to a street address, so give the hotel's name and address for an exact price.
        `passengers` = everyone travelling. `pickup_time` is 24-hour HH:MM; if you leave it out 12:00 is used and the answer says so (`pickup_time_was_default`):
        the price can differ by time of day, so give the real time from the flight, or ask the operator. A busy route can have 40+ offers: `max_results` (1-50, default 12) shows the cheapest private offers
        that take the whole group, ranked; `coverage` says how many Mozio listed. Scheduled shuttle buses (per-person tickets on fixed
        times) are not private transfers and are not priced here. Takes about 20 seconds. Nothing is booked."""
        if not 1 <= max_results <= 50:
            raise ToolError("max_results must be between 1 and 50.")
        if not from_place.strip() or not to_place.strip():
            raise ToolError("from_place and to_place need a place: an airport code like PDL, or a hotel name with the town.")
        if len(from_place) > 150 or len(to_place) > 150:
            raise ToolError("from_place and to_place are too long; use a short name or address.")
        if travel_date < _today():
            raise ToolError("travel_date is in the past.")
        if not 1 <= passengers <= 16:
            raise ToolError("passengers must be between 1 and 16.")
        pickup_was_default = pickup_time is None
        pickup_time = "12:00" if pickup_was_default else pickup_time
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", pickup_time.strip())
        if not m:
            raise ToolError("pickup_time must be 24-hour HH:MM, for example 14:30.")
        pickup = time(int(m.group(1)), int(m.group(2)))
        found = await services.mozio().search(from_place, to_place, travel_date, pickup, passengers)
        parsed = parse_polls(found["polls"])
        ensure("Mozio", check_offers(parsed, travel_date, passengers, "EUR"))
        base = {"date": travel_date.isoformat(), "pickup_time": pickup_time.strip(), "passengers": passengers,
                "matched_from": parsed["from"], "matched_to": parsed["to"], "source": found["url"]}
        if pickup_was_default:
            base["pickup_time_was_default"] = ("No pick-up time was given, so 12:00 was used. Say so, and use the same time on every source: take it from the trip's flight, "
                                               "or ask the operator once.")
        if not parsed["offers"]:
            return {**base, "offers": [], "note": "Mozio shows no transfer between these two places for this date and time (no provider covers it, or the "
                                                   "place was not understood). Check `matched_from` / `matched_to`; if they are right, ask the operator for another source."}
        private = sorted([o for o in parsed["offers"] if not o["scheduled_shuttle"]], key=lambda o: (o["price_total"], -(o["max_passengers"] or 0)))
        shuttles = len(parsed["offers"]) - len(private)
        fits = [o for o in private if (o["max_passengers"] or 0) >= passengers]
        shown = fits[:max_results]
        for rank, o in enumerate(shown, 1):
            o["rank"] = rank
            o["fits_group"] = True
            o.pop("scheduled_shuttle")
        answer: dict[str, Any] = {
            **base, "prices_are": "per booking (the whole group in one vehicle unless `vehicles` says more), one way, in EUR, with Mozio's small platform fee included",
            "sorted_by": "price (cheapest first)",
            "coverage": {"offers_read": len(parsed["offers"]), "private_offers": len(private), "fit_the_group": len(fits), "shown": len(shown), "scheduled_shuttles_not_priced": shuttles},
            "offers": shown,
            "at_a_glance": {"cheapest_that_fits": shown[0] if shown else None,
                            "note": "Cheapest private offer that takes all passengers; luggage is not counted: check `max_bags` against the group's bags. Cheaper offers are often "
                                    "a smaller class or a longer cancellation notice: compare `free_cancellation_hours_before` too."},
            "payment_note": "Mozio takes payment online when booking; the page's own wording decides: check it at booking.",
        }
        if len(fits) > len(shown):
            answer["more_offers_note"] = f"{len(fits) - len(shown)} more offers that fit the group exist; raise max_results to see them."
        if shuttles:
            answer["shuttle_note"] = (f"Mozio also lists {shuttles} scheduled shuttle bus service(s) with per-person tickets on fixed times; they are not private transfers "
                                      "and are not priced here. Mention them only if the operator wants a cheap shared option, and check the price on mozio.com.")
        only_town = [name for name, place in (("pick-up", parsed["from"]), ("drop-off", parsed["to"])) if place["only_the_town"]]
        if only_town:
            answer["address_note"] = (f"The {' and '.join(only_town)} is priced to the centre of the town, not to a street address: the price can change with the exact "
                                      "address. Call again with the hotel's name and address for a closer price.")
        if not fits:
            answer["note"] = "No private offer takes this many passengers in one vehicle; ask the operator about two vehicles."
        return answer

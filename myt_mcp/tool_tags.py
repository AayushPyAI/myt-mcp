"""One short tag in front of every recipe tool's description: the KIND of price it reads and the words an operator or a tool search would use for it.

A recipe's own description starts with the site ("FOR BOOKING.COM FLIGHTS ..."), so a search for "car rental" or "טיסה" could miss a site whose name says nothing about the kind (Ofran, Skyscanner, Kiwitaxi...).
The tag is added in ONE place, after every tool is registered, so a new recipe cannot forget its words: tests/test_tool_budget.py fails for a recipe that has no kind here.
"""

from __future__ import annotations

from typing import Any

KINDS: dict[str, str] = {
    "hotels": "HOTELS (hotel, room, stay, accommodation, breakfast, מלון)",
    "flights": "FLIGHTS (flight, airline, fare, air ticket, טיסה)",
    "cars": "CAR RENTAL (rent a car, vehicle, pick-up, השכרת רכב)",
    "activities": "ACTIVITIES (tour, attraction, excursion, activity ticket, פעילות)",
    "trains": "TRAINS (train, rail ticket, רכבת)",
    "transfers": "TRANSFERS (airport transfer, taxi, shuttle, העברה)",
}
KIND_OF: dict[str, str] = {
    **dict.fromkeys(("arbitrip_hotels_recipe", "arbitrip_rooms_recipe", "bensaude_hotels_recipe", "ratehawk_hotels_recipe"), "hotels"),
    **dict.fromkeys(("booking_flights_recipe", "elal_recipe", "ratehawk_air_recipe", "sata_recipe", "skyscanner_recipe", "tap_recipe"), "flights"),
    **dict.fromkeys(("europcar_cars_recipe", "ofran_recipe", "ratehawk_cars_recipe", "rentalcars_cars_recipe"), "cars"),
    **dict.fromkeys(("booking_attractions_recipe", "booking_attraction_recipe", "getyourguide_find_recipe", "getyourguide_activity_recipe", "viator_find_recipe", "viator_activity_recipe"), "activities"),
    **dict.fromkeys(("cp_trains_recipe", "ratehawk_trains_recipe"), "trains"),
    **dict.fromkeys(("ratehawk_transfers_recipe", "iway_transfers_recipe"), "transfers"),
}


def tag_tools(mcp: Any) -> None:
    for name, tool in mcp._tool_manager._tools.items():
        kind = KIND_OF.get(name)
        if kind and not (tool.description or "").startswith("["):
            tool.description = f"[{KINDS[kind]}] " + (tool.description or "")

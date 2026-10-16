"""Mozio search answers -> the transfer offers for one route, date and group.

mozio.com/v2/en-us/search creates a search (POST api.mozio.com/v2/search/) and then polls it (GET .../<id>/poll/)
until `more_coming` is false; each poll carries the results found so far. A result is one vehicle offer: the total price
for the whole booking, the vehicle (type, passengers, bags), the provider, the duration, the cancellation policy and what
is included. The answer also says which places Mozio matched for the two addresses.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from myt_mcp.checks import close


def _money(block: Any) -> float | None:
    try:
        return round(float((block or {})["value"]), 2)
    except (KeyError, TypeError, ValueError):
        return None


def _place(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    return {"name": raw.get("formatted_address") or raw.get("custom_name") or raw.get("full_address"), "type": raw.get("type"),
            "airport_code": raw.get("iata_code") or None, "city": raw.get("city") or None, "country": raw.get("country") or None,
            "only_the_town": bool(raw.get("is_incomplete"))}


def _offer(raw: dict[str, Any]) -> dict[str, Any] | None:
    steps = [s for s in raw.get("steps") or [] if isinstance(s, dict) and s.get("main")] or [s for s in raw.get("steps") or [] if isinstance(s, dict)]
    if not steps:
        return None
    d = steps[0].get("details") or {}
    vehicle = d.get("vehicle") or {}
    prices = raw.get("total_price") or {}
    total = _money(prices.get("total_price"))
    if total is None:
        return None
    provider = d.get("provider") or {}
    policy = [p for p in (d.get("cancellation") or {}).get("policy") or [] if isinstance(p, dict)]
    free = [p for p in policy if p.get("refund_percent") == 100]
    times = (d.get("alternative_times") or {}).get("options") or []
    default = times[(d.get("alternative_times") or {}).get("default_index") or 0] if times else {}
    amenities = [a for a in d.get("amenities") or [] if isinstance(a, dict)]
    return {
        "vehicle_type": (vehicle.get("vehicle_type") or {}).get("name"), "vehicle_class": (vehicle.get("vehicle_class_detail") or {}).get("display_name"),
        "max_passengers": vehicle.get("max_passengers"), "max_bags": vehicle.get("max_bags"), "vehicles": vehicle.get("num_vehicles"),
        "price_total": total, "price_without_platform_fee": _money(prices.get("total_price_without_platform_fee")), "platform_fee": _money(prices.get("platform_fee")),
        "currency": (prices.get("total_price") or {}).get("currency"),
        "provider": provider.get("display_name") or d.get("provider_name"), "provider_rating": provider.get("rating_with_decimals"),
        "provider_rating_count": provider.get("rating_count"),
        "duration_minutes": d.get("time"), "departure": (d.get("departure_datetime") or "")[:16].replace("T", " ") or None,
        "arrival": (default.get("arrival_datetime") or "")[:16].replace("T", " ") or None,
        "free_cancellation_hours_before": max((p.get("notice") for p in free if isinstance(p.get("notice"), (int, float))), default=None),
        "cancellation_policy": [{"hours_before": p.get("notice"), "refund_percent": p.get("refund_percent")} for p in policy],
        "waiting_minutes_included": (d.get("wait_time") or {}).get("minutes_included"),
        "tolls_included": (d.get("price") or {}).get("tolls_included"), "gratuity_included": (d.get("price") or {}).get("gratuity_included"),
        "included": [a.get("name") for a in amenities if a.get("included")],
        "extras_on_request": [{"name": a.get("name"), "price": _money(a.get("price"))} for a in amenities if not a.get("included")],
        "flight_number_needed": d.get("flight_info_required"), "bookable": d.get("bookable"),
        "scheduled_shuttle": bool(d.get("ticket_types")) or (vehicle.get("vehicle_type") or {}).get("name") == "Bus",   # per-person tickets on fixed times, not a private vehicle
    }


def parse_polls(polls: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge every poll answer of one search: {offers, from, to, currency, passengers, pickup, finished}."""
    found: dict[str, dict[str, Any]] = {}
    for poll in polls:
        for raw in poll.get("results") or []:
            if isinstance(raw, dict) and raw.get("result_id") not in found:
                offer = _offer(raw)
                if offer:
                    found[raw["result_id"]] = offer
    last = polls[-1] if polls else {}
    return {"offers": list(found.values()), "from": _place(last.get("start_location")), "to": _place(last.get("end_location")),
            "currency": (last.get("currency_info") or {}).get("code"), "passengers": last.get("num_passengers"),
            "pickup": (last.get("pickup_datetime") or "")[:16].replace("T", " ") or None, "finished": last.get("more_coming") is False}


def check_offers(parsed: dict[str, Any], day: date, passengers: int, currency: str) -> list[str]:
    """Problems that mean the answer does not belong to the search that was asked (empty = fine)."""
    problems = []
    if not parsed["finished"]:
        problems.append("Mozio had not finished searching")
    if parsed["passengers"] != passengers:
        problems.append(f"it is for {parsed['passengers']} passengers, not {passengers}")
    if parsed["pickup"] and parsed["pickup"][:10] != day.isoformat():
        problems.append(f"the pick-up day is {parsed['pickup'][:10]}, not {day.isoformat()}")
    if parsed["currency"] != currency:
        problems.append(f"prices are in {parsed['currency']}, not {currency}")
    for o in parsed["offers"]:
        if o["currency"] != currency:
            problems.append(f"an offer is priced in {o['currency']}")
        if o["departure"] and o["departure"][:10] != day.isoformat():
            problems.append(f"an offer departs on {o['departure'][:10]}, not {day.isoformat()}")
        if o["price_without_platform_fee"] is not None and o["platform_fee"] is not None and not close(o["price_without_platform_fee"] + o["platform_fee"], o["price_total"]):
            problems.append(f"{o['vehicle_type']} price {o['price_total']} does not add up")
    return list(dict.fromkeys(problems))

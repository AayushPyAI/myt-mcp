"""TAP Air Portugal availability answer -> flights with their fares and the price for the whole group.

The booking page (booking.flytap.com) calls /bfm/rest/booking/availability/search; its answer lists every outbound flight
(`listOutbound`: segments with carrier, number, airports and local times) and every fare offer (`offers.listOffers`:
fare family, total and per passenger type, bag and refund flags), each flight pointing at its offers by id.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from myt_mcp.checks import close


def _local(stamp: str | None) -> str | None:
    """'2027-03-06T12:20:00.000Z' -> '2027-03-06 12:20' (TAP sends local times with a Z)."""
    return stamp[:16].replace("T", " ") if isinstance(stamp, str) and len(stamp) >= 16 else None


def _flag(values: Any) -> bool | None:
    """The offer lists one flag per segment; the fare is only as good as its worst segment."""
    flags = [v for v in values or [] if isinstance(v, bool)]
    return all(flags) if flags else None


def _offer(raw: dict[str, Any]) -> dict[str, Any]:
    out = raw.get("outbound") or {}
    total = raw.get("totalPrice") or {}
    per_type = {p.get("typePax"): p.get("price") for p in raw.get("listPaxPrice") or [] if isinstance(p, dict)}
    seats = [g.get("seatOutBound") for g in raw.get("groupFlights") or [] if isinstance(g, dict) and g.get("seatOutBound") is not None]
    return {
        "fare_code": raw.get("outFareFamily"), "cabin": (out.get("cabin") or [None])[0],
        "price_total": total.get("price"), "price_base": total.get("basePrice"), "price_taxes": total.get("tax"),
        "price_per_passenger_type": per_type, "checked_bag_included": _flag(out.get("bagIncluded")), "refundable": _flag(out.get("refundable")),
        "seats_left": min(seats) if seats else None, "fare_basis": [b for b in out.get("fareBasis") or []],
    }


def parse_availability(answer: dict[str, Any]) -> dict[str, Any]:
    data = answer.get("data") or {}
    offers = {o["idOffer"]: o for o in ((data.get("offers") or {}).get("listOffers") or []) if isinstance(o, dict) and "idOffer" in o}
    flights = []
    for fl in data.get("listOutbound") or []:
        segments = [{
            "flight": f"{s.get('carrier') or ''}{s.get('flightNumber') or ''}", "operated_by": s.get("operationCarrier") if s.get("operationCarrier") != s.get("carrier") else None,
            "from": s.get("departureAirport"), "to": s.get("arrivalAirport"), "departure": _local(s.get("departureDate")), "arrival": _local(s.get("arrivalDate")),
            "aircraft": s.get("equipment"), "departure_terminal": s.get("departureTerminal"),
        } for s in fl.get("listSegment") or [] if isinstance(s, dict)]
        fares = sorted((_offer(offers[i]) for i in fl.get("relateOffer") or [] if i in offers), key=lambda f: (f["price_total"] is None, f["price_total"] or 0))
        if not segments or not fares:
            continue
        flights.append({"stops": fl.get("numberOfStops"), "duration_minutes": fl.get("duration"), "segments": segments, "fares": fares,
                        "cheapest_total": fares[0]["price_total"]})
    flights.sort(key=lambda f: (f["cheapest_total"] is None, f["cheapest_total"] or 0, f["duration_minutes"] or 0))
    passengers = {p.get("paxType"): p.get("paxNum") for p in data.get("listPaxNum") or [] if isinstance(p, dict)}
    return {"currency": (data.get("offers") or {}).get("currency"), "passengers": passengers, "flights": flights, "not_available": bool(data.get("notAvailable"))}


def split_by_origin(parsed: dict[str, Any], origin: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(flights that start at `origin`, offers that start elsewhere): TAP also sells flights with a train leg from a station
    (for example ZMS, Florence station) under the same search; those are listed apart, not mixed with the flights from the airport."""
    same = [f for f in parsed["flights"] if f["segments"][0]["from"] == origin]
    return same, [f for f in parsed["flights"] if f["segments"][0]["from"] != origin]


def check_availability(parsed: dict[str, Any], origin: str, destination: str, day: date, adults: int, children: int, infants: int, currency: str) -> list[str]:
    """Each flight must run the asked route on the asked day for the asked group, in the asked currency, and the totals must add up."""
    problems = []
    want = {"ADT": adults, **({"CHD": children} if children else {}), **({"INF": infants} if infants else {})}
    if {k: v for k, v in parsed["passengers"].items() if v} != want:
        problems.append(f"the answer is for passengers {parsed['passengers']}, not {want}")
    if parsed["flights"] and parsed["currency"] != currency:
        problems.append(f"prices are in {parsed['currency']}, not {currency}")
    for fl in parsed["flights"]:
        first, last = fl["segments"][0], fl["segments"][-1]
        name = "+".join(s["flight"] for s in fl["segments"])
        if last["to"] != destination:
            problems.append(f"flight {name} ends at {last['to']}, not {destination}")
        if not (first["departure"] or "").startswith(day.isoformat()):
            problems.append(f"flight {name} departs {first['departure']}, not on {day.isoformat()}")
        for fare in fl["fares"]:
            types = fare["price_per_passenger_type"]
            expected = sum(types.get(k, 0) * n for k, n in want.items())
            if fare["price_total"] is None or (types and not close(expected, fare["price_total"], 0.05)):
                problems.append(f"flight {name}, fare {fare['fare_code']}: total {fare['price_total']} does not add up from the fares per passenger ({expected})")
                break
    return problems

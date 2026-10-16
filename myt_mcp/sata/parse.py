"""SATA's flight search answer (ibe/pricedAvailability) -> flight options, cheapest first.

How the answer fits together:
- bounds[i].sectors[0].sectorSolutions = the flights of one direction, each with an `id`
- every priced combination is in itineraryInfoDictionary under "<flightId>_<fareFamilyId>", joined with "#"
  for a round trip (outbound#return), with the total for the whole group and per passenger type
- cabins[].fareFamilies = the fares (code + what is included: bags, changes, refunds)
"""

from __future__ import annotations

from typing import Any

from myt_mcp.checks import close

PAX = {"ADT": "adults", "CHD": "children", "INF": "infants"}
BENEFITS = {
    "CARRYON_BAGS": "hand_luggage", "CHECKED_BAGS": "checked_bag", "PREPAID_BAGGAGE": "checked_bag_price",
    "TICKET_CHANGE_BEFORE_DEPARTURE": "change", "TICKET_REFUND_BEFORE_DEPARTURE": "refund", "SEAT_SELECTION": "seat",
}


def _flight(solution: dict[str, Any]) -> dict[str, Any]:
    segments = solution.get("segments") or []
    return {
        "flights": [f"{s.get('marketingAirlineCode')} {s.get('flightNumber')}" for s in segments],
        "from": solution.get("originAirport"),
        "to": solution.get("destinationAirport"),
        "departs": (solution.get("startDate") or "").replace("T", " ")[:16],
        "arrives": (solution.get("endDate") or "").replace("T", " ")[:16],
        "duration_minutes": solution.get("duration"),
        "stops": max(len(segments) - 1, 0),
    }


def fare_families(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """id -> {fare, cabin, conditions}."""
    families = {}
    for cabin in data.get("cabins") or []:
        for f in cabin.get("fareFamilies") or []:
            conditions = {}
            for b in f.get("fareBenefits") or []:
                label = BENEFITS.get(b.get("code"))
                if label:
                    status = (b.get("inclusionStatus") or "").replace("_", " ").lower()
                    conditions[label] = f"{b.get('value')} ({status})" if status else b.get("value")
            families[f["id"]] = {"fare": f.get("code"), "cabin": cabin.get("code"), "conditions": conditions}
    return families


def _varied(options: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Cheapest first, but each outbound flight once before any repeats, so a round trip doesn't show the
    same outbound with three different returns."""
    first, rest, seen = [], [], set()
    for o in options:
        outbound = tuple(o["legs"][0]["flights"])
        (rest if outbound in seen else first).append(o)
        seen.add(outbound)
    return sorted((first + rest)[:limit], key=options.index)


def summarize_availability(answer: dict[str, Any], max_results: int) -> dict[str, Any]:
    data = answer.get("data") or {}
    flights = {s["id"]: _flight(s) for b in data.get("bounds") or [] for sector in b.get("sectors") or []
               for s in sector.get("sectorSolutions") or [] if isinstance(s, dict) and "id" in s}
    families = fare_families(data)
    # (flight ids) -> {(fare ids): itinerary}
    groups: dict[tuple[int, ...], dict[tuple[int, ...], dict[str, Any]]] = {}
    for key, itinerary in (data.get("itineraryInfoDictionary") or {}).items():
        try:
            parts = [tuple(int(x) for x in part.split("_")) for part in key.split("#")]
        except ValueError:
            continue
        if not all(len(p) == 2 and p[0] in flights for p in parts) or not (itinerary.get("totalTripPrice") or {}).get("cash"):
            continue
        groups.setdefault(tuple(p[0] for p in parts), {})[tuple(p[1] for p in parts)] = itinerary

    options = []
    for flight_ids, fares in groups.items():
        cheapest_fares, cheapest = min(fares.items(), key=lambda kv: kv[1]["totalTripPrice"]["cash"])
        option = {
            "total_price": cheapest["totalTripPrice"]["cash"],
            "per_passenger_type": {PAX.get(t, t): v.get("cash") for t, v in (cheapest.get("totalPricePerPaxType") or {}).items()},
            "legs": [{**flights[fid], "fare": families.get(ff, {}).get("fare")} for fid, ff in zip(flight_ids, cheapest_fares)],
            # the same fare on every leg (e.g. all "BSC"): what each fare costs on these flights
            "price_by_fare": {families[ffs[0]]["fare"]: it["totalTripPrice"]["cash"] for ffs, it in sorted(fares.items(), key=lambda kv: kv[1]["totalTripPrice"]["cash"])
                              if len(set(ffs)) == 1 and ffs[0] in families},
        }
        options.append(option)
    # same price: fewer stops, then shorter journey, then earlier departure
    options.sort(key=lambda o: (o["total_price"], sum(leg["stops"] for leg in o["legs"]),
                                sum(leg["duration_minutes"] or 0 for leg in o["legs"]), tuple(leg["departs"] for leg in o["legs"])))
    chosen = _varied(options, max_results)
    used = {leg["fare"] for o in chosen for leg in o["legs"]} | {f for o in chosen for f in o["price_by_fare"]}
    conditions = {f["fare"]: {"cabin": f["cabin"], **f["conditions"]} for f in families.values() if f["fare"] in used}
    answer: dict[str, Any] = {
        "currency": data.get("currency"),
        "options": chosen,
        "total_options": len(options),
        "fare_conditions": conditions,
        "fare_names_note": "SATA's data gives fare codes only (e.g. SPL, BSC); use the code with its fare_conditions, not a made-up fare name.",
    }
    if len(options) > len(chosen):
        cheapest_other = min((o["total_price"] for o in options if o not in chosen), default=None)
        answer["note"] = (f"Showing {len(chosen)} of {len(options)} options: the cheapest option for each different outbound flight, so these are "
                          "NOT necessarily the cheapest ones (the same outbound with another return or fare can be cheaper)"
                          f"{f'; the cheapest option not shown costs {cheapest_other}' if cheapest_other is not None else ''}. Never call the shown "
                          f"list \"the cheapest {len(chosen)}\". Tell the operator how many more there are and offer to show more with a higher max_results.")
    if any("*" in str(v) for c in conditions.values() for v in c.values()):
        answer["fine_print"] = ("An asterisk (*) after a condition means SATA attaches conditions to it (for example a fare difference or "
                                "limits). Say \"conditions apply\" for it; never call it free or unconditional.")
    return answer


def check_answer(answer: dict[str, Any], origin: str, destination: str, departure: str, return_date: str | None,
                 travellers: dict[str, int]) -> list[str]:
    """What doesn't match the search: route and dates per direction, travellers, currency, totals."""
    data = answer.get("data") or {}
    problems = []
    if data.get("currency") not in (None, "EUR"):
        problems.append(f"prices are in {data.get('currency')}, not EUR")
    wanted = [(origin, destination, departure)] + ([(destination, origin, return_date)] if return_date else [])
    bounds = data.get("bounds") or []
    if bounds and len(bounds) != len(wanted):
        problems.append(f"{len(bounds)} directions instead of {len(wanted)}")
    for bound, (frm, to, day) in zip(bounds, wanted):
        if (bound.get("origin"), bound.get("destination"), bound.get("startDate")) != (frm, to, day):
            problems.append(f"got {bound.get('origin')}->{bound.get('destination')} on {bound.get('startDate')} instead of {frm}->{to} on {day}")
        for sector in bound.get("sectors") or []:
            for s in sector.get("sectorSolutions") or []:
                if (s.get("startDate") or "")[:10] != day or s.get("originAirport") != frm or s.get("destinationAirport") != to:
                    problems.append(f"flight {s.get('originAirport')}->{s.get('destinationAirport')} on {(s.get('startDate') or '')[:10]} is not the asked route/day")
                    break
    expected_pax = {code: travellers[field] for code, field in PAX.items() if travellers.get(field)}
    for key, it in (data.get("itineraryInfoDictionary") or {}).items():
        pax = {k: v for k, v in (it.get("numberOfPassengersPerPaxType") or {}).items() if v}
        if pax != expected_pax:
            problems.append(f"priced for {pax} instead of {expected_pax}")
            break
        total = (it.get("totalTripPrice") or {}).get("cash")
        parts = [v.get("cash") for v in (it.get("totalPricePerPaxType") or {}).values()]
        if not (isinstance(total, (int, float)) and total > 0) or (parts and not close(sum(p or 0 for p in parts), total)):
            problems.append(f"total {total} does not add up for {key}")
            break
    return problems

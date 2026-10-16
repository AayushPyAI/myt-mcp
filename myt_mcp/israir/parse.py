"""Israir flight search answer -> flight options with the price for the whole group.

The answer (POST /api/search/FLIGHTS) holds one package per flight: the flight number in its deep link, the segments with
local departure and arrival times, the baggage that is or is not in the price, and the fare per passenger type.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from myt_mcp.checks import close

# airports the traveller names -> the city code Israir sells by
CITY_OF_AIRPORT = {"FCO": "ROM", "CIA": "ROM", "MXP": "MIL", "LIN": "MIL", "BGY": "MIL", "LHR": "LON", "LGW": "LON", "STN": "LON", "LTN": "LON",
                   "LCY": "LON", "ORY": "PAR", "CDG": "PAR", "JFK": "NYC", "EWR": "NYC", "LGA": "NYC", "VCE": "VCE", "TSF": "VCE", "OTP": "BUH"}
TLV_ORIGIN_ID = 2135        # "all airports" id the search page uses for Tel Aviv as the departure city
SITE = "https://www.israir.co.il"


def _when(text: str | None) -> str | None:
    try:
        return datetime.strptime(text or "", "%d/%m/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _baggage(info: list[dict[str, Any]]) -> dict[str, Any]:
    by = {b.get("type"): b for b in info or [] if isinstance(b, dict)}
    included = lambda kind: (by.get(kind) or {}).get("indicator") == "INCLUDED_IN_PRICE"
    checked = by.get("CHECKED_BAGGAGE") or {}
    kg = checked.get("weight")
    return {"hand_bag_included": included("HAND_BAG"), "trolley_included": included("LUGGAGE_TROLY"), "checked_bag_included": included("CHECKED_BAGGAGE"),
            "checked_bag": (f"included ({kg} kg)" if included("CHECKED_BAGGAGE") else f"not included ({kg} kg can be added for a fee)") if kg else "not listed"}


def _source(deep_link: str) -> str:
    """The booking-flow link of the flight on Israir's site, without the session and tracking parameters."""
    parts = urlsplit(deep_link or "")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in ("sessionId", "edgetracrackerid", "token")]
    return f"{SITE}/he-IL/reservation/deal/searchFlight/abroadFlight?{urlencode(query, safe='/;')}"


def parse_packages(answer: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pkg in ((answer.get("data") or {}).get("ltsPackages") or []):
        try:
            option = pkg["legGroups"][0]["legList"][0]["legOptionList"][0]
            segments = option["legSegmentList"]
            fare = pkg["packageFare"]
            economy = (option.get("cabinVariants") or {}).get("ECONOMY") or {}
            numbers = re.search(r"fNumbers=([\d;]+)", pkg.get("deepLinkURL") or "")
            per_type: dict[str, float] = {}
            for p in fare.get("passengerFares") or []:
                per_type[(p.get("ltsPassengerType") or "?").lower()] = (p.get("amount") or {}).get("amount")
            seats = economy.get("seats")
            out.append({
                "flight_numbers": [n for n in (numbers.group(1).split(";") if numbers else []) if n],
                "from": segments[0]["depLoc"]["location"], "to": segments[-1]["arrLoc"]["location"],
                "departure": _when(segments[0]["depLoc"].get("scheduledDateTime")), "arrival": _when(segments[-1]["arrLoc"].get("scheduledDateTime")),
                "stops": len(segments) - 1, "carrier_code": segments[0].get("carrierCode"),
                "price_total": (fare.get("amount") or {}).get("amount"), "currency": (fare.get("amount") or {}).get("currency"),
                "price_per_passenger_type": per_type, "tax_amount": (fare.get("tax") or {}).get("amount"), "tax_included_in_price": bool(fare.get("taxIncluded")),
                "package_type": (pkg.get("packageId") or {}).get("packageType"),
                "baggage": _baggage(economy.get("baggageInformation") or segments[0].get("baggageInformation")),
                "meal_included": economy.get("meals") == "INCLUDED_IN_PRICE",
                "seats_left": seats if isinstance(seats, int) and economy.get("seatsIndicator") != "NO_DISPLAY" else None,
                "passengers": pkg.get("passengerSet"), "source": _source(pkg.get("deepLinkURL") or ""),
            })
        except (KeyError, IndexError, TypeError):
            continue
    return out


def check_packages(options: list[dict[str, Any]], day: date, adults: int, children: int, from_code: str, to_code: str) -> list[str]:
    """Each flight must be for the asked day, route and group, in one currency, and its total must add up from the fares per passenger."""
    problems = []
    for o in options:
        label = f"flight {'/'.join(o['flight_numbers']) or '?'}"
        if not (o["departure"] or "").startswith(day.isoformat()):
            problems.append(f"{label} departs {o['departure']}, not on {day.isoformat()}")
        if (o["passengers"] or {}).get("adults") != adults or (o["passengers"] or {}).get("children", 0) != children:
            problems.append(f"{label} is priced for {o['passengers']}, not {adults} adults and {children} children")
        if o["price_total"] is None or o["currency"] is None:
            problems.append(f"{label} has no price")
            continue
        types = o["price_per_passenger_type"]
        expected = adults * (types.get("adult") or 0) + children * (types.get("child") or 0)
        if types and not close(expected, o["price_total"], 0.05):
            problems.append(f"{label}: total {o['price_total']} does not add up from the fares per passenger ({expected})")
    if len({o["currency"] for o in options}) > 1:
        problems.append("the flights are priced in more than one currency")
    return problems

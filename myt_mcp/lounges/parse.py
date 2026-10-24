"""Aspire answers -> compact rows: which airport page matches, and what the lounge costs for a group."""

from __future__ import annotations

from datetime import datetime
from typing import Any

# Airport codes for the Aspire airports a Selected Places trip is likely to pass through. Anything else is
# matched by name ("Venice", "Ben Gurion", "Schiphol").
IATA = {
    "TLV": "tel-aviv-ben-gurion-airport", "VCE": "venice-marco-polo-airport", "VRN": "verona-airport",
    "AMS": "amsterdam-schiphol-airport", "ZRH": "zurich-international-airport", "GVA": "geneva-airport",
    "BSL": "euroairport-basel-mulhouse-freiburg", "HEL": "helsinki-airport", "CPH": "copenhagen-airport",
    "ARN": "stockholm-arlanda-airport", "GRZ": "graz-airport", "VNO": "vilnius-international-airport",
    "LHR": "london-heathrow-airport", "LGW": "london-gatwick-airport", "LTN": "london-luton-airport",
    "MAN": "manchester-airport", "EDI": "edinburgh-airport", "BHX": "birmingham-airport",
}
GROUP = (("adults", "Adult"), ("children", "Child"), ("infants", "Infant"))


def match_airport(query: str, airports: list[str]) -> list[str]:
    """Airport page names matching an IATA code or words of the airport/city name."""
    q = query.strip()
    if q.upper() in IATA and IATA[q.upper()] in airports:
        return [IATA[q.upper()]]
    words = [w for w in q.lower().replace("-", " ").split() if w not in ("airport", "international")]
    return [a for a in airports if words and all(w in a for w in words)]


def _each(ticket: dict[str, Any]) -> float | None:
    """What one ticket costs. Mirrors the website: a discount already shown in `unit` is not taken off again."""
    price = ticket.get("price") or {}
    unit, original, discount = price.get("unit"), price.get("originalValue"), price.get("discount") or 0
    if not isinstance(unit, (int, float)):
        return None
    already_applied = discount > 0 and original != unit
    return round(unit - (0 if already_applied else discount), 2)


BOARDING_MINUTES = 45


def _when(text: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "")) if text else None
    except ValueError:
        return None


def summarize_rates(answer: dict[str, Any], group: dict[str, int]) -> dict[str, Any]:
    """Prices for the group (adults/children/infants) at one lounge, for one flight time."""
    if answer.get("isError"):
        return {"available": False, "note": answer.get("errorDescription") or "Aspire could not price this lounge for that time."}
    data = answer.get("data") or {}
    if not data.get("isAvailable"):
        return {"available": False, "note": "The lounge has no availability (or is closed) for this flight time."}
    tickets = {t.get("type"): t for t in data.get("tickets") or [] if isinstance(t, dict)}
    lines, total, problems = [], 0.0, []
    for field, ticket_type in GROUP:
        count = group.get(field, 0)
        if not count:
            continue
        ticket = tickets.get(ticket_type)
        each = _each(ticket) if ticket else None
        if each is None:
            problems.append(f"no {ticket_type} ticket is sold at this lounge")
            continue
        if count > (ticket.get("maxQuantity") or count):
            problems.append(f"at most {ticket['maxQuantity']} {ticket_type} tickets per booking, so split the group into two bookings")
        lines.append({"ticket": ticket_type, "count": count, "price_each": each, "total": round(each * count, 2),
                      "currency": ticket.get("currency")})
        total += each * count
    result: dict[str, Any] = {
        "available": True,
        "lounge_entry": data.get("loungeEntryDateTime"),
        "lounge_exit": data.get("loungeExitDateTime"),
        "tickets": lines,
        "total_price": round(total, 2),
        "currency": next((line["currency"] for line in lines if line["currency"]), "EUR"),
    }
    exit_at, flight_at = _when(data.get("loungeExitDateTime")), _when(data.get("flightDateTime"))
    if exit_at and flight_at and (flight_at - exit_at).total_seconds() < BOARDING_MINUTES * 60:
        result["boarding_note"] = (f"Aspire lists the exit at {exit_at:%H:%M}, which is the flight time ({flight_at:%H:%M}): the family must leave the lounge for the gate at least "
                                   f"{BOARDING_MINUTES} minutes before departure (boarding closes earlier), so the usable stay is shorter than the window shown.")
    if data.get("showShortStayWarning"):
        problems.append("the stay is shorter than usual for this flight time (opening hours)")
    if problems:
        result["note"] = "; ".join(problems).capitalize() + "."
    return result


def check_rates(answer: dict[str, Any], flight_time: str) -> list[str]:
    """The price must be for this flight time, in EUR, with the lounge visit before the flight."""
    data = answer.get("data") or {}
    if answer.get("isError") or not data.get("isAvailable"):
        return []
    problems = []
    if (data.get("flightDateTime") or "")[:16] != flight_time[:16]:
        problems.append(f"priced for a flight at {data.get('flightDateTime')}, not {flight_time}")
    bad = sorted({t.get("currency") for t in data.get("tickets") or [] if t.get("currency") not in (None, "EUR")})
    if bad:
        problems.append(f"prices are in {', '.join(bad)}, not EUR")
    entry, flight = data.get("loungeEntryDateTime") or "", data.get("flightDateTime") or ""
    if entry and flight and entry > flight:
        problems.append(f"lounge entry {entry} is after the flight {flight}")
    return problems

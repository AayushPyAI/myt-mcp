"""Turn MYT's GetTrip/v3 payload (often over 1 MB) into compact summaries for Claude.

Only fields that matter for building a quote are kept. Every accessor tolerates
missing keys, because MYT omits or nulls fields depending on what is filled in.
"""

from __future__ import annotations

import re
from typing import Any

_TAG = re.compile(r"<[^>]+>")


def _date(d: dict | None) -> str | None:
    """MYT date object -> 'YYYY-MM-DD'."""
    return (d or {}).get("date", "")[:10] or None


def _time(d: dict | None) -> str | None:
    return ((d or {}).get("time") or {}).get("string")


def _amount(m: dict | None) -> float | None:
    value = (m or {}).get("amount")
    return round(value, 2) if isinstance(value, (int, float)) else value


def _flag(d: dict | None) -> str | None:
    """MYT encodes enums as {"name": "Hotel", "hotel": true}; return the name, or the true key."""
    if not d:
        return None
    if d.get("name"):
        return d["name"]
    return next((k for k, v in d.items() if v is True), None)


def _text(html: str | None, limit: int = 200) -> str:
    text = _TAG.sub(" ", html or "").replace("&nbsp;", " ")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def trip_summary(v3: dict[str, Any]) -> dict[str, Any]:
    trip = v3.get("trip") or {}
    dates = trip.get("dates") or {}
    quotation = v3.get("quotation") or {}
    return {
        "trip_id": trip.get("trip_id"),
        "number": trip.get("number"),
        "name": trip.get("name"),
        "status": (trip.get("status") or {}).get("name"),
        "start": _date(dates.get("start")),
        "end": _date(dates.get("end")),
        "countries": list(dict.fromkeys(c.get("name") if isinstance(c, dict) else c for c in trip.get("countries") or [])),
        "customer_text": {"marketing_content": _text(trip.get("marketing_content")), "quotation_comment": _text(quotation.get("general_description"))},
        "not_in_myt_data": "Project notes, comments and the children's ages are not given by MYT's data: ask the operator if the customer's wishes or the ages matter.",
        "paying_participants": trip.get("paying_participants"),
        "participants": trip.get("participants"),
        "staff": trip.get("number_of_staff"),
        "days": [
            {
                "day": day.get("day_number"),
                "date": _date(day.get("date")),
                "activities": [
                    {
                        "name": a.get("name"),
                        "supplier": a.get("supplier_name"),
                        "supplier_type": _flag(a.get("supplier_type")),
                        "description": _text(a.get("description")),
                    }
                    for a in day.get("activites") or []
                ],
            }
            for day in v3.get("schedule") or []
        ],
        "hotels": [
            {
                "hotel": h.get("product_name"),
                "supplier": h.get("supplier_name"),
                "check_in": _date((h.get("dates") or {}).get("start")),
                "check_out": _date((h.get("dates") or {}).get("end")),
                "nights": h.get("duration"),
                "rooms": h.get("quantity"),
                "price": _amount(h.get("price")),
                "currency": (h.get("currency") or {}).get("name"),
            }
            for h in v3.get("accomodation") or []
        ],
        "flights": [
            {
                "flight": f.get("number"),
                "from": f.get("from_airport"),
                "to": f.get("to_airport"),
                "departure": f"{_date(f.get('departure_date'))} {_time(f.get('departure_date')) or ''}".strip(),
                "arrival": f"{_date(f.get('arrival_date'))} {_time(f.get('arrival_date')) or ''}".strip(),
                "note": f.get("description"),
            }
            for f in v3.get("flights") or []
        ],
        "suppliers": [
            {"id": s.get("supplier_id"), "name": s.get("supplier_name"), "type": _flag(s.get("supplier_type"))}
            for s in v3.get("suppliers") or []
        ],
        "quotation": {
            "number": quotation.get("number"),
            "version": quotation.get("version"),
            "status": quotation.get("status"),
        }
        if quotation
        else None,
    }


def _line(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": _flag(p.get("type")),
        "product": p.get("name"),
        "supplier": p.get("supplier_name"),
        "supplier_id": p.get("supplier_id"),
        "pricing": "PP" if p.get("PP") else "PS",
        "line_type": _flag(p.get("first_category")),
        "transport": _flag(p.get("second_category")),
        "seats": _flag(p.get("third_category")),
        "date": _date(p.get("start_date")),
        "qty": p.get("quantity"),
        "nights": p.get("nights"),
        # MYT exposes line prices with the line profit already added (330 net -> 372.90);
        # the net cost per line is not in the public API.
        "unit_price_with_profit": _amount(p.get("unit_price")),
        "total_with_profit": _amount(p.get("total_price")) or _amount(p.get("quote_price")),
        "vat_pct": p.get("vat"),
        "currency": (p.get("currency") or {}).get("name"),
    }


def quotation_summary(v3: dict[str, Any]) -> dict[str, Any] | None:
    """The trip's selected quotation: cost lines, markups and the totals MYT calculated."""
    q = v3.get("quotation")
    if not q:
        return None
    packages = []
    for pkg in q.get("product_packages") or []:
        for pf in pkg.get("pax_free") or []:
            price = pf.get("price") or {}
            packages.append(
                {
                    "package_id": pkg.get("id"),
                    "package": pkg.get("title"),
                    "pax": pf.get("pax"),
                    "free": pf.get("free"),
                    # Sum of lines with profit, before conversion difference and fixed markups.
                    "lines_subtotal_group": _amount((price.get("tax") or {}).get("net")),
                    "price_per_person": _amount(price.get("person")),
                    "price_group": _amount(price.get("group")),
                    "single_supplement": _amount(price.get("single_supplement")),
                    "lines": [_line(p) for p in price.get("products") or []],
                }
            )
    unpriced = any(not p["price_group"] and p["lines_subtotal_group"] for p in packages)
    return {
        "number": q.get("number"),
        "version": q.get("version"),
        "status": q.get("status"),
        **({"note": "price_group and price_per_person are empty because MYT has not calculated the selling price yet (typical for a Draft). "
                    "The total of the cost lines is lines_subtotal_group: report that as the lines total, and say the selling price is not set."}
           if unpriced else {}),
        "currency": (q.get("currency") or {}).get("name"),
        "language": (q.get("language") or {}).get("name"),
        "markup": q.get("markup"),
        "packages": packages,
    }


def trips_list(trips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact GetTrips rows."""
    return [
        {
            "trip_id": t.get("TripId"),
            "name": t.get("TripName"),
            "start": (t.get("StartDateAndTime") or "")[:10] or None,
            "end": (t.get("EndDateAndTime") or "")[:10] or None,
            "status": t.get("TripStatusName"),
            "client": t.get("TripClientName"),
            "participants": t.get("CurrentParticipants"),
        }
        for t in trips or []
    ]

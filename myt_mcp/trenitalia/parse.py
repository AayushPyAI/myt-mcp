"""Turn Trenitalia search results into compact train rows."""

from __future__ import annotations

import re

from typing import Any

FARE_NOTES = {"BASE": "flexible (changes and refunds allowed)", "Economy": "cheaper, limited changes, no refund"}


def _amount(p: Any) -> float | None:
    if isinstance(p, dict) and isinstance(p.get("amount"), (int, float)):
        return round(float(p["amount"]), 2)
    return None


def _time(iso: str | None) -> str | None:
    return iso[11:16] if iso and len(iso) >= 16 else None


def _fares(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Per class and fare. Only for direct trains: with changes, the grid covers one leg, not the trip."""
    grids = item.get("grids") or []
    if len(grids) != 1:
        return []
    fares = []
    for service in grids[0].get("services") or []:
        for offer in service.get("offers") or []:
            price = _amount(offer.get("price"))
            if price is None:
                continue
            fares.append({
                "class": service.get("name"),
                "fare": offer.get("name"),
                "conditions": FARE_NOTES.get(offer.get("name")),
                "price": price,
                "seats_left": offer.get("availableAmount"),
            })
    return fares


def summarize_solutions(data: dict[str, Any], max_results: int = 10) -> tuple[list[dict[str, Any]], int]:
    """(trains, skipped). Prices are for all passengers in the search, in EUR."""
    rows, skipped = [], 0
    for item in data.get("solutions") or []:
        s = item.get("solution") if isinstance(item, dict) else None
        if not isinstance(s, dict) or not s.get("departureTime"):
            skipped += 1
            continue
        trains = [f"{t.get('trainCategory') or t.get('acronym')} {t.get('name')}".strip() for t in s.get("trains") or []]
        rows.append({
            "from": s.get("origin"),
            "to": s.get("destination"),
            "date": s["departureTime"][:10],
            "departure": _time(s.get("departureTime")),
            "arrival": _time(s.get("arrivalTime")),
            "duration": s.get("duration"),
            "trains": trains,
            "changes": max(len(s.get("nodes") or []) - 1, 0),
            "bookable": s.get("status") == "SALEABLE",
            "cheapest_price": _amount(s.get("price")),
            "currency": "EUR",
            "fares": _fares(item),
        })
        if not rows[-1]["fares"]:
            rows[-1]["fares_note"] = ("Trenitalia gives no class/fare breakdown for this train here; only the cheapest total is known. "
                                      "Do not state a class or fare conditions; check them on trenitalia.com.")
        if len(rows) >= max_results:
            break
    return rows, skipped


def check_rows(rows: list[dict[str, Any]], departure: str) -> list[str]:
    """Trains must leave at or after the asked date and time ("YYYY-MM-DD HH:MM"), with real prices."""
    problems = []
    for r in rows:
        if f"{r['date']} {r['departure']}" < departure:
            problems.append(f"train {', '.join(r['trains'])} leaves {r['date']} {r['departure']}, before {departure}")
            break
        if r["bookable"] and not (r["cheapest_price"] or 0) > 0:
            problems.append(f"train {', '.join(r['trains'])} has no price")
            break
        if any(not f["price"] > 0 for f in r["fares"]):
            problems.append(f"train {', '.join(r['trains'])} has a fare without a price")
            break
    return problems


def minutes(duration: str | None) -> int | None:
    """"1h 36min" -> 96."""
    if not isinstance(duration, str):
        return None
    h = re.search(r"(\d+)\s*h", duration)
    m = re.search(r"(\d+)\s*min", duration)
    return (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0) or None


def highlights(rows: list[dict[str, Any]], complete: bool = False) -> dict[str, Any]:
    """Cheapest and fastest of the trains shown (bookable ones with a price), worked out here so the answer copies them."""
    sellable = [r for r in rows if r["bookable"] and (r["cheapest_price"] or 0) > 0]
    out: dict[str, Any] = {"trains_shown": len(rows)}

    def pick(r: dict[str, Any]) -> dict[str, Any]:
        return {"departure": r["departure"], "arrival": r["arrival"], "trains": r["trains"], "changes": r["changes"],
                "duration": r["duration"], "price": r["cheapest_price"]}

    if sellable:
        out["cheapest_of_shown"] = pick(min(sellable, key=lambda r: (r["cheapest_price"], minutes(r["duration"]) or 9999)))
        timed = [r for r in sellable if minutes(r["duration"])]
        if timed:
            out["fastest_of_shown"] = pick(min(timed, key=lambda r: (minutes(r["duration"]), r["cheapest_price"])))
    out["note"] = ("Cheapest and fastest of ALL trains of the travel date from the asked time to the end of the day." if complete
                   else "Cheapest and fastest are among the trains shown only; later trains were not read.")
    return out

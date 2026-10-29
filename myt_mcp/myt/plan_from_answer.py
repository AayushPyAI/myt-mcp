"""A row of a composed answer that the operator chose becomes a supplier-reservation line (29 Oct 2026).

Until now the lines of `plan_supplier_reservations` were typed by hand (supplier, product, date, quantity, net price). Here the server finds the row again in what it composed
(`OFFERS`: found by the source, the name and the price the answer shows, never by a price the assistant types), decides the supplier and the category from the row's source
(only suppliers that are in the directory, never a new one), and returns lines the plan tool already knows. Pure logic: it changes nothing in MYT.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from myt_mcp.compose import Offer, group_date
from myt_mcp.myt import supplier_directory
from myt_mcp.myt.reservations import SUPPLIER_KIND, _key

KIND_CATEGORY = {"flights": "Transport", "trains": "Transport", "cars": "Transport", "transfers": "Transport", "hotels": "Lodging", "activities": "Attraction"}
# the word of a row's source or supplier -> the supplier id in the directory (RateHawk, Arbitrip, Get your guide, Ofran, TAP, SATA, Trenitalia, Sixt, 7M, Bensaude: verified on real
# reservations 22 Oct 2026). Kiwitaxi, iWay, Europcar, Rentalcars, Viator, Booking.com, Skyscanner and El Al are not in the directory: no line is made for them.
SOURCE_SUPPLIER = {"ratehawk": 85936, "arbitrip": 102638, "getyourguide": 48039, "get your guide": 48039, "ofran": 83265, "tap": 98430, "sata": 46627,
                   "trenitalia": 73808, "sixt": 98182, "7m": 106702, "bensaude": 115247}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _flat(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def find_offer(offers: list[Offer], choice: dict[str, Any]) -> tuple[Offer | None, str | None]:
    """The one row of the last answers that has this source, all the words of this name (in any order) and this price; else why not."""
    want_source, want_name = _flat(choice.get("source")), _flat(choice.get("name"))
    price = choice.get("price")
    group = _flat(choice.get("group"))
    same_source = [o for o in offers if want_source and want_source in _flat(o.source)]
    words = want_name.split()
    hits = [o for o in same_source if words and all(w in _flat(o.name) for w in words) and (price is None or abs((o.price_total or 0) - float(price)) < 0.01) and (not group or group in _flat(o.group))]
    if len(hits) == 1:
        return hits[0], None
    if len(hits) > 1:
        return None, f"{len(hits)} rows of {choice.get('source')} fit {choice.get('name')!r} at that price: add the leg (`group`, e.g. the date) or more of the name"
    near = sorted({f"{o.name[:60]} {o.price_total:.2f}" for o in same_source if want_name and want_name[:12] in _flat(o.name)})[:3]
    return None, (f"no row of {choice.get('source')!r} named like {choice.get('name')!r}" + (f" at {price}" if price is not None else "") + " in the last composed answer of this kind"
                  + (f" (close: {'; '.join(near)})" if near else "") + ": copy the source, the name and the price from the answer exactly")


def supplier_for(offer: Offer, category: str, override: str | int | None) -> tuple[dict[str, Any] | None, str | None]:
    """The directory entry for a row: the operator's own choice (`supplier`: a name or an id), else the one the row's source or supplier points to."""
    directory = supplier_directory.load()
    if override not in (None, ""):
        found = [s for s in directory if str(s["id"]) == str(override)] or supplier_directory.find_suppliers(str(override))
        if len(found) != 1:
            return None, f"supplier {override!r} matches {len(found)} suppliers in the directory: give its id (find_supplier shows them)"
        entry = found[0]
    else:
        text = f" {_flat(offer.supplier)} {_flat(offer.source)} "
        ids = [i for word, i in SOURCE_SUPPLIER.items() if f" {word} " in text]
        entry = next((s for s in directory if s["id"] in ids), None)
        if entry is None:
            return None, (f"{offer.source} is not a supplier in the MYT directory (RateHawk, Arbitrip, Get your guide, Ofran, TAP, SATA, Trenitalia...): give the exact MYT supplier name "
                          "as `supplier`, or create it on the MYT screen first (this tool never creates a supplier)")
    kinds = SUPPLIER_KIND[category]
    if entry.get("type") is not None and entry["type"] not in kinds:
        return None, (f"{entry['name']} is a {entry['type']} supplier: MYT keeps a {category} product only under a {'/'.join(kinds)} supplier. "
                      + ("A hotel is reserved under a lodging supplier (Arbitrip, or the hotel's own supplier): say which with `supplier`." if category == "Lodging" else "Choose a supplier of the right type with `supplier`."))
    return entry, None


def start_of(offer: Offer, given: Any) -> date | None:
    """The day of the service: given by the operator, else the date in the row's leg ('TLV to LIS, 12 Jan 2027'); a hotel or a car has none and must be given."""
    if given:
        return given if isinstance(given, date) else date.fromisoformat(str(given))
    parts = group_date(offer.group)
    if parts and parts[1][:3] in MONTHS:
        try:
            return date(int(parts[2]), MONTHS[parts[1][:3]], int(parts[0]))
        except ValueError:
            return None
    return None


def lines_from_choices(kind: str, choices: list[dict[str, Any]], offers: list[Offer]) -> dict[str, Any]:
    """{"lines": [PlanLine dicts], "problems": [...], "warnings": [...]}: one line per chosen row; a row that cannot be reserved is a problem, never a guess."""
    category = KIND_CATEGORY.get(kind)
    problems: list[str] = []
    warnings: list[str] = []
    lines: list[dict[str, Any]] = []
    if category is None:
        return {"lines": [], "problems": [f"kind {kind!r} has no reservation category"], "warnings": []}
    if not offers:
        problems.append(f"no composed {kind} answer is kept on the server (it keeps them for 3 hours): run compose_answer for the {kind} again")
    for n, choice in enumerate(choices, 1):
        if not offers:
            break
        offer, why = find_offer(offers, choice)
        if offer is None:
            problems.append(f"choice {n}: {why}")
            continue
        if not offer.quotable:
            problems.append(f"choice {n}: {offer.source}: {offer.name[:50]} is a comparison row (not quotable): the supplier's own price is the one to reserve; choose a quotable row")
            continue
        if offer.fits is False:
            problems.append(f"choice {n}: {offer.name[:50]} does not meet every wish of the operator (it is not in the table): choose another row")
            continue
        if offer.fits is None and offer.unconfirmed:
            warnings.append(f"choice {n}: {offer.name[:50]} is not confirmed for: {', '.join(offer.unconfirmed)}")
        supplier, why = supplier_for(offer, category, choice.get("supplier"))
        if supplier is None:
            problems.append(f"choice {n}: {why}")
            continue
        start = start_of(offer, choice.get("start_date"))
        if start is None:
            problems.append(f"choice {n}: give `start_date` (the day of this {kind.rstrip('s')}: check-in, pick-up, the day of the flight, the transfer or the tour)")
            continue
        quantity = float(choice.get("quantity") or 1)
        nights = int(choice.get("nights") or 0)
        total = float(offer.price_total or 0)
        if kind in ("hotels", "cars"):
            if nights <= 0 and kind == "cars":
                days = re.search(r"(\d+)\s+days?", offer.price_basis or "")
                nights = int(days.group(1)) if days else 0
            if nights <= 0:
                problems.append(f"choice {n}: give `nights` ({'the nights of the stay' if kind == 'hotels' else 'the days of the rental'}): the NET price is entered per {'night' if kind == 'hotels' else 'day'}")
                continue
            unit = round(total / (nights * quantity), 2)
            if abs(unit * nights * quantity - total) > 0.05:
                warnings.append(f"choice {n}: {total:.2f} does not divide evenly by {nights} x {quantity:g}: the reservation total will be {unit * nights * quantity:.2f}")
        else:
            nights, unit = 1, round(total, 2)
        line = {"supplier": supplier["name"], "supplier_id": supplier["id"], "category": category, "product_name": offer.name.strip()[:110],
                "start_date": start.isoformat(), "price": unit, "quantity": quantity, "nights": nights, "pricing": "PS", "currency": offer.currency or "EUR",
                "comments": f"From the {kind} answer: {offer.source}, {offer.group}" + (f"; {offer.price_basis[:80]}" if offer.price_basis else "")}
        if any(_key(l["product_name"]) == _key(line["product_name"]) and l["start_date"] == line["start_date"] and l["supplier_id"] == line["supplier_id"] for l in lines):
            problems.append(f"choice {n}: the same row is chosen twice")
            continue
        lines.append(line)
    return {"lines": lines, "problems": problems, "warnings": warnings}

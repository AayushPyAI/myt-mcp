"""Turn operator-approved lines into a supplier-reservation plan: who is the supplier, which category, which order, what total.

Pure logic (no MYT calls): the tool reads the trip, calls build_plan, shows the plan, and only after the operator's yes sends the
writes. MYT puts the products of one supplier into one order by itself (seen 22 Oct 2026), so the plan groups by supplier.
Reservations are NET prices; profit is a quote-line field and is not part of a reservation.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from myt_mcp.myt import supplier_directory
from myt_mcp.myt.reservations import KNOWN_CREATE_CATEGORIES, SUPPLIER_KIND, _key

MAX_LINES = 12                      # one plan is a handful of reservations, never a bulk load on the client's MYT
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
DMC_ADVICE = ("real DMC reservations are typed by what they are: use category Transport for a RateHawk transfer and Attraction for a "
              "Get your guide tour (both under the DMC supplier), not DMC")


def _resolve(line: dict[str, Any], problems: list[str], warnings: list[str], n: int) -> dict[str, Any] | None:
    """The directory entry for the line's supplier: by id, or by name when exactly one supplier fits the category."""
    category = line["category"]
    kinds = SUPPLIER_KIND[category]
    if line.get("supplier_id"):
        hit = next((s for s in supplier_directory.load() if s["id"] == line["supplier_id"]), None)
        if not hit:
            problems.append(f"line {n}: supplier id {line['supplier_id']} is not in the directory; confirm its name and type on the MYT screen first")
        return hit
    found = supplier_directory.find_suppliers(line["supplier"])
    fitting = [s for s in found if s.get("type") is None or s["type"] in kinds]
    if not found:
        problems.append(f"line {n}: no supplier called {line['supplier']!r} in the directory; ask the operator for the exact MYT name (never guess, never create a supplier)")
    elif not fitting:
        problems.append(f"line {n}: {line['supplier']!r} matches {', '.join(s['name'] + ' (' + str(s['type']) + ')' for s in found)}, none of which fits category {category}")
    elif len(fitting) > 1:
        problems.append(f"line {n}: {line['supplier']!r} matches several suppliers ({', '.join(str(s['id']) + ' ' + s['name'] for s in fitting)}); give supplier_id")
    else:
        return fitting[0]
    return None


def build_plan(lines: list[dict[str, Any]], existing: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """`lines`: dicts with supplier (name), supplier_id (optional), category, product_name, start_date (date), price, quantity, nights,
    pricing, currency, arrival_time, comments. `existing`: the trip's reservations as GetTrip/v3 returns them (duplicate check)."""
    problems: list[str] = []
    warnings: list[str] = []
    if not lines:
        problems.append("no lines given")
    if len(lines) > MAX_LINES:
        problems.append(f"{len(lines)} lines: send at most {MAX_LINES} per plan (no bulk writes on the client's MYT)")
    seen: set[tuple] = set()
    resolved: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for n, line in enumerate(lines[:MAX_LINES], 1):
        if line["category"] not in KNOWN_CREATE_CATEGORIES:
            problems.append(f"line {n}: category {line['category']!r} cannot be created through the API (use one of {', '.join(KNOWN_CREATE_CATEGORIES)})")
            continue
        if line["category"] == "DMC":
            warnings.append(f"line {n}: {DMC_ADVICE}")
        if not (line.get("product_name") or "").strip():
            problems.append(f"line {n}: product_name is empty")
        if not line["price"] or line["price"] <= 0:
            problems.append(f"line {n}: price must be more than 0 (the NET price per unit)")
        if line["quantity"] <= 0 or line["nights"] <= 0:
            problems.append(f"line {n}: quantity and nights must be more than 0")
        if line["start_date"] < today:
            problems.append(f"line {n}: start_date {line['start_date']} is in the past")
        if line.get("arrival_time") and not TIME_RE.fullmatch(line["arrival_time"]):
            problems.append(f"line {n}: arrival_time must be 24-hour HH:MM")
        supplier = _resolve(line, problems, warnings, n)
        if not supplier:
            continue
        if supplier.get("type") is None:
            warnings.append(f"line {n}: the type of {supplier['name']} (id {supplier['id']}) was never confirmed (seen on a quote line only): "
                            f"MYT silently drops a product whose type does not match its supplier; check the supplier's type on the MYT screen first")
        key = (supplier["id"], _key(line["product_name"]), line["start_date"])
        if key in seen:
            problems.append(f"line {n}: the same supplier, product and date appear twice in this plan")
        seen.add(key)
        for r in existing:
            if (r.get("supplier_id") == supplier["id"] and _key(r.get("product_name")) == key[1]
                    and ((r.get("dates") or {}).get("start") or {}).get("date", "")[:10] == line["start_date"].isoformat()):
                problems.append(f"line {n}: this reservation already exists (order {r.get('order_id')}, reservation {r.get('reservation_id')})")
        resolved.append((n, line, supplier))

    orders: dict[int, dict[str, Any]] = {}
    for n, line, supplier in resolved:
        order = orders.setdefault(supplier["id"], {"supplier_id": supplier["id"], "supplier": supplier["name"], "supplier_type": supplier.get("type"),
                                                   "products": [], "totals": {}})
        total = round(line["price"] * line["quantity"] * line["nights"], 2)
        order["products"].append({"line": n, "category": line["category"], "product": line["product_name"].strip(), "start_date": line["start_date"].isoformat(),
                                  "pricing": line["pricing"], "unit_price": line["price"], "quantity": line["quantity"], "nights": line["nights"],
                                  "currency": line["currency"].upper(), "total": total,
                                  "arrival_time": line.get("arrival_time"), "comments": line.get("comments")})
        cur = line["currency"].upper()
        order["totals"][cur] = round(order["totals"].get(cur, 0.0) + total, 2)
    grand: dict[str, float] = {}
    for order in orders.values():       # never add EUR and ILS together
        for cur, amount in order["totals"].items():
            grand[cur] = round(grand.get(cur, 0.0) + amount, 2)
    return {"orders": list(orders.values()), "total_by_currency": grand, "reservations": len(resolved), "problems": problems, "warnings": warnings}

"""`at_a_glance`: the cheapest and the most flexible option, worked out by the server.

Claude copies these instead of working them out from a long list, so the numbers cannot drift. Recommended and
Best fit are NOT here on purpose: they depend on the customer's wishes and are the operator-facing advice.
"""

from __future__ import annotations

import re
from typing import Any

NOTE = ("Worked out by the server from the options in this answer; copy these. Recommended and Best fit are for you to "
        "choose, from the customer's wishes and the playbook rules.")


def discount_pct(paid: Any, before: Any) -> int | None:
    if isinstance(paid, (int, float)) and isinstance(before, (int, float)) and paid > 0 and before > paid:
        return round((before - paid) / before * 100)
    return None


def free_cancellation(text: Any) -> bool | None:
    """True / False when the cancellation text says so; None when it does not say."""
    if not isinstance(text, str) or not text.strip():
        return None
    low = text.lower()
    if re.search(r"free cancel|cancel for free|cancel up to|cancel until|full refund", low):   # "free until X; no refund after" is still free before X
        return True
    if re.search(r"non.?refundable|no refund|not refundable", low):
        return False
    return True if re.search(r"refundable", low) else None


def _pick(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: entry[k] for k in keys if entry.get(k) is not None}


def activity_glance(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """entries: {option, time, price, price_before_discount, free_cancellation, cancellation} per option and start time."""
    priced = [e for e in entries if isinstance(e.get("price"), (int, float)) and e["price"] > 0]
    out: dict[str, Any] = {"priced_choices": len(priced), "note": NOTE}
    if not priced:
        out["cheapest"] = None
        return out
    keys = ("option", "time", "price", "price_before_discount", "discount_pct", "free_cancellation", "cancellation")
    for e in priced:
        e["discount_pct"] = discount_pct(e["price"], e.get("price_before_discount"))
    out["cheapest"] = _pick(min(priced, key=lambda e: e["price"]), keys)
    flexible = [e for e in priced if e.get("free_cancellation") is True]
    out["most_flexible"] = _pick(min(flexible, key=lambda e: e["price"]), keys) if flexible else None
    return out


def cars_glance(cars: list[dict[str, Any]]) -> dict[str, Any]:
    priced = [c for c in cars if isinstance(c.get("price"), (int, float)) and c["price"] > 0]
    out: dict[str, Any] = {"cars_checked": len(priced), "note": NOTE}
    if not priced:
        out["cheapest"] = None
        return out
    keys = ("car", "supplier", "transmission", "price", "price_before_discount", "discount_pct", "cdw_excess", "deposit", "package")

    def show(c: dict[str, Any]) -> dict[str, Any]:
        return _pick({**c, "discount_pct": discount_pct(c["price"], c.get("price_before_discount"))}, keys)

    out["cheapest"] = show(min(priced, key=lambda c: c["price"]))
    auto = [c for c in priced if "auto" in str(c.get("transmission") or "").lower()]
    out["cheapest_automatic"] = show(min(auto, key=lambda c: c["price"])) if auto else None
    zero = [c for c in priced if c.get("cdw_excess") == 0]
    out["cheapest_zero_excess"] = show(min(zero, key=lambda c: c["price"])) if zero else None
    return out


def flights_glance(options: list[dict[str, Any]]) -> dict[str, Any]:
    priced = [o for o in options if isinstance(o.get("total_price"), (int, float)) and o["total_price"] > 0]
    out: dict[str, Any] = {"options_checked": len(priced), "note": NOTE}
    if not priced:
        out["cheapest"] = None
        return out

    def show(o: dict[str, Any]) -> dict[str, Any]:
        legs = o.get("legs") or []
        return {"total_price": o["total_price"], "flights": [" + ".join(leg.get("flights") or []) for leg in legs],
                "departs": [leg.get("departs") for leg in legs], "stops": [leg.get("stops") for leg in legs],
                "fare": [leg.get("fare") for leg in legs]}

    out["cheapest"] = show(min(priced, key=lambda o: o["total_price"]))
    nonstop = [o for o in priced if all((leg.get("stops") or 0) == 0 for leg in o.get("legs") or [])]
    out["cheapest_nonstop"] = show(min(nonstop, key=lambda o: o["total_price"])) if nonstop else None
    return out


def activity_shortlist(rows: list[dict[str, Any]], id_key: str, min_reviews: int) -> list[dict[str, Any]]:
    """Up to three results worth an exact price check: the cheapest, the best rated and the most reviewed, among the
    per-person results with at least `min_reviews` reviews (a result can win several labels; it is listed once)."""
    solid = [r for r in rows if r.get("price_basis", "per person") == "per person" and r.get("from_price") is not None and (r.get("reviews") or 0) >= min_reviews]
    picks = [(f"Cheapest with {min_reviews}+ reviews", min(solid, key=lambda r: (r["from_price"], -r["reviews"]), default=None)),
             (f"Best rated with {min_reviews}+ reviews", min(solid, key=lambda r: (-(r.get("rating") or 0), -r["reviews"]), default=None)),
             ("Most reviewed", min(solid, key=lambda r: -r["reviews"], default=None))]
    out: list[dict[str, Any]] = []
    for label, row in picks:
        if not row:
            continue
        match = next((x for x in out if x[id_key] == row[id_key]), None)
        if match:
            match["why"] += f"; {label}"
        else:
            out.append({"why": label, id_key: row[id_key], "title": row["title"], "url": row.get("url"),
                        "from_price": row["from_price"], "rating": row.get("rating"), "reviews": row["reviews"]})
    return out

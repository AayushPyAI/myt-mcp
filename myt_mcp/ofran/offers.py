"""Turn Ofran's search result into compact offer rows, cheapest first."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import quote

log = logging.getLogger("myt_mcp.ofran")
IMAGE_URL = "https://img.ofran.co.il/photos/Desktop/"
AUTOMATIC = set("ABD")  # third letter of the ACRISS/SIPP code
Transmission = Literal["any", "manual", "automatic"]


def _num(v: Any) -> float | None:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


@dataclass
class OfferSummary:
    total: int = 0          # offers that matched the filter
    skipped: int = 0        # malformed offers left out
    cars: list[dict[str, Any]] = field(default_factory=list)


def _row(g: dict[str, Any], c: dict[str, Any], gear: str) -> dict[str, Any]:
    price, list_price = _num(c.get("nettotal")), _num(c.get("OfflineRate"))
    extras = ((c.get("AdditionalProducts") or {}).get("Products") or {}).get("AdditionalProduct") or []
    if isinstance(extras, dict):  # a single product comes back as an object, not a list
        extras = [extras]
    return {
        "supplier": g.get("suppliername"),
        "car": f"{g.get('carmodel')} or similar",
        "group": g.get("ofranCarGroupName"),
        "sipp": g.get("sippcode"),
        "transmission": gear,
        "seats": g.get("reccnumofadults"),
        "kids": g.get("reccnumofkids"),
        "doors": g.get("numdoors"),
        "suitcases": g.get("reccnumofsuitcases"),
        "handbags": g.get("reccnumofhandbags"),
        "supplier_rating": _num(g.get("SupplierRating")),
        "recommended": g.get("Recommended") == "true",
        "station_type": ((g.get("Filters") or {}).get("StationType") or {}).get("StationTypeName"),
        "image": f"{IMAGE_URL}{quote(g['PictureFile'])}" if g.get("PictureFile") else None,
        "price": price,
        "price_before_discount": list_price if list_price and price and list_price > price else None,
        "currency": c.get("currency"),
        "package": c.get("contractname"),
        "live_rate": c.get("IsLiveRate") == "true",
        "cdw_excess": _num(c.get("CDWExcess")),
        "theft_excess": _num(c.get("TPExcess")),
        "deposit": _num(c.get("Deposit")),
        "excess_currency": c.get("PolicyCurrency"),
        "fees": {k: v for k, v in (("handling", _num(c.get("handlingfee"))), ("premium", _num(c.get("premiumfee")))) if v},
        "one_way_fee": c.get("OneWayFee") or None,
        "optional_extras": [
            {"name": e.get("Name"), "price": _num(e.get("RateInReservationPQCurrency")), "currency": e.get("ReservationPQCurrencyCode")}
            for e in extras if isinstance(e, dict)
        ],
    }


def summarize_offers(result: list[Any], transmission: Transmission = "any", limit: int = 15) -> OfferSummary:
    """One row per contract. Offers without a price or car group are skipped and counted, so a
    change in Ofran's format shows up as `skipped` instead of breaking the whole answer."""
    summary = OfferSummary()
    rows = []
    for item in result:
        g = item.get("cargroup") if isinstance(item, dict) else None
        contracts = item.get("contracts") if isinstance(item, dict) else None
        if not isinstance(g, dict) or not isinstance(contracts, list):
            summary.skipped += 1
            continue
        sipp = g.get("sippcode") or ""
        gear = "automatic" if len(sipp) > 2 and sipp[2] in AUTOMATIC else "manual"
        if transmission != "any" and gear != transmission:
            continue
        for c in contracts:
            if not isinstance(c, dict) or _num(c.get("nettotal")) is None:
                summary.skipped += 1
                continue
            rows.append(_row(g, c, gear))
    if summary.skipped:
        log.warning("Ofran: skipped %d malformed offers", summary.skipped)
    rows.sort(key=lambda r: r["price"])
    summary.total, summary.cars = len(rows), rows[:limit]
    return summary


def check_offers(cars: list[dict[str, Any]]) -> list[str]:
    """Every offer needs a positive price and a currency, and all offers one currency (so they compare)."""
    problems = []
    if any(not (c["price"] or 0) > 0 for c in cars):
        problems.append("an offer has no price")
    currencies = {c["currency"] for c in cars}
    if None in currencies or "" in currencies:
        problems.append("an offer has no currency")
    elif len(currencies) > 1:
        problems.append(f"offers come in several currencies ({', '.join(sorted(currencies))})")
    return problems

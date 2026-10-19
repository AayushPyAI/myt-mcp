"""Correct, real data only.

1. Match checks: each source's answer is compared with the search that was asked (route, dates, travellers,
   currency, totals). If anything doesn't match, the answer is NOT used: the tool fails with DataCheckError
   instead of showing a price that may belong to another search.
2. checked_at: every tool answer says when its price data was fetched from the site (UTC). Answers served
   from the short cache keep the time of the real fetch, so the operator always sees how fresh a price is.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, ParamSpec, TypeVar

from myt_mcp.errors import IntegrationError

log = logging.getLogger("myt_mcp.checks")
P = ParamSpec("P")
R = TypeVar("R")

# wall-clock times (epoch seconds) of the price data used by the current tool call
_fetched: ContextVar[list[float] | None] = ContextVar("fetched", default=None)


class DataCheckError(IntegrationError):
    pass


def ensure(source: str, problems: list[str]) -> None:
    """Refuse an answer that doesn't match the search."""
    if problems:
        log.warning("%s answer failed checks: %s", source, problems)
        raise DataCheckError(f"{source}'s answer did not match the search ({'; '.join(problems[:3])}). "
                             "It was not used. Try again, or check the price on the website.")


def record_fetch(epoch_seconds: float) -> None:
    """Called by the price caches each time they hand out data (fresh or cached)."""
    times = _fetched.get()
    if times is not None:
        times.append(epoch_seconds)


def close(a: Any, b: Any, tolerance: float = 0.02) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(a - b) <= tolerance


REMINDER = ("Before you answer: copy every name, date and price exactly as this result gives it (never add a person's name, translate or "
            "shift a date); every number and detail must come from this result (else say 'not available'); "
            "flag any option that does not match the request; say how many results you read of how many exist and never call a result "
            "'the cheapest' or 'the best' unless you read them all; rows come ranked: show them in rank order, never re-sort, and copy every flag "
            "(few reviews, per group, sold out); a 'from' price is not a final price: get the exact price for the shortlist (cheapest too) "
            "one call after another; a detail (meeting point, pickup, child age band, cancellation) belongs to ONE option or listing: "
            "write the one you priced; recommend by the whole group's total first and never contradict your own table; show the discounted "
            "price AND the list price when both exist; label Cheapest, Recommended and Most flexible with a one-line reason; end with "
            "end_your_answer_with. Before you compare options or sources call quote_guide('comparison'); before a hotel or car search call quote_guide('filters') and apply the operator's filters or the trip's defaults; in a long chat call quote_guide('correct_data') again before writing to MYT.")

_SOURCES = {
    "find_trip": "MYT (ManageYourTrip)", "get_trip": "MYT (ManageYourTrip)", "get_quotation": "MYT (ManageYourTrip)", "update_minisite": "Selected Places mini-site",
    "get_trip_participants": "MYT (ManageYourTrip)", "get_supplier_reservations": "MYT (ManageYourTrip)", "reconcile_trip": "MYT (ManageYourTrip)", "check_reservation_paperwork": "MYT (ManageYourTrip)", "train_prices": "Trenitalia (lefrecce.it)",
    "sata_flight_prices": "SATA (azoresairlines.pt)", "lounge_prices": "Aspire Lounges", "viator_search_activities": "Viator",
    "viator_activity_details": "Viator", "getyourguide_activity_details": "GetYourGuide", "getyourguide_find_activities": "GetYourGuide",
    "ofran_car_prices": "Ofran", "kiwitaxi_transfer_prices": "Kiwitaxi (kiwitaxi.com)", "mozio_transfer_prices": "Mozio (mozio.com)", "israir_flight_prices": "Israir (israir.co.il)", "tap_flight_prices": "TAP Air Portugal (flytap.com)", "tap_fare_calendar": "TAP Air Portugal fare calendar (flytap.com)",
}


def _cite(tool: str, result: dict[str, Any]) -> str:
    """A ready-made line for the operator: where the data comes from, when it was checked and the link."""
    link = next((result[k] for k in ("source", "activity_url", "url") if isinstance(result.get(k), str)), None)
    line = f"Source: {_SOURCES.get(tool, tool)}, checked {result['checked_at']} ({result['data_age_minutes']} min old)"
    line = f"{line}, {link}" if link else line
    age_rules = result.get("age_rules")            # travels with the source line so a short answer cannot drop it
    return f"{line}. Note: {age_rules}" if isinstance(age_rules, str) else line


def with_checked_at(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Adds `checked_at` (oldest price data in the answer) and `end_your_answer_with` (the source line to show) to a tool's dict answer."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        token = _fetched.set([])
        try:
            result = await fn(*args, **kwargs)
            times = _fetched.get() or []
        finally:
            _fetched.reset(token)
        if isinstance(result, dict) and times:
            oldest = min(times)
            result["checked_at"] = datetime.fromtimestamp(oldest, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            result["data_age_minutes"] = int((time.time() - oldest) // 60)
            result["end_your_answer_with"] = _cite(fn.__name__, result)
            result["remember"] = REMINDER
        return result

    return wrapper

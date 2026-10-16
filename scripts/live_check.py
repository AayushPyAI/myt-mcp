"""Live self-check: one real search per source, through the same tools Claude uses, with all data checks on.

Run it before a demo, after a site may have changed, or daily:

    .venv/bin/python scripts/live_check.py

PASS = the source answered, the answer matched the search, and it has real prices.
FAIL = the reason (blocked, site changed, answer didn't match...). Nothing is booked; one search per source.
Needs the automation Chrome (BROWSER_CDP_URL) for SATA, Viator and Aspire.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from mcp import Client  # noqa: E402

from myt_mcp.app import create_server  # noqa: E402
from myt_mcp.config import Settings  # noqa: E402

DAY = date.today() + timedelta(days=35)


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content or json.loads(result.content[0].text)


def _first(items: list[Any], *path: str) -> Any:
    value: Any = items[0] if items else None
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


async def _viator(c: Client) -> str:
    found = await c.call_tool("viator_search_activities", {"query": "Sintra day trip from Lisbon", "max_results": 1})
    if found.is_error:
        raise RuntimeError(found.content[0].text)
    url = found.structured_content["activities"][0]["url"]
    r = await c.call_tool("viator_activity_details", {"url": url, "activity_date": DAY.isoformat(), "adults": 2})
    if r.is_error:
        raise RuntimeError(r.content[0].text)
    group = r.structured_content["for_your_group"]
    best = next((o for o in group["options"] if o["available"]), None)
    return f"{r.structured_content['title'][:40]}: " + (f"€{best['total_price_from']} for 2 adults" if best else "sold out that day")


def _trip_ids() -> list[int]:
    return [int(x) for x in os.environ.get("ALLOWED_TRIP_IDS", "").split(",") if x.strip()]


CHECKS = [
    ("MYT trip", "get_trip", lambda: {"trip_id": _trip_ids()[0]},
     lambda d: f"trip #{d['number']} {d['name']} ({d['start']} to {d['end']})"),
    ("Trenitalia", "train_prices", lambda: {"from_station": "Firenze", "to_station": "Roma", "travel_date": DAY.isoformat(), "max_results": 1},
     lambda d: f"{_first(d['trains'], 'departure')} {', '.join(_first(d['trains'], 'trains') or [])}: €{_first(d['trains'], 'cheapest_price')} for 2"),
    ("SATA", "sata_flight_prices", lambda: {"from_airport": "LIS", "to_airport": "PDL", "departure_date": DAY.isoformat(), "max_results": 1},
     lambda d: f"{_first(d['options'], 'legs')[0]['flights'][0]} {_first(d['options'], 'legs')[0]['departs']}: €{_first(d['options'], 'total_price')} for 2"
     if d["options"] else "no flights that day"),
    ("Aspire", "lounge_prices", lambda: {"airport": "TLV", "flight_departure": datetime.combine(DAY, datetime.min.time()).replace(hour=10).isoformat()},
     lambda d: f"{_first(d['lounges'], 'name')}: €{_first(d['lounges'], 'total_price')} for 2"),
    ("Ofran", "ofran_car_prices", lambda: {"location": "Lisbon Airport", "pickup_date": DAY.isoformat(),
                                           "dropoff_date": (DAY + timedelta(days=3)).isoformat(), "max_results": 1},
     lambda d: f"{_first(d['cars'], 'car')} {_first(d['cars'], 'supplier')}: {_first(d['cars'], 'price')} {_first(d['cars'], 'currency')}"
     if d["cars"] else "no cars"),
]


async def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    failures = 0
    async with Client(create_server(Settings.from_env())) as c:
        for name, tool, args, show in CHECKS:
            started = time.time()
            try:
                r = await c.call_tool(tool, args())
                if r.is_error:
                    raise RuntimeError(r.content[0].text)
                data = _payload(r)
                line = f"PASS  {show(data)}  (checked {data.get('checked_at', '?')})"
            except Exception as e:  # report every source, whatever fails
                failures += 1
                line = f"FAIL  {str(e)[:220]}"
            print(f"{name:<11} {time.time() - started:5.1f}s  {line}", flush=True)
        started = time.time()
        try:
            line = f"PASS  {await _viator(c)}"
        except Exception as e:
            failures += 1
            line = f"FAIL  {str(e)[:220]}"
        print(f"{'Viator':<11} {time.time() - started:5.1f}s  {line}")
    print(f"\n{len(CHECKS) + 1 - failures} of {len(CHECKS) + 1} sources OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

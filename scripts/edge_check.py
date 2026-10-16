"""Edge-case sweep: odd, wrong and extreme inputs against every tool, live, through the same path Claude uses.

    .venv/bin/python scripts/edge_check.py            # everything
    .venv/bin/python scripts/edge_check.py trains     # one group

What counts as a problem:
  CRASH   the tool answered "failed unexpectedly" (an unhandled bug; the safety net caught it)
  WRONG   a call that must be refused was answered, or a normal call was refused
  SLOW    more than 120 s
  UNCLEAR an error message with no readable explanation
A clean refusal ("travel_date is in the past") is the correct answer for bad input.

Expectations:  ok = a normal answer   error = a clear refusal   either = depends on the live site (only crashes count)
Nothing is booked or written. Needs the automation Chrome for SATA, Viator and Aspire.
"""

from __future__ import annotations

import asyncio
import json
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

TODAY = date.today()
DAY = TODAY + timedelta(days=35)
PAST = TODAY - timedelta(days=3)
FAR = TODAY + timedelta(days=500)
NOW = datetime.now()
VIATOR = "https://www.viator.com/tours/Florence/Cooking-Art-Brunelleschi/d519-212483P5"
GYG = "https://www.getyourguide.com/florence-l32/florence-pasta-cooking-class-with-unlimited-wine-t552524/"
LINE = {"category": "Attraction", "supplier": "X", "product_name": "Y", "pricing": "PP", "unit_price": 10}
TRIP = 276310


def iso(d: date) -> str:
    return d.isoformat()


def dt(d: date, hour: int) -> str:
    return datetime.combine(d, datetime.min.time()).replace(hour=hour).isoformat()


# (group, label, tool, args, expectation)
CASES: list[tuple[str, str, str, dict[str, Any], str]] = [
    # ---------- MYT ----------
    ("myt", "find trip by number", "find_trip", {"trip_number": "906"}, "ok"),
    ("myt", "find trip: no arguments", "find_trip", {}, "either"),
    ("myt", "find trip: unknown number", "find_trip", {"trip_number": "99999999"}, "either"),
    ("myt", "find trip: SQL-looking name", "find_trip", {"name": "'; DROP TABLE trips; --"}, "either"),
    ("myt", "find trip: 5000-char name", "find_trip", {"name": "x" * 5000}, "either"),
    ("myt", "get_trip: the allowed test trip", "get_trip", {"trip_id": TRIP}, "ok"),
    ("myt", "get_trip: another trip (905)", "get_trip", {"trip_id": 905}, "error"),
    ("myt", "get_trip: id 0", "get_trip", {"trip_id": 0}, "error"),
    ("myt", "get_trip: negative id", "get_trip", {"trip_id": -5}, "error"),
    ("myt", "get_trip: huge id", "get_trip", {"trip_id": 10**15}, "error"),
    ("myt", "get_trip: text instead of id", "get_trip", {"trip_id": "abc"}, "error"),
    ("myt", "get_quotation: test trip", "get_quotation", {"trip_id": TRIP}, "ok"),
    ("myt", "get_quotation: other trip", "get_quotation", {"trip_id": 123}, "error"),
    ("myt", "participants: other trip", "get_trip_participants", {"trip_id": 123}, "error"),
    # ---------- quote maths ----------
    ("quote", "normal quote", "calculate_quote", {"lines": [LINE], "paying_pax": 2}, "ok"),
    ("quote", "no lines", "calculate_quote", {"lines": [], "paying_pax": 2}, "error"),
    ("quote", "zero paying travellers", "calculate_quote", {"lines": [LINE], "paying_pax": 0}, "error"),
    ("quote", "negative price", "calculate_quote", {"lines": [{**LINE, "unit_price": -5}], "paying_pax": 2}, "error"),
    ("quote", "unknown category", "calculate_quote", {"lines": [{**LINE, "category": "Spaceship"}], "paying_pax": 2}, "error"),
    ("quote", "conversion 150%", "calculate_quote", {"lines": [LINE], "paying_pax": 2, "conversion_pct": 150}, "error"),
    ("quote", "negative free pax", "calculate_quote", {"lines": [LINE], "paying_pax": 2, "free_pax": -1}, "error"),
    ("quote", "qty zero", "calculate_quote", {"lines": [{**LINE, "qty": 0}], "paying_pax": 2}, "error"),
    ("quote", "huge price", "calculate_quote", {"lines": [{**LINE, "unit_price": 1e12}], "paying_pax": 2}, "either"),
    ("quote", "1000 lines", "calculate_quote", {"lines": [LINE] * 1000, "paying_pax": 2}, "ok"),
    # ---------- playbook ----------
    ("guide", "rules topic", "quote_guide", {"topic": "rules"}, "ok"),
    ("guide", "unknown topic", "quote_guide", {"topic": "nonsense"}, "error"),
    # ---------- trains ----------
    ("trains", "normal", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY)}, "ok"),
    ("trains", "English city names", "train_prices", {"from_station": "Florence", "to_station": "Rome", "travel_date": iso(DAY)}, "ok"),
    ("trains", "typo must not become another station", "train_prices", {"from_station": "Romma", "to_station": "Firenze", "travel_date": iso(DAY)}, "error"),
    ("trains", "lower case + typo", "train_prices", {"from_station": "firenze", "to_station": "romma", "travel_date": iso(DAY)}, "either"),
    ("trains", "unknown station", "train_prices", {"from_station": "Atlantis", "to_station": "Roma", "travel_date": iso(DAY)}, "error"),
    ("trains", "same station", "train_prices", {"from_station": "Roma", "to_station": "Roma", "travel_date": iso(DAY)}, "error"),
    ("trains", "past date", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(PAST)}, "error"),
    ("trains", "date 500 days away", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(FAR)}, "either"),
    ("trains", "bad time 9:00", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "depart_after": "9:00"}, "error"),
    ("trains", "bad time 24:00", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "depart_after": "24:00"}, "error"),
    ("trains", "late night 23:59", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "depart_after": "23:59"}, "either"),
    ("trains", "zero adults", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "adults": 0}, "error"),
    ("trains", "10 adults", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "adults": 10}, "error"),
    ("trains", "max_results 0", "train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY), "max_results": 0}, "error"),
    ("trains", "emoji station", "train_prices", {"from_station": "🚆🚆", "to_station": "Roma", "travel_date": iso(DAY)}, "either"),
    ("trains", "5000-char station", "train_prices", {"from_station": "a" * 5000, "to_station": "Roma", "travel_date": iso(DAY)}, "either"),
    ("trains", "station lookup empty", "train_find_station", {"query": "  "}, "error"),
    ("trains", "station lookup normal", "train_find_station", {"query": "Venezia"}, "ok"),
    # ---------- SATA ----------
    ("sata", "round trip", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "return_date": iso(DAY + timedelta(days=7))}, "ok"),
    ("sata", "one way inter-island", "sata_flight_prices", {"from_airport": "PDL", "to_airport": "PIX", "departure_date": iso(DAY)}, "ok"),
    ("sata", "lower case + spaces", "sata_flight_prices", {"from_airport": " lis ", "to_airport": "pdl", "departure_date": iso(DAY)}, "ok"),
    ("sata", "city name instead of code", "sata_flight_prices", {"from_airport": "Lisbon", "to_airport": "PDL", "departure_date": iso(DAY)}, "error"),
    ("sata", "same airports", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "LIS", "departure_date": iso(DAY)}, "error"),
    ("sata", "unknown airport code", "sata_flight_prices", {"from_airport": "XXX", "to_airport": "PDL", "departure_date": iso(DAY)}, "either"),
    ("sata", "route SATA doesn't fly", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "LAX", "departure_date": iso(DAY)}, "either"),
    ("sata", "past departure", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(PAST)}, "error"),
    ("sata", "return before departure", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "return_date": iso(DAY - timedelta(days=1))}, "error"),
    ("sata", "return same day", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "return_date": iso(DAY)}, "either"),
    ("sata", "departure 500 days away", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(FAR)}, "either"),
    ("sata", "departure today", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(TODAY)}, "either"),
    ("sata", "infants more than adults", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "adults": 1, "infants": 2}, "error"),
    ("sata", "10 seats", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "adults": 5, "children": 5}, "error"),
    ("sata", "family 2+2+1", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "adults": 2, "children": 2, "infants": 1}, "ok"),
    ("sata", "max_results 100", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": iso(DAY), "max_results": 100}, "error"),
    # ---------- Viator ----------
    ("viator", "search normal", "viator_search_activities", {"query": "Florence cooking class"}, "ok"),
    ("viator", "search empty", "viator_search_activities", {"query": "   "}, "error"),
    ("viator", "search nothing exists", "viator_search_activities", {"query": "zzqxjv underwater basket weaving Atlantis"}, "either"),
    ("viator", "search emoji", "viator_search_activities", {"query": "🍝🍝🍝"}, "either"),
    ("viator", "search symbols/quotes", "viator_search_activities", {"query": "\"'<>&%$#@!"}, "either"),
    ("viator", "search Hebrew", "viator_search_activities", {"query": "סדנת בישול פירנצה"}, "either"),
    ("viator", "search 5000 chars", "viator_search_activities", {"query": "pasta " * 900}, "either"),
    ("viator", "search max_results 0", "viator_search_activities", {"query": "pasta", "max_results": 0}, "error"),
    ("viator", "search max_results 100", "viator_search_activities", {"query": "pasta", "max_results": 100}, "error"),
    ("viator", "details no date", "viator_activity_details", {"url": VIATOR}, "ok"),
    ("viator", "details with date + group", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "adults": 2, "child_ages": [8]}, "ok"),
    ("viator", "details: other site link", "viator_activity_details", {"url": "https://www.getyourguide.com/x-t1/"}, "error"),
    ("viator", "details: http link", "viator_activity_details", {"url": "http://www.viator.com/tours/a/b/d1-X"}, "error"),
    ("viator", "details: fake product", "viator_activity_details", {"url": "https://www.viator.com/tours/Nowhere/Fake/d1-FAKECODE999"}, "either"),
    ("viator", "details: not a url", "viator_activity_details", {"url": "pasta class please"}, "error"),
    ("viator", "details: past date", "viator_activity_details", {"url": VIATOR, "activity_date": iso(PAST)}, "error"),
    ("viator", "details: date 800 days away", "viator_activity_details", {"url": VIATOR, "activity_date": iso(TODAY + timedelta(days=800))}, "either"),
    ("viator", "details: child aged 18", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "child_ages": [18]}, "error"),
    ("viator", "details: child aged -1", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "child_ages": [-1]}, "error"),
    ("viator", "details: 16 adults", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "adults": 16}, "error"),
    ("viator", "details: nobody travelling", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "adults": 0}, "error"),
    ("viator", "details: baby aged 0", "viator_activity_details", {"url": VIATOR, "activity_date": iso(DAY), "adults": 2, "child_ages": [0]}, "either"),
    # ---------- GetYourGuide (details only; search stays with the connector) ----------
    ("gyg", "details 2 adults", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 2}, "ok"),
    ("gyg", "connector link with tracking", "getyourguide_activity_details", {"url": GYG + "?psrc=widget&partner_id=F71L4IS&currency=EUR&visitor_id=ABC&date_from=" + iso(DAY), "activity_date": iso(DAY)}, "ok"),
    ("gyg", "child aged 8 (adult group here)", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 2, "child_ages": [8]}, "ok"),
    ("gyg", "baby aged 2", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 2, "child_ages": [2]}, "ok"),
    ("gyg", "family 2+3 children", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 2, "child_ages": [1, 7, 15]}, "ok"),
    ("gyg", "date 800 days away", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(TODAY + timedelta(days=800))}, "ok"),
    ("gyg", "past date", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(PAST)}, "error"),
    ("gyg", "Viator link", "getyourguide_activity_details", {"url": VIATOR, "activity_date": iso(DAY)}, "error"),
    ("gyg", "city page, not an activity", "getyourguide_activity_details", {"url": "https://www.getyourguide.com/florence-l32/", "activity_date": iso(DAY)}, "error"),
    ("gyg", "look-alike domain", "getyourguide_activity_details", {"url": "https://www.getyourguide.com.evil.test/x-t552524/", "activity_date": iso(DAY)}, "error"),
    ("gyg", "activity that does not exist", "getyourguide_activity_details", {"url": "https://www.getyourguide.com/florence-l32/nothing-here-t99999999/", "activity_date": iso(DAY)}, "either"),
    ("gyg", "16 adults", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 16}, "error"),
    ("gyg", "nobody travelling", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "adults": 0}, "error"),
    ("gyg", "child aged 18", "getyourguide_activity_details", {"url": GYG, "activity_date": iso(DAY), "child_ages": [18]}, "error"),
    ("gyg", "no date given", "getyourguide_activity_details", {"url": GYG}, "error"),
    # ---------- Aspire ----------
    ("aspire", "TLV normal", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 10)}, "ok"),
    ("aspire", "airport by name", "lounge_prices", {"airport": "Ben Gurion", "flight_departure": dt(DAY, 10)}, "ok"),
    ("aspire", "no Aspire at airport", "lounge_prices", {"airport": "Lisbon", "flight_departure": dt(DAY, 10)}, "ok"),
    ("aspire", "ambiguous airport", "lounge_prices", {"airport": "London", "flight_departure": dt(DAY, 10)}, "either"),
    ("aspire", "gibberish airport", "lounge_prices", {"airport": "qwertyuiop", "flight_departure": dt(DAY, 10)}, "ok"),
    ("aspire", "empty airport", "lounge_prices", {"airport": " ", "flight_departure": dt(DAY, 10)}, "error"),
    ("aspire", "past flight", "lounge_prices", {"airport": "TLV", "flight_departure": dt(PAST, 10)}, "error"),
    ("aspire", "flight in 3 minutes", "lounge_prices", {"airport": "TLV", "flight_departure": (NOW + timedelta(minutes=3)).isoformat()}, "either"),
    ("aspire", "flight at 03:00", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 3)}, "either"),
    ("aspire", "flight 400 days away", "lounge_prices", {"airport": "TLV", "flight_departure": dt(TODAY + timedelta(days=400), 10)}, "either"),
    ("aspire", "no travellers", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 10), "adults": 0}, "error"),
    ("aspire", "20 adults", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 10), "adults": 20}, "error"),
    ("aspire", "9 adults (needs 2 bookings)", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 10), "adults": 9}, "either"),
    ("aspire", "family with baby", "lounge_prices", {"airport": "TLV", "flight_departure": dt(DAY, 10), "adults": 2, "children": 2, "infants": 1}, "ok"),
    # ---------- Ofran (blocked from India; must fail cleanly) ----------
    ("ofran", "normal", "ofran_car_prices", {"location": "Lisbon Airport", "pickup_date": iso(DAY), "dropoff_date": iso(DAY + timedelta(days=3))}, "either"),
    ("ofran", "empty location", "ofran_car_prices", {"location": " ", "pickup_date": iso(DAY), "dropoff_date": iso(DAY + timedelta(days=3))}, "error"),
    ("ofran", "past pickup", "ofran_car_prices", {"location": "Lisbon", "pickup_date": iso(PAST), "dropoff_date": iso(DAY)}, "error"),
    ("ofran", "dropoff before pickup", "ofran_car_prices", {"location": "Lisbon", "pickup_date": iso(DAY), "dropoff_date": iso(DAY - timedelta(days=1))}, "error"),
    ("ofran", "bad time", "ofran_car_prices", {"location": "Lisbon", "pickup_date": iso(DAY), "dropoff_date": iso(DAY + timedelta(days=2)), "pickup_time": "25:00"}, "error"),
    ("ofran", "driver aged 17", "ofran_car_prices", {"location": "Lisbon", "pickup_date": iso(DAY), "dropoff_date": iso(DAY + timedelta(days=2)), "driver_age": 17}, "error"),
    ("ofran", "location lookup", "ofran_find_location", {"query": "Florence"}, "either"),
]

# groups of calls run at the same time (shared caches, pacing and per-site locks must hold up)
TRAIN = {"from_station": "Firenze", "to_station": "Roma", "travel_date": iso(DAY + timedelta(days=1))}
PARALLEL = [
    ("six identical train searches at once", [("train_prices", TRAIN)] * 6),
    ("four different SATA searches at once", [("sata_flight_prices", {"from_airport": "LIS", "to_airport": a, "departure_date": iso(DAY + timedelta(days=i))})
                                               for i, a in enumerate(("PDL", "TER", "HOR", "PIX"))]),
    ("every source at once", [("train_prices", TRAIN), ("viator_search_activities", {"query": "Rome colosseum tour"}),
                              ("lounge_prices", {"airport": "VCE", "flight_departure": dt(DAY, 12)}),
                              ("sata_flight_prices", {"from_airport": "OPO", "to_airport": "PDL", "departure_date": iso(DAY)}),
                              ("get_trip", {"trip_id": TRIP}), ("calculate_quote", {"lines": [LINE], "paying_pax": 2})]),
]


def text_of(result: Any) -> str:
    return result.content[0].text if result.content else ""


def judge(result: Any, expect: str, seconds: float) -> tuple[str, str]:
    """(verdict, note)."""
    text = text_of(result)
    if "failed unexpectedly" in text:
        return "CRASH", text[:200]
    if seconds > 120:
        return "SLOW", f"{seconds:.0f}s"
    if result.is_error:
        if len(text.strip()) < 12:
            return "UNCLEAR", repr(text)
        return ("WRONG", "refused: " + text[:160]) if expect == "ok" else ("PASS", "refused: " + text[:110])
    if expect == "error":
        return "WRONG", "answered, should have been refused: " + text[:120].replace("\n", " ")
    return "PASS", "answered"


async def run_case(client: Client, group: str, label: str, tool: str, args: dict[str, Any], expect: str) -> dict[str, Any]:
    started = time.time()
    try:
        result = await client.call_tool(tool, args)
        verdict, note = judge(result, expect, time.time() - started)
    except Exception as e:  # a protocol-level failure (e.g. invalid argument type) is a clean refusal too
        msg = f"{type(e).__name__}: {str(e)[:150]}"
        verdict, note = ("WRONG", "raised: " + msg) if expect == "ok" else ("PASS", "raised: " + msg)
    return {"group": group, "label": label, "tool": tool, "expect": expect, "verdict": verdict, "note": note,
            "seconds": round(time.time() - started, 1)}


async def main(only: set[str]) -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    rows: list[dict[str, Any]] = []
    async with Client(create_server(Settings.from_env())) as client:
        for group, label, tool, args, expect in CASES:
            if only and group not in only:
                continue
            row = await run_case(client, group, label, tool, args, expect)
            rows.append(row)
            flag = "  " if row["verdict"] == "PASS" else "!!"
            print(f"{flag} {group:<7} {label:<38} {row['verdict']:<7} {row['seconds']:>5}s  {row['note'][:95]}", flush=True)
        if not only or "parallel" in only:
            for label, calls in PARALLEL:
                started = time.time()
                results = await asyncio.gather(*(client.call_tool(t, a) for t, a in calls), return_exceptions=True)
                bad = [t for (t, _), r in zip(calls, results)
                       if isinstance(r, Exception) or "failed unexpectedly" in text_of(r)]
                errors = [text_of(r)[:80] for r in results if not isinstance(r, Exception) and r.is_error]
                verdict = "CRASH" if bad else "PASS"
                note = f"{len(calls)} calls, {len(errors)} refused" + (f" ({errors[0]})" if errors else "")
                rows.append({"group": "parallel", "label": label, "tool": "-", "expect": "ok", "verdict": verdict,
                             "note": note, "seconds": round(time.time() - started, 1)})
                print(f"{'  ' if verdict == 'PASS' else '!!'} parallel {label:<38} {verdict:<7} {time.time() - started:>5.1f}s  {note[:95]}", flush=True)
    report = Path(__file__).resolve().parent.parent.parent / "docs" / f"Edge_Case_Report_{TODAY.isoformat()}.json"
    report.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    problems = [r for r in rows if r["verdict"] != "PASS"]
    print(f"\n{len(rows) - len(problems)} of {len(rows)} edge cases handled correctly; {len(problems)} need attention. Report: {report}")
    for r in problems:
        print(f"  - [{r['verdict']}] {r['group']}: {r['label']} -> {r['note'][:140]}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(set(sys.argv[1:]))))

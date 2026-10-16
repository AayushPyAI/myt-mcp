"""Train tools (Trenitalia)."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import date, datetime, time
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.services import Services
from myt_mcp.trenitalia.parse import FARE_NOTES, check_rows, highlights, minutes, summarize_solutions

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
COMPACT_ABOVE = 10
MAX_TRAINS = 150     # a whole day; an all-stations search (Roma + Napoli) has 90+ trains, 10 per request
SORTS = ("departure", "price", "arrival", "duration")
TYPES = ("all", "frecce", "intercity", "regional")
FAR_DAYS = 30        # beyond this, a day with only Frecce trains usually means regional/Intercity are not published yet


def _clock(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _sort_key(sort_by: str):
    """Cheapest first for price; ties go to the earlier train. Arrival = departure + travel time, so a night train sorts correctly."""
    return {
        "departure": lambda t: (t["date"], t["departure"]),
        "price": lambda t: (t["cheapest_price"] if t["cheapest_price"] else 1e9, t["date"], t["departure"]),
        "arrival": lambda t: (t["date"], _clock(t["departure"]) + (minutes(t["duration"]) or 0)),
        "duration": lambda t: (minutes(t["duration"]) or 1e9, t["cheapest_price"] or 1e9, t["date"], t["departure"]),
    }[sort_by]
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# English names Trenitalia understands for the main Italian cities (typed name -> its Italian name)
EXONYMS = {"florence": "firenze", "rome": "roma", "venice": "venezia", "milan": "milano", "naples": "napoli",
           "turin": "torino", "genoa": "genova", "padua": "padova", "mantua": "mantova", "syracuse": "siracusa"}


def _plain(text: str) -> str:
    """Lower case, no accents or punctuation: 'Forlì' -> 'forli'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text).split())


def italian_name(query: str) -> str:
    """'Rome' -> 'Roma', 'Florence' -> 'Firenze': Trenitalia's own search puts other places first for English names."""
    words = query.strip().split()
    return " ".join(EXONYMS.get(_plain(w), w) for w in words)


# words Trenitalia abbreviates to one letter in station names ("Firenze S. M. Novella")
ABBREVIATED = {"santa": "s", "san": "s", "santo": "s", "maria": "m", "porta": "p", "giovanni": "g"}


def station_matches(query: str, name: str) -> bool:
    """True when `name` is really the station typed (not a fuzzy guess like romma -> Bromma)."""
    q, n = _plain(query), _plain(name)
    q = " ".join(EXONYMS.get(word, word) for word in q.split())
    tokens = n.split()
    return bool(q) and all(
        word in tokens or any(w.startswith(word) for w in tokens) or ABBREVIATED.get(word) in tokens for word in q.split()
    )


def register(mcp: MCPServer, services: Services) -> None:
    async def resolve(query: str, what: str) -> tuple[dict[str, Any], list[str]]:
        if not query or not query.strip():
            raise ToolError(f"{what} is empty.")
        if sum(ch.isalpha() for ch in query) < 2:
            raise ToolError(f"{what} {query!r} is not a station name. Use a city or station name such as Firenze or Roma Termini.")
        if len(query) > 80:
            raise ToolError(f"{what} is too long to be a station name.")
        matches = await services.trenitalia().find_stations(italian_name(query))
        words = italian_name(query).split()
        if not matches and len(words) > 1:
            # a long or spelled-out name ("Firenze Santa Maria Novella") finds nothing: search the city and keep only a real match
            matches = [m for m in await services.trenitalia().find_stations(words[0], limit=10) if station_matches(query, m["name"])]
        if not matches:
            raise ToolError(f"No Trenitalia station matches {query!r}. Try the Italian city name (e.g. Firenze, Roma, Venezia).")
        if not station_matches(query, matches[0]["name"]):
            closest = ", ".join(m["name"] for m in matches[:3])
            raise ToolError(f"{what} {query!r} is not an exact station name (closest: {closest}). "
                            "It was not used, so no train from the wrong station is shown. Check the spelling with train_find_station "
                            "and use the exact name.")
        return matches[0], [m["name"] for m in matches[1:4]]

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def train_find_station(query: str) -> list[dict[str, Any]]:
        """Find Trenitalia stations by name (Italian names work best, e.g. "Firenze", "Roma Termini").
        "(Tutte Le Stazioni)" means every station in that city."""
        if not query or not query.strip():
            raise ToolError("query is empty.")
        return await services.trenitalia().find_stations(query)

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def train_prices(
        from_station: str,
        to_station: str,
        travel_date: date,
        depart_after: str = "08:00",
        adults: int = 2,
        children: int = 0,
        max_results: int = MAX_TRAINS,
        sort_by: str = "departure",
        max_price: float | None = None,
        direct_only: bool = False,
        train_type: str = "all",
    ) -> dict[str, Any]:
        """Italian trains: use for any train question (times, how long, schedule, cheapest way between two Italian cities, רכבת). Live Trenitalia trains for one journey, from `depart_after` onwards: times, duration, changes,
        and the fares per class (Standard, Premium, Business, Executive; BASE = flexible, Economy = cheaper with
        restrictions) with seats left. Prices are for ALL passengers together, in EUR. One call = one search. By default it reads
        EVERY train of the travel_date from `depart_after` to the end of that day (25-40 trains for one station pair,
        4 requests ~15 s; an all-stations search such as "Roma" to "Napoli" has 90+ and takes ~40 s), so "cheapest" and "fastest" are real; trains of the next day are left out. With more than 10 trains each train is one short line (times, duration, changes, cheapest
        price); to get the fares of one train, search again with depart_after = its departure time and max_results=1.
        Choose the options from what the traveller wants: sort_by "price" (cheapest first; for a budget trip), "duration"
        (fastest first), "arrival" (must be there by a time) or "departure" (default); max_price = most the whole group
        may pay for the train (EUR, all passengers together; trains without a price are dropped); direct_only = no changes;
        train_type = "all" (default), "frecce" (high speed), "intercity" or "regional" (cheapest, slowest). Regional and Intercity
        trains are published only until the December timetable change (on 15 Oct 2026: up to 12 Dec 2026): for a later date only
        Frecce show, so say "cheapest of the Frecce; regional/Intercity are not published yet" and do not call it the cheapest overall."""
        if travel_date < date.today():
            raise ToolError("travel_date is in the past.")
        if not TIME.match(depart_after):
            raise ToolError("depart_after must look like 08:00 (24-hour HH:MM).")
        if not 1 <= adults <= 9 or not 0 <= children <= 9:
            raise ToolError("adults must be 1-9 and children 0-9.")
        if not 1 <= max_results <= MAX_TRAINS:
            raise ToolError(f"max_results must be between 1 and {MAX_TRAINS}.")
        if train_type not in TYPES:
            raise ToolError(f"train_type must be one of: {', '.join(TYPES)}.")
        if sort_by not in SORTS:
            raise ToolError(f"sort_by must be one of: {', '.join(SORTS)}.")
        if max_price is not None and max_price <= 0:
            raise ToolError("max_price must be more than 0 (EUR, all passengers together).")

        (origin, other_origins), (destination, other_destinations) = await asyncio.gather(
            resolve(from_station, "from_station"), resolve(to_station, "to_station"))
        if origin["id"] == destination["id"]:
            raise ToolError("from_station and to_station are the same station.")
        departure = datetime.combine(travel_date, time.fromisoformat(depart_after))
        data = await services.trenitalia().search_many(origin["id"], destination["id"], departure, adults, children, count=max_results,
                                                               frecce_only=train_type == "frecce", regional_only=train_type == "regional")
        trains, skipped = summarize_solutions(data, max_results)
        # A train Trenitalia gives no price for (a night train, a sold-out one) must not spoil the whole day: leave it out and say so.
        read = len(trains)      # trains read from Trenitalia, before anything below leaves some out
        unpriced = [t for t in trains if t["bookable"] and not (t["cheapest_price"] or 0) > 0]
        trains = [t for t in trains if not any(t is u for u in unpriced)]
        ensure("Trenitalia", check_rows(trains, departure.strftime("%Y-%m-%d %H:%M")))
        # Trenitalia answers with the next 24 hours from `depart_after`: an evening search also returns tomorrow's early trains
        next_day = [t for t in trains if t["date"] != travel_date.isoformat()]
        trains = [t for t in trains if t["date"] == travel_date.isoformat()]
        if train_type == "intercity":
            trains = [t for t in trains if any("intercity" in name.lower() for name in t["trains"])]
        if direct_only:
            trains = [t for t in trains if t["changes"] == 0]
        if max_price is not None:
            trains = [t for t in trains if t["cheapest_price"] and t["cheapest_price"] <= max_price]
        trains.sort(key=_sort_key(sort_by))

        answer: dict[str, Any] = {
            "from": origin["name"], "to": destination["name"], "date": travel_date.isoformat(),
            "depart_after": depart_after, "passengers": {"adults": adults, "children": children},
            "sorted_by": sort_by, "filters": {"max_price": max_price, "direct_only": direct_only, "train_type": train_type},
            "trains_read": read,
            **({"next_day_trains_left_out": len(next_day)} if next_day else {}),
            "prices_are_for": "all passengers together",
            "trains": trains,
            "at_a_glance": highlights(trains, complete=read < max_results),
            "source": "https://www.lefrecce.it/",
        }
        if len(trains) > COMPACT_ABOVE:     # a full day with every fare is ~50,000 tokens: keep one short line per train
            for t in trains:
                for key in ("fares", "fares_note", "date", "currency"):      # the stations stay: one search can mix several
                    t.pop(key, None)
            answer["fares_note"] = ("Fares are left out when many trains are listed. For the fares of one train, call train_prices again with "
                                    "depart_after = that train's departure time and max_results=1. cheapest_price is the lowest fare of the train, all passengers together, in EUR.")
        names = {f["fare"] for t in trains for f in t.get("fares") or []}
        if names:   # what each fare name means, only where Trenitalia's data (or our notes) say so
            others = sorted(names - set(FARE_NOTES))
            answer["fare_key"] = {**{n: FARE_NOTES[n] for n in sorted(names & set(FARE_NOTES))},
                                  **({"conditions_not_available_for": others,
                                      "note": "Do not describe the conditions of these fares; the data does not give them. Say so or check trenitalia.com."}
                                     if others else {})}
        stations = {"from": sorted({t["from"] for t in trains if t.get("from")}), "to": sorted({t["to"] for t in trains if t.get("to")})}
        if len(stations["from"]) > 1 or len(stations["to"]) > 1:
            answer["stations_note"] = (f"These trains use different stations (from: {', '.join(stations['from'])}; to: {', '.join(stations['to'])}). "
                                       "Show the departure and arrival station of EVERY train you name, and compare times only between the same stations. "
                                       "If the traveller needs one station (e.g. Roma Termini, Napoli Centrale), search again with that exact station name.")
        if other_origins or other_destinations:
            answer["other_matching_stations"] = {"from": other_origins, "to": other_destinations}
        if not read and train_type in ("regional", "intercity"):
            answer["note"] = (f"No {train_type} trains found for this route and date. For a date after the December timetable change they are probably "
                              "not published yet (on 15 Oct 2026 regional trains were published up to 12 Dec 2026); try train_type 'all' or 'frecce'.")
        elif not read:
            answer["note"] = "Trenitalia has no trains for this route and time."
        elif not trains:
            answer["note"] = (f"{read} trains were read, none passes the filters (max_price {max_price}, direct_only {direct_only}). "
                              "Say so, and offer a higher price or allowing changes.")
        elif read >= max_results:
            answer["note"] = (f"Read the first {read} trains from {depart_after}; there may be later trains. Tell the operator, "
                              "and search again with a later depart_after or a higher max_results (up to 150) to see them.")
        if (train_type == "all" and trains and (travel_date - date.today()).days > FAR_DAYS
                and all(any("frecc" in name.lower() for name in t["trains"]) for t in trains)):
            answer["types_note"] = ("Only Frecce (high-speed) trains are listed. Regional and Intercity trains are not published yet for this date "
                                    "(Trenitalia publishes them only until the December timetable change). Call the 'cheapest' the cheapest Frecce, "
                                    "not the cheapest train overall, and do not predict that cheaper regional or Intercity fares will appear.")
        warnings = []
        if skipped:
            warnings.append(f"{skipped} results were left out because Trenitalia sent them in an unexpected format.")
        if unpriced:
            names = ", ".join(f"{', '.join(u['trains'])} {u['departure']}" for u in unpriced[:3])
            warnings.append(f"{len(unpriced)} train(s) were left out because Trenitalia gave no price for them ({names}); they may be sold out. "
                            "Do not guess a price; check them on trenitalia.com if the traveller wants them.")
        if warnings:
            answer["warning"] = " ".join(warnings)
        return answer

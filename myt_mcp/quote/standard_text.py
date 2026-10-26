"""The standard Hebrew "price includes / does not include" lines of a new quotation, chosen from the trip's itinerary.

Nothing here writes to MYT (the public API cannot: the lists are typed on the MYT screen, see docs/Standard_Includes_Text_2026-10-23.md). The Hebrew
text and the rule of every line are DATA (standard_text_he.json); this module only reads a trip (`GetTrip/v3`) into a few yes/no facts and applies
the rules. Lines the operator has not confirmed are marked `draft` (written when their rule says so, listed for a yes) or `open` (never written
until she decides); every line comes with the question that settles it. Checked on 8 real quotations on 26 Oct 2026 (tests/fixtures/standard_text_trips.json).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from myt_mcp.myt.summaries import quotation_summary, trip_summary

CATALOG = json.loads((Path(__file__).with_name("standard_text_he.json")).read_text(encoding="utf-8"))
ISRAEL = ("ben gurion", "tel aviv")
TRANSFER_WORDS = re.compile(r"transfer|trf", re.I)
DEFAULT_STARS = "4/5"


def _israel(place: Any) -> bool:
    return any(w in str(place).lower() for w in ISRAEL)


def trip_facts(v3: dict[str, Any]) -> dict[str, bool]:
    """What the itinerary and the quotation lines of a trip say. A fact is False when the data has no sign of it (the caller can then ask)."""
    summary = trip_summary(v3)
    quote = quotation_summary(v3) or {}
    lines = [line for package in quote.get("packages") or [] for line in package.get("lines") or []]
    flights = summary["flights"]
    cars = [line for line in lines if line.get("transport") == "Car"]
    return {
        "hotels": bool(summary["hotels"]) or any(line.get("category") == "Lodging" and line.get("line_type") == "Room" for line in lines),
        # a car line that is not named as a transfer is a rental (Day lines: 'VW T-Cross', 'IFAR Nissan Qashqai automatic')
        "rental_car": any(not TRANSFER_WORDS.search(str(line.get("product"))) for line in cars),
        # a flight with neither end in Israel (checked on the 8 quotations: the same answer as listing the Portuguese airports)
        "domestic_flight": any(not _israel(f["from"]) and not _israel(f["to"]) for f in flights),
        "lounge": any("lounge" in str(line.get("product")).lower() for line in lines) or any(_israel(f["from"]) for f in flights),
    }


def _applies(rule: str, facts: dict[str, bool]) -> bool:
    if rule == "always":
        return True
    if rule == "never":
        return False
    return bool(facts.get(rule))


def choose(facts: dict[str, bool], stars: str | None = None) -> dict[str, Any]:
    """-> {"includes": [hebrew lines], "not_includes": [...], "to_confirm": [{line, status, question}]}.

    `confirmed` lines and `draft` lines are written when their rule applies; `open` lines are never written. Every draft or open line, and the hotel stars when
    the operator gave none, appears in `to_confirm` with its question."""
    out: dict[str, Any] = {"includes": [], "not_includes": [], "to_confirm": []}
    for side in ("includes", "not_includes"):
        for entry in CATALOG[side]:
            applies = _applies(entry["rule"], facts)
            if applies:
                out[side].append(entry["text"].replace("{stars}", stars or entry.get("stars_default", DEFAULT_STARS)))
            if entry["status"] != "confirmed" and (applies or entry["status"] == "open"):
                out["to_confirm"].append({"line": entry["id"], "status": entry["status"], "written": applies, "question": entry["question"]})
            elif entry["id"] == "hotels" and applies and not stars:
                out["to_confirm"].append({"line": entry["id"], "status": "default", "written": True, "question": entry["question"]})
    return out


def standard_text_for(v3: dict[str, Any], stars: str | None = None) -> dict[str, Any]:
    facts = trip_facts(v3)
    return {"facts": facts, **choose(facts, stars)}

"""compose_summary: ONE final text for the operator, built by the server from the answers it composed itself.

2 Nov 2026 (all-in-one Lisbon run): the assistant's final message was its own prose. It had no "Sources checked / Not checked" line, no Picks table, filters nobody asked for (direct flight, checked bag, refundable fare,
breakfast, EUR 200 a night, "full cover") written as the operator's wishes, and check_answer was never called. Here the picks, the filters with their labels, what was not checked and the links of every kind that was
composed are copied from what compose_answer kept (composed.SUMMARIES); nothing is typed, priced or chosen by the assistant. A kind that was asked for and never composed is named as not searched.
"""

from __future__ import annotations

import re
from typing import Any

ORDER = ["flights", "hotels", "transfers", "cars", "activities", "trains", "lounges"]
TITLES = {"flights": "Flights", "hotels": "Hotels", "transfers": "Transfers", "cars": "Cars", "activities": "Activities", "trains": "Trains", "lounges": "Lounges"}
# the sentences of a kind's notes that change how a pick may be read: a narrowed source, a filter not applied, another time or age than the one asked, a wish a row does not confirm
KEEP_NOTE = re.compile(r"narrowed|not applied|searched at|15-minute|young|assumed|not confirmed|does not say|outside|only a damage|not checkable|no .{0,20} was checked", re.I)
MAX_NOTE = 700


def _kept_sentences(notes: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", notes or "")
    kept = [s for s in sentences if KEEP_NOTE.search(s)]
    text = " ".join(kept)
    return text if len(text) <= MAX_NOTE else text[:MAX_NOTE].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"


def build_summary(summaries: dict[str, dict[str, Any]], request: str | None = None, asked: list[str] | None = None) -> dict[str, Any]:
    kinds = [k for k in ORDER if k in summaries] + [k for k in summaries if k not in ORDER]
    wanted = [k.strip().lower() for k in (asked or []) if k and k.strip()]
    missing = [k for k in wanted if k not in summaries]
    if not kinds:
        return {"ok": False, "problems": ["no compose_answer result of the last 3 hours exists on this server: read the sources and call compose_answer for each kind first"],
                "next": "Call task_plan, read the sources, call compose_answer for each kind; then compose_summary."}
    lines: list[str] = []
    for kind in kinds:
        for needs in summaries[kind].get("needs_you") or []:
            if needs not in lines:
                lines.append(needs)
    lines += ["Summary of everything searched in this conversation. The server built it from its own answers: show it exactly as written."]
    if request and request.strip():
        lines += ["", "What the operator asked (their own words): " + " ".join(request.split())[:600]]
    lines += ["A line marked (operator) is something the operator said; anything else under 'Filters used' was assumed or defaulted and is labelled so."]
    for kind in kinds:
        s = summaries[kind]
        lines += ["", f"## {TITLES.get(kind, kind.title())}", s.get("sources") or "Sources checked: not recorded"]
        if s.get("filters"):
            lines.append("Filters used: " + "; ".join(s["filters"]))
        if s.get("pickup_time"):
            lines.append(f"Pick-up time used on every source: {s['pickup_time']}")
        if s.get("checked_at"):
            lines.append(f"Checked: {s['checked_at']}")
        for g in s.get("groups") or []:
            lines += ["", f"### {g['group']}", "", "| Pick | Option | Reason |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in g.get("picks") or []]
            lines += [f"- {n}" for n in g.get("notes") or []]
        careful = _kept_sentences(s.get("notes") or "")
        if careful:
            lines += ["", "Read before quoting: " + careful]
        if s.get("links"):
            lines += ["", s["links"]]
    if missing:
        lines += ["", "Not searched in this conversation: " + ", ".join(TITLES.get(k, k) for k in missing) + " (no compose_answer for it): ask the operator whether to search it, or say it was not searched."]
    return {"ok": True, "answer": "\n".join(lines), "kinds": kinds, "not_searched": missing,
            "next": "Show `answer` to the operator exactly as written: no check_answer call is needed (every row, pick and reason in it was kept from compose_answer's own texts). Never add a price, a pick or a filter of your own to it; "
                    "you may add questions after it. The full tables of each kind are in the compose_answer answers above."}

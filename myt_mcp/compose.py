"""Builds the operator's answer from structured offers, so the rules live in code and not in Claude's memory.

Claude gathers (tools and Chrome pages) and hands over rows; this module checks the inputs against the playbook, fills every
missing field with 'not shown', picks Cheapest / Best fit / Most flexible / Recommended by fixed rules, and writes the answer
with the required lines and links. Claude shows the text as it is. Nothing here reads a site or changes anything.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

# the details every kind of offer must show ("not shown" when the source did not give them)
REQUIRED_DETAILS: dict[str, list[str]] = {
    "flights": ["stops", "fare", "checked_bag", "refund_change", "per_person"],
    "hotels": ["stars", "score", "reviews", "distance_from_centre", "meal", "cancellation", "room_bed"],
    "cars": ["company", "gearbox", "seats_bags", "excess", "fuel", "mileage", "deposit", "cancellation"],
    "transfers": ["capacity", "waiting_time", "cancellation", "provider", "meeting_point"],
    "trains": ["class_fare", "changes", "seats_left", "conditions"],
    "activities": ["duration", "start_times", "language", "meeting_point", "cancellation", "private_or_group"],
    "lounges": ["terminal", "entry_window", "stay", "adult_price", "child_price"],
}
NEEDS_FILTERS = {"flights", "hotels", "cars", "transfers", "trains", "activities"}
NEEDS_SUPPLIER_CHECK = {"flights", "hotels", "cars", "transfers", "activities"}
NEEDS_PICKUP = {"cars", "transfers"}
BANNED_REASONS = ("for time", "out of scope", "this pass", "keep it short", "say the word", "not asked", "didn't ask", "did not ask", "on request",
                  "happy to run", "would need the quotation", "no myt trip", "trip number")
ALLOWED_REASON_WORDS = ("browser", "chrome", "login", "captcha", "block", "not served", "does not sell", "doesn't sell", "does not fly", "did not answer",
                        "no flights", "not sold", "refused", "not available", "switched off")
SOURCE_WORDS = ("operator", "trip", "default")


class Offer(BaseModel):
    group: str = Field("Options", description="The leg, stay or item this row belongs to (for example 'FLR -> LIS 6 Mar 2027').")
    source: str = Field(description="Where you read it: 'TAP', 'RateHawk', 'Ofran', 'Skyscanner'...")
    name: str = Field(description="The option as the source names it: flight and times, hotel, car, vehicle, activity.")
    price_total: float | None = Field(None, description="The price exactly as the source shows it, for the whole group or stay.")
    currency: str | None = Field(None, description="EUR, USD, GBP... as the source shows it; never converted.")
    price_basis: str = Field("group total", description="'group total', 'per person x N (calculated)', 'whole rental', 'per vehicle'...")
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict, description="Fields from the source, keyed as in the playbook (stops, fare, checked_bag...). Leave out what it did not show.")
    flexible: bool | None = Field(None, description="True only if the source says refundable / free cancellation / free change.")
    fits: bool | None = Field(None, description="True if it meets EVERY wish of the operator (bag, direct, meal...). None if no wishes.")
    quotable: bool = Field(True, description="False for comparison-only rows (Skyscanner, an agent's advert, a public Ofran price).")
    connecting: bool = Field(False, description="True for a connecting itinerary shown because no direct exists.")
    supplier: str | None = Field(None, description="The company to check in MYT (airline, hotel, rental company, provider).")
    preferred_reason: str | None = Field(None, description="Why this option suits the trip better, from a source or the trip data (for example 'departs 12:20, the trip plans 12:10'). Used for Best fit.")
    link: str | None = None


class SourceRead(BaseModel):
    name: str
    read: int | None = Field(None, description="How many results you read.")
    of: int | None = Field(None, description="How many exist after the filters (M in 'N of M').")
    link: str | None = Field(None, description="The exact search or results page (the tool's `source`/`url`, or the Chrome page address).")


class NotChecked(BaseModel):
    name: str
    reason: str


def _money(v: float | None, cur: str | None) -> str:
    return "not shown" if v is None else f"{v:,.2f} {cur or ''}".strip()


def _cell(v: Any) -> str:
    if v is None or v == "":
        return "not shown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v).replace("|", "/").replace("\n", " ")


def validate(kind: str, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
             myt_supplier: dict[str, str], pickup_time: str | None) -> list[str]:
    problems: list[str] = []
    if kind not in REQUIRED_DETAILS:
        problems.append(f"kind must be one of {sorted(REQUIRED_DETAILS)}")
    if not sources_read:
        problems.append("sources_read is empty: list every source you read")
    for s in sources_read:
        if not s.link or not re.match(r"https?://\S+", s.link) or re.fullmatch(r"https?://[^/]+/?", s.link):
            problems.append(f"{s.name}: give the exact search or results page as `link`, not a home page")
        if s.read is None or s.of is None:
            problems.append(f"{s.name}: give `read` and `of` (N of M)")
    for n in not_checked:
        low = n.reason.lower()
        if any(b in low for b in BANNED_REASONS):
            problems.append(f"{n.name}: '{n.reason}' is not an allowed reason; read it, or use: no browser tool, login/captcha/block, route not served, did not answer")
        elif not any(w in low for w in ALLOWED_REASON_WORDS):
            problems.append(f"{n.name}: the reason must be one of: no browser tool in this chat, login/captcha/block, route not served by the source, source did not answer")
    if kind in NEEDS_FILTERS:
        if not filters_used:
            problems.append("filters_used is empty: write each filter with its source, e.g. 'direct only (trip default)'")
        for f in filters_used:
            if not any(w in f.lower() for w in SOURCE_WORDS):
                problems.append(f"filter '{f}': say where it comes from (operator / trip / default)")
    if not offers:
        problems.append("offers is empty")
    names = {s.name.lower() for s in sources_read}
    for o in offers:
        if o.source.lower() not in names:
            problems.append(f"offer '{o.name}' comes from '{o.source}', which is not in sources_read")
        if o.price_total is not None and not o.currency:
            problems.append(f"offer '{o.name}': price without a currency")
    if kind in NEEDS_PICKUP and not pickup_time:
        problems.append("pickup_time is required for cars and transfers (from the trip's flight, or asked): the same on every source")
    return list(dict.fromkeys(problems))


def _primary_currency(rows: list[Offer]) -> str | None:
    quotable = [o for o in rows if o.price_total is not None and o.quotable]
    pool = quotable or [o for o in rows if o.price_total is not None]
    if not pool:
        return None
    counts: dict[str, int] = {}
    for o in pool:
        counts[o.currency or ""] = counts.get(o.currency or "", 0) + 1
    return max(counts, key=lambda c: (counts[c], c == pool[0].currency))


def picks(kind: str, rows: list[Offer], sorted_by_price: bool) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Cheapest, Best fit, Most flexible, Recommended for one group: (label, option, reason) rows and notes. All reasons come from the rows' own numbers."""
    notes: list[str] = []
    cur = _primary_currency(rows)
    priced = [o for o in rows if o.price_total is not None and (o.currency or "") == cur]
    other = {o.currency for o in rows if o.price_total is not None and (o.currency or "") != cur}
    if other:
        notes.append(f"Other currencies ({', '.join(sorted(str(c) for c in other))}) are shown but not compared: no conversion without the operator's rate.")
    if not priced:
        return [(p, "not determined", "no priced option") for p in ("Cheapest", "Best fit", "Most flexible", "Recommended")], notes
    cheapest = min(priced, key=lambda o: o.price_total)
    cheap_reason = f"lowest of {len(priced)} priced option(s) in {cur}"
    if kind == "hotels" and not sorted_by_price:
        cheap_reason = f"lowest of the {len(priced)} read, but the list sorted by price was NOT read: not the cheapest overall"
    if not cheapest.quotable:
        cheap_reason += " (comparison row, not quotable)"
    quotable = [o for o in priced if o.quotable and not o.connecting]
    if not quotable:
        quotable = [o for o in priced if o.quotable]
    wishes_given = any(o.fits is not None for o in rows)
    fitting = [o for o in quotable if o.fits] if wishes_given else list(quotable)
    if wishes_given and cheapest.fits is False:
        cheap_reason += "; it does NOT meet every wish of the operator"
    preferred = [o for o in fitting if o.preferred_reason]
    if preferred:
        best = min(preferred, key=lambda o: o.price_total)
        best_reason = best.preferred_reason or ""
    elif fitting:
        best = min(fitting, key=lambda o: o.price_total)
        best_reason = "cheapest option that meets every wish of the operator" if wishes_given else "no extra wishes were given: the cheapest quotable option"
    else:
        best = None
        best_reason = "no quotable option meets every wish"
    flex = [o for o in fitting if o.flexible] or [o for o in quotable if o.flexible]
    flexible = min(flex, key=lambda o: o.price_total) if flex else None
    cheapest_fitting = min(fitting, key=lambda o: o.price_total) if fitting else None
    if best is None:
        rec, rec_reason = None, "not determined: " + best_reason
    elif cheapest_fitting is not None and best.price_total > cheapest_fitting.price_total * 1.10:
        pct = (best.price_total / cheapest_fitting.price_total - 1) * 100
        rec, rec_reason = cheapest_fitting, f"the Best fit is {pct:.1f}% above the cheapest option that meets every wish (more than 10%), so that one is recommended"
    elif best is cheapest_fitting:
        rec, rec_reason = best, "the Best fit, and the cheapest option that meets every wish"
    else:
        rec, rec_reason = best, "the Best fit; within 10% of the cheapest option that meets every wish"

    def label(o: Offer | None) -> str:
        return "not determined" if o is None else f"{o.source}: {o.name} - {_money(o.price_total, o.currency)} ({o.price_basis})"
    if kind == "hotels":      # a caution made only from the row's own numbers
        for title, o in (("Best fit", best), ("Recommended", rec)):
            if o is None:
                continue
            try:
                score = float(str(o.details.get("score")))
            except ValueError:
                score = None
            reviews = o.details.get("reviews")
            if (score is not None and score < 7.5) or (isinstance(reviews, int) and reviews < 50) or o.details.get("score") in (None, ""):
                notes.append(f"Caution on the {title} ({o.name}): score {o.details.get('score') or 'not shown'} from {reviews if reviews is not None else 'not shown'} review(s). "
                             "Ask the operator for a minimum score or star level if this is too low.")
                break
    rows_out = [("Cheapest", label(cheapest), cheap_reason),
                ("Best fit", label(best), best_reason),
                ("Most flexible", label(flexible), "the cheapest option the source says is refundable or free to cancel" if flexible else "not determined: no refundable or free-cancellation option was read"),
                ("Recommended", label(rec), rec_reason)]
    return rows_out, notes


def compose(kind: str, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
            myt_supplier: dict[str, str], pickup_time: str | None, sorted_by_price: bool, notes: str) -> dict[str, Any]:
    problems = validate(kind, filters_used, sources_read, not_checked, offers, myt_supplier, pickup_time)
    if problems:
        return {"ok": False, "problems": problems, "next": "Fix every problem (read the source, or write an allowed reason / the missing field) and call compose_answer again. Do not write the answer yourself."}
    required = REQUIRED_DETAILS[kind]
    lines: list[str] = []
    lines.append("Sources checked: " + "; ".join(f"{s.name} ({s.read} of {s.of} read)" for s in sources_read)
                 + " | Not checked: " + ("; ".join(f"{n.name} ({n.reason})" for n in not_checked) or "none"))
    if filters_used:
        lines.append("Filters used: " + "; ".join(filters_used))
    if pickup_time:
        lines.append(f"Pick-up time used on every source: {pickup_time}")
    gaps: dict[str, int] = {}
    groups: dict[str, list[Offer]] = {}
    for o in offers:
        groups.setdefault(o.group, []).append(o)
    supplier_lines: dict[str, str] = {}
    for g, rows in groups.items():
        keys = list(dict.fromkeys(required + [k for o in rows for k in o.details if k not in required]))
        lines += ["", f"### {g}", "", "| Source | Option | " + " | ".join(k.replace("_", " ") for k in keys) + " | Price | Basis | Quotable | Link |",
                  "|" + "---|" * (len(keys) + 6)]
        for o in sorted(rows, key=lambda r: (r.price_total is None, r.price_total or 0)):
            cells = []
            for k in keys:
                v = o.details.get(k)
                if v is None or v == "":
                    gaps[k] = gaps.get(k, 0) + 1
                cells.append(_cell(v))
            tag = " (connecting)" if o.connecting else ""
            lines.append(f"| {o.source} | {_cell(o.name)}{tag} | " + " | ".join(cells)
                         + f" | {_money(o.price_total, o.currency)} | {_cell(o.price_basis)} | {'yes' if o.quotable else 'comparison only'} | {o.link or 'see Sources'} |")
        pk, pnotes = picks(kind, rows, sorted_by_price)
        lines += ["", "| Pick | Option | Reason |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in pk] + [f"- {n}" for n in pnotes]
        for label, text, _ in pk:
            if label in ("Cheapest", "Best fit", "Recommended") and text != "not determined":
                m = next((o for o in rows if text.startswith(f"{o.source}: {o.name}")), None)
                if m and m.supplier:
                    supplier_lines[m.supplier] = myt_supplier.get(m.supplier, "not checked: not provided")
    if kind in NEEDS_SUPPLIER_CHECK:
        lines += ["", "In MYT supplier? " + ("; ".join(f"{s}: {v}" for s, v in supplier_lines.items()) or "no supplier given for the picks: not checked")]
    if gaps:
        lines += ["", "Not shown by the sources: " + ", ".join(f"{k.replace('_', ' ')} (in {n} row(s))" for k, n in gaps.items()) + "."]
    lines += ["", "Sources: " + " | ".join(f"{s.name}: {s.link}" for s in sources_read)]
    if notes.strip():
        lines += ["", "Notes (assistant's judgement, not from a source): " + notes.strip()]
    return {"ok": True, "answer": "\n".join(lines), "next": "Show `answer` to the operator exactly as written. Do not change a number, a pick or a reason. You may add questions after it."}

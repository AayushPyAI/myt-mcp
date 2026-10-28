"""Builds the operator's answer from structured offers, so the rules live in code and not in Claude's memory.

Claude gathers (tools and Chrome pages) and hands over rows; this module checks the inputs against the playbook, fills every
missing field with 'not shown', picks Cheapest / Best fit / Most flexible / Recommended by fixed rules, and writes the answer
with the required lines and links. Claude shows the text as it is. Nothing here reads a site or changes anything.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, field_validator

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
MAX_ROWS_BY_KIND = {"flights": 20, "hotels": 20, "cars": 20, "transfers": 20, "trains": 20, "activities": 30}      # rows the table shows per group; the picks always use every row read
PER_SOURCE_MIN_ROWS = 3
ALLOWED_REASON_WORDS = ("browser", "chrome", "login", "captcha", "block", "not served", "does not sell", "doesn't sell", "does not fly", "did not answer",
                        "no flights", "not sold", "refused", "not available", "switched off", "could not be read", "layout", "window too narrow", "operator excluded", "operator asked for", "operator named", "place not found", "place not offered", "no matching place")      # "operator excluded": the operator named the sources to use and left this one out; the answer shows it
SOURCE_WORDS = ("operator", "trip", "default", "server", "agency", "assistant")      # "server": a filter the server itself wrote, e.g. the euro conversion; "assistant": a choice the assistant made and says so (28 Oct 2026: "(assistant: no hotel picked)" and "(my judgement)" were refused)


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
    unconfirmed: list[str] = Field(default_factory=list, description="Wishes of the operator this row could not be checked against (set by the server, never typed): the row stays in the table and is never a pick.")

    @field_validator("details")
    @classmethod
    def _one_form_of_key(cls, v: dict) -> dict:
        """'meeting point', 'Meeting-Point' and 'meeting_point' are one column (27 Oct 2026: a chat typed spaces and the table got both)."""
        out: dict = {}
        for k, val in v.items():
            key = re.sub(r"[\s\-]+", "_", str(k).strip().lower())
            key = KEY_ALIASES.get(key, key)
            if key not in out or out[key] in (None, ""):
                out[key] = val
        if "capacity" not in out and (out.get("max_passengers") is not None or out.get("max_bags") is not None or out.get("max_standard_bags") is not None):
            people, bags = out.get("max_passengers"), out.get("max_bags") if out.get("max_bags") is not None else out.get("max_standard_bags")
            out["capacity"] = "up to " + " / ".join(x for x in (f"{people} people" if people is not None else "", f"{bags} bags" if bags is not None else "") if x)
            for k in ("max_passengers", "max_bags", "max_standard_bags"):
                out.pop(k, None)      # said once, in the column the other sources use
        return out


class SourceRead(BaseModel):
    name: str
    read: int | None = Field(None, description="How many results you read.")
    of: int | None = Field(None, description="How many exist after the filters (M in 'N of M').")
    link: str | None = Field(None, description="The exact search or results page (the tool's `source`/`url`, or the Chrome page address).")


class NotChecked(BaseModel):
    name: str
    reason: str


def directory_status(name: str) -> str:
    """'In MYT supplier?' from the local directory of the 31 suppliers read from MYT on 22 Oct 2026. A name that is not in it is NOT proof that MYT lacks the supplier: it stays 'not checked'."""
    from myt_mcp.myt.supplier_directory import find_suppliers
    hits = find_suppliers(name)
    if not hits:
        return "not checked: not provided (not in the local supplier directory; search it in the quotation's Search supplier box)"
    s = hits[0]
    return f"yes: {s['name']} (supplier id {s['id']}, type {s.get('type') or 'not shown'}; from the local supplier directory, 22 Oct 2026)"


def _money(v: float | None, cur: str | None) -> str:
    return "not shown" if v is None else f"{v:,.2f} {cur or ''}".strip()


def _quotable_cell(o: "Offer") -> str:
    base = "yes" if o.quotable else "comparison only"
    return f"{base} (not confirmed: {', '.join(o.unconfirmed)})" if o.unconfirmed else base


KEY_ALIASES = {"free_cancellation": "cancellation", "free_cancel": "cancellation", "waiting": "waiting_time", "meeting": "meeting_point"}      # the words a chat writes for the columns the server asks for (28 Oct 2026: Kiwitaxi rows)


DETAIL_CAP = 200      # characters of one detail cell (includes, know before, meeting point...): a longer text is cut at a word and ends with "…" (28 Oct 2026: cells were cut in the middle of a word and the answers were so long that the chat shortened them by hand)


def _cell(v: Any, cap: int | None = None) -> str:
    if v is None or v == "":
        return "not shown"
    if isinstance(v, bool):
        return "yes" if v else "no"
    text = str(v).replace("|", "/").replace("\n", " ")
    if cap and len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    return text


def validate(kind: str, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
             myt_supplier: dict[str, str], pickup_time: str | None, nothing_found: bool = False) -> list[str]:
    problems: list[str] = []
    if kind not in REQUIRED_DETAILS:
        problems.append(f"kind must be one of {sorted(REQUIRED_DETAILS)}")
    if not sources_read and not nothing_found:
        problems.append("sources_read is empty: list every source you read")
    for s in sources_read:
        urls = re.findall(r"https?://[^\s;|]+", s.link or "")      # one link, or one per leg ("TLV to LIS, 10 Dec 2026: https://...; LIS to TLV, ...: https://...")
        if not urls or any(re.fullmatch(r"https?://[^/]+/?", u) for u in urls):
            problems.append(f"{s.name}: give the exact search or results page as `link`, not a home page")
        if s.read is None or s.of is None:
            problems.append(f"{s.name}: give `read` and `of` (N of M)")
    for n in not_checked:
        low = n.reason.lower()
        if any(b in low for b in BANNED_REASONS):
            problems.append(f"{n.name}: '{n.reason}' is not an allowed reason; read it, or use: no browser tool, login/captcha/block, route not served, did not answer")
        elif not any(w in low for w in ALLOWED_REASON_WORDS):
            problems.append(f"{n.name}: the reason must be one of: no browser tool in this chat, login/captcha/block, route not served by the source, place not found in the source's From/To box (say which place), source did not answer, 'could not be read: <the script's own error>', or 'operator asked for <sources> only' when the operator named the sources to use")
    if kind in NEEDS_FILTERS:
        if not filters_used:
            problems.append("filters_used is empty: write each filter with its source, e.g. 'direct only (trip default)'")
        for f in filters_used:
            if not any(w in f.lower() for w in SOURCE_WORDS):
                problems.append(f"filter '{f}': say where it comes from (operator / trip / default)")
    if not offers and not nothing_found:
        problems.append("offers is empty: pass the site script's answer parts in site_results (or the rows you read in offers)")
    names = {s.name.lower() for s in sources_read}
    if kind == "hotels":      # one stay is ONE group, so Cheapest / Best fit / Recommended compare every source; a group of one source each hides the better site
        by_group: dict[str, set[str]] = {}
        for o in offers:
            by_group.setdefault(o.group, set()).add(o.source.lower())
        if len(by_group) > 1 and all(len(v) == 1 for v in by_group.values()) and len({next(iter(v)) for v in by_group.values()}) == len(by_group):
            problems.append(f"each source is in its own group ({', '.join(sorted(by_group))}): put the options of one stay in ONE `group` (same text on every source) so the picks compare all sources; use separate groups only for different cities")
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


def distance_km(text: Any) -> float | None:
    """'1.6 km from the Lisbon center' -> 1.6, '214 m from ...' -> 0.214; None when the text has no distance."""
    m = re.match(r"\s*\(?\s*([\d.,]+)\s*(km|m)\b", str(text or ""), re.I)      # "(0.9 km from center)" (Arbitrip) and "214 m from the Lisbon center" (RateHawk)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if m.group(2).lower() == "km" else value / 1000


# columns only some sources have (which sort tab a row came from): a source without it is not "hiding" it
NOT_A_GAP = {"from_tab"}


def meets_limits(price: float | None, distance_text: Any, wishes: dict[str, Any]) -> bool:
    """The operator's budget (whole stay) and distance limits; a row that cannot show the number does not meet a limit that was asked."""
    if wishes.get("max_total") is not None and (price is None or price > float(wishes["max_total"])):
        return False
    if wishes.get("max_distance_km") is not None:
        km = distance_km(distance_text)
        if km is None or km > float(wishes["max_distance_km"]):
            return False
    return True


def _solid(o: Offer) -> bool:
    """A hotel whose own numbers are not thin: score 7.5 or more from at least 50 reviews."""
    try:
        return float(str(o.details.get("score"))) >= 7.5 and int(o.details.get("reviews")) >= 50
    except (TypeError, ValueError):
        return False


def cheaper_unconnected_notes(kind: str, rows: list[Offer]) -> list[str]:
    """A comparison row (Skyscanner...) cheaper than the best quotable one, whose airline no connected source sells, must not just disappear into 'comparison only': say who, how much, and where to check
    (23 Oct 2026: Skyscanner showed Arkia at 531 EUR for the group against 1,283 EUR quotable; no connected source sells Arkia)."""
    if kind != "flights":
        return []
    cur = _primary_currency(rows)
    quotable = [o for o in rows if o.quotable and o.fits is not False and o.price_total is not None and (o.currency or "") == cur]
    if not quotable:
        return []
    best = min(o.price_total for o in quotable)
    sold = " ".join(f"{o.name} {o.supplier or ''} {o.source}".lower() for o in rows if o.quotable)      # the airline's own source (TAP rows are named by flight number) counts as selling it
    notes = []
    for o in sorted((o for o in rows if not o.quotable and o.price_total is not None and (o.currency or "") == cur and o.price_total < best), key=lambda r: r.price_total):
        airline = re.split(r"\s+\d{1,2}:\d{2}", o.name, maxsplit=1)[0].strip()
        first = airline.lower().split(" ")[0]
        if first and first not in sold and not any(first in (x.name or "").lower() for x in quotable):
            notes.append(f"Cheaper, but no connected source sells it: {o.source} lists {o.name} at {o.price_total:,.2f} {cur} against {best:,.2f} {cur} for the best quotable option. "
                         f"Check {airline}'s own website (their price may need a different bag or refund condition than the wishes) before quoting; it is not a pick.")
            break
    return notes


PRICE_GAP = 2.0       # the cheapest row of one source is this many times cheaper than the cheapest of another


def price_gap_notes(kind: str, rows: list[Offer]) -> list[str]:
    """Sources that sell almost the same thing (a transfer, a car) can differ by a lot because of the vehicle class, the drop-off point or what is included: say it, so the cheapest is not quoted blindly
    (24 Oct 2026: RateHawk Economy 13 EUR against Kiwitaxi Comfort 40 EUR for the same airport transfer, the RateHawk drop-off was a hotel next to the square)."""
    if kind not in ("transfers", "cars"):
        return []
    cur = _primary_currency(rows)
    best: dict[str, float] = {}
    for o in rows:
        if o.quotable and o.fits is not False and o.price_total is not None and (o.currency or "") == cur:
            best[o.source] = min(best.get(o.source, o.price_total), o.price_total)
    if len(best) < 2:
        return []
    low, high = min(best, key=best.get), max(best, key=best.get)
    if best[low] <= 0 or best[high] / best[low] < PRICE_GAP:
        return []
    return [f"Big price gap between sources: the cheapest {low} row is {best[low]:,.2f} {cur} and the cheapest {high} row is {best[high]:,.2f} {cur}. The vehicle class, the pick-up or drop-off point and what is included can differ: compare them row by row before quoting the cheapest."]


def flexible_reason(priced: list["Offer"]) -> str:
    """Why there is no 'Most flexible': say when only comparison rows (not quotable) show free cancellation (28 Oct 2026: 'no free-cancellation option was read' next to rows that carry the flag)."""
    cmp_flex = [o for o in priced if o.flexible and not o.quotable]
    if cmp_flex:
        return f"not determined: no quotable option shows free cancellation (only {len(cmp_flex)} comparison-only row(s) do, from {', '.join(sorted({o.source for o in cmp_flex}))})"
    return "not determined: no refundable or free-cancellation option was read"


def picks(kind: str, rows: list[Offer], sorted_by_price: bool, complete: bool = False) -> tuple[list[tuple[str, str, str]], list[str]]:
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
    if kind == "hotels" and not sorted_by_price and not complete:       # complete: every source of this group was read to its last row, so nothing cheaper was left unread
        cheap_reason = f"lowest of the {len(priced)} read, but the list sorted by price was NOT read: not the cheapest overall"
    if not cheapest.quotable:
        cheap_reason += " (comparison row, not quotable)"
    quotable = [o for o in priced if o.quotable and not o.connecting]
    if not quotable:
        quotable = [o for o in priced if o.quotable]
    wishes_given = any(o.fits is not None or o.unconfirmed for o in rows)
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
        unchecked = [o for o in quotable if o.unconfirmed]
        best_reason = ("no quotable option is confirmed to meet every wish (" + f"{len(unchecked)} could not be checked for: {', '.join(dict.fromkeys(w for o in unchecked for w in o.unconfirmed))})") if unchecked else "no quotable option meets every wish"
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

    if kind == "hotels" and rec is not None and not _solid(rec):      # a thin cheapest pick must not be the whole recommendation
        solid = [o for o in fitting if _solid(o)]
        if solid:
            alt = min(solid, key=lambda o: o.price_total)
            rec, rec_reason = alt, (f"the Best fit ({rec.name}: score {rec.details.get('score') or 'not shown'}, {rec.details.get('reviews') if rec.details.get('reviews') is not None else 'not shown'} reviews) "
                                    "is thin, so the recommendation is the cheapest option that meets every wish with score 7.5+ from 50+ reviews")

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
    if kind == "flights":      # what the row itself says it does not show, whether or not the operator asked for it (28 Oct 2026: a 'refundable only' answer's Best fit showed 'not shown on the list')
        done: set[int] = set()
        for title, o in (("Best fit", best), ("Recommended", rec)):
            if o is None or id(o) in done:
                continue
            done.add(id(o))
            gaps = [w for key, w in (("refund_change", "refund terms"), ("checked_bag", "checked-bag terms")) if str(o.details.get(key) or "").lower().startswith("not shown")]
            if gaps:
                notes.append(f"Caution on the {title} ({o.source}: {o.name}): its {' and '.join(gaps)} are not shown on the list: confirm them on the airline's page before quoting.")
    if kind == "cars":      # a pick that is not at the airport terminal (28 Oct 2026: the Best fit was an Ofran station outside the airport and only a table cell said so)
        said: set[int] = set()
        for title, o in (("Best fit", best), ("Recommended", rec)):
            where = str((o.details or {}).get("pickup_place") or "") if o is not None else ""
            if o is not None and id(o) not in said and re.search(r"not at the terminal|outside the airport", where, re.I):
                said.add(id(o))
                notes.append(f"Caution on the {title} ({o.source}: {o.name}): its pick-up is not at the airport terminal ({where}): the operator should know before quoting.")
    rows_out = [("Cheapest", label(cheapest), cheap_reason),
                ("Best fit", label(best), best_reason),
                ("Most flexible", label(flexible), "the cheapest option the source says is refundable or free to cancel" if flexible else flexible_reason(priced)),
                ("Recommended", label(rec), rec_reason)]
    return rows_out, notes


def group_key(group: str) -> tuple[str, ...]:
    """'Lisbon Airport -> Praça do Comércio 6 Mar 2027 10:00' and 'Lisbon Airport to Praça do Comércio, 06 Mar 2027 10:00' name one leg: no accents or punctuation, '->' and 'to' dropped,
    '06' is '6'. The order of the words stays (A to B is not B to A)."""
    plain = unicodedata.normalize("NFKD", str(group).lower()).encode("ascii", "ignore").decode()
    words = [w.lstrip("0") or "0" if w.isdigit() else w for w in re.findall(r"[a-z0-9:]+", plain)]
    return tuple(w for w in words if w != "to")


def unify_groups(offers: list[Offer]) -> None:
    """Rows of one leg written with different spellings of its name become one group, so there is one table and one set of Picks (28 Oct 2026: Kiwitaxi's rows typed by the chat and iWay's rows
    from the recipe came as two tables, 'Best fit' in one and 'not determined' in the other). The first spelling seen is kept."""
    first: dict[tuple[str, ...], str] = {}
    for o in offers:
        o.group = first.setdefault(group_key(o.group), o.group)


def nothing_found_answer(kind: str, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], pickup_time: str | None, notes: str) -> dict[str, Any]:
    """No source returned an option and every one has an allowed reason: the answer says exactly that (no '0 of 0 read'), with the same lines and an empty pick table."""
    why = "no source returned an option for this search"
    lines = ["Sources checked: none returned an option" + (f" (searched, no options: {'; '.join(s.name for s in sources_read)})" if sources_read else "")
             + " | Not checked: " + ("; ".join(f"{n.name} ({n.reason})" for n in not_checked) or "none")]
    if filters_used:
        lines.append("Filters used: " + "; ".join(filters_used))
    if pickup_time:
        lines.append(f"Pick-up time used on every source: {pickup_time}")
    lines += ["", "No options to show: " + why + ".", "", "| Pick | Option | Reason |", "|---|---|---|"] + [f"| {p} | not determined | not determined: {why} |" for p in ("Cheapest", "Best fit", "Most flexible", "Recommended")]
    if kind in NEEDS_SUPPLIER_CHECK:
        lines += ["", "In MYT supplier? not checked: there was no option to check."]
    lines += ["", "Sources: " + (" | ".join(f"{s.name}: {s.link}" for s in sources_read) if sources_read else "none read")]
    if notes.strip():
        lines += ["", "Notes (assistant's judgement, not from a source): " + notes.strip()]
    return {"ok": True, "answer": "\n".join(lines), "next": "Call check_answer with this `answer` (and this kind) BEFORE you send it, then show `answer` to the operator exactly as written. Do not retype, reword or reorder it. You may add questions after it."}


def compose(kind: str, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
            myt_supplier: dict[str, str], pickup_time: str | None, sorted_by_price: bool, notes: str, max_rows: int | None = None, checked_at: str | None = None) -> dict[str, Any]:
    unify_groups(offers)
    # every source was excused or read nothing (28 Oct 2026: CP had no trains on sale, RateHawk has no Lisbon station; a chat listed CP as '0 of 0 read' and the answer was refused): the server writes "nothing found" itself
    empty = not offers and bool(sources_read or not_checked) and all(not s.read for s in sources_read)
    problems = validate(kind, filters_used, sources_read, not_checked, offers, myt_supplier, pickup_time, nothing_found=empty)
    if problems:
        return {"ok": False, "problems": problems, "next": "Fix every problem (read the source, or write an allowed reason / the missing field) and call compose_answer again. Do not write the answer yourself."}
    if empty:
        return nothing_found_answer(kind, filters_used, sources_read, not_checked, pickup_time, notes)
    required = REQUIRED_DETAILS[kind]
    if kind == "hotels":      # the agency usually compares RateHawk and Arbitrip: when neither read nor excused (the operator asked for one source, e.g. a hotel's own website) the answer SAYS so; it is not a refusal
        covered = {s.name.lower() for s in sources_read} | {n.name.lower() for n in not_checked}
        not_checked = list(not_checked) + [NotChecked(name=src, reason="not read in this answer: not compared") for src in ("RateHawk", "Arbitrip") if not any(c.startswith(src.lower()) for c in covered)]
    complete_sources = {s.name.lower() for s in sources_read if s.of and s.read == s.of}
    lines: list[str] = []
    lines.append("Sources checked: " + "; ".join(f"{s.name} ({s.read} of {s.of} read)" for s in sources_read)
                 + " | Not checked: " + ("; ".join(f"{n.name} ({n.reason})" for n in not_checked) or "none"))
    if filters_used:
        lines.append("Filters used: " + "; ".join(filters_used))
    if checked_at:
        lines.append(f"Checked: {checked_at}")
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
        pk, pnotes = picks(kind, rows, sorted_by_price, all(o.source.lower() in complete_sources for o in rows))
        pnotes += cheaper_unconnected_notes(kind, rows)
        pnotes += price_gap_notes(kind, rows)
        kept = [o for o in rows if o.fits is not False]
        pool = kept if kept else rows        # an option that clearly misses a wish of the operator is not listed (rows without wishes, such as comparison rows, stay)
        ordered = sorted(pool, key=lambda r: (r.price_total is None, r.price_total or 0))
        shown = ordered
        if max_rows and len(ordered) > max_rows:       # the picks always use EVERY row read; the table shows the cheapest, the picks and (hotels) the best rated
            keep = {id(o) for o in ordered[:max_rows]}
            keep |= {id(o) for _, text, _ in pk for o in rows if text.startswith(f"{o.source}: {o.name} - ")}
            for src in dict.fromkeys(o.source for o in ordered):                # no source disappears from the table: its cheapest rows stay
                keep |= {id(o) for o in [x for x in ordered if x.source == src][:PER_SOURCE_MIN_ROWS]}
            if kind == "hotels":
                keep |= {id(o) for o in sorted((o for o in rows if _solid(o)), key=lambda r: -float(str(r.details.get("score"))))[:5]}
            shown = [o for o in ordered if id(o) in keep]
            show_note = f"Showing {len(shown)} of the {len(ordered)} options read: the cheapest, the picks and the best rated. The picks are chosen from all {len(ordered)}."
        else:
            show_note = None
        if len(pool) < len(rows):
            dropped = f"{len(rows) - len(pool)} of the {len(rows)} options read do not meet every wish of the operator and are not in the table."
            show_note = f"{show_note} {dropped}" if show_note else dropped
        for o in shown:
            cells = []
            for k in keys:
                v = o.details.get(k)
                if (v is None or v == "") and k not in NOT_A_GAP and (k in required or k in o.details):      # a column this kind of row never has (the exact-price columns next to list rows) is not a gap
                    gaps[k] = gaps.get(k, 0) + 1
                cells.append(_cell(v, DETAIL_CAP))
            tag = " (connecting)" if o.connecting else ""
            lines.append(f"| {o.source} | {_cell(o.name)}{tag} | " + " | ".join(cells)
                         + f" | {_money(o.price_total, o.currency)} | {_cell(o.price_basis)} | {_quotable_cell(o)} | {o.link or 'see Sources'} |")
        if show_note:
            lines += ["", show_note]
        lines += ["", "| Pick | Option | Reason |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in pk] + [f"- {n}" for n in pnotes]
        for label, text, _ in pk:
            if label in ("Cheapest", "Best fit", "Recommended") and text != "not determined":
                m = next((o for o in rows if text.startswith(f"{o.source}: {o.name}")), None)
                if m and m.supplier:
                    supplier_lines[m.supplier] = myt_supplier.get(m.supplier) or directory_status(m.supplier)
    if kind in NEEDS_SUPPLIER_CHECK:
        lines += ["", "In MYT supplier? " + ("; ".join(f"{s}: {v}" for s, v in supplier_lines.items()) or "no supplier given for the picks: not checked")]
    if gaps:
        lines += ["", "Not shown by the sources: " + ", ".join(f"{k.replace('_', ' ')} (in {n} row(s))" for k, n in gaps.items()) + "."]
    lines += ["", "Sources: " + " | ".join(f"{s.name}: {s.link}" for s in sources_read)]
    if notes.strip():
        lines += ["", "Notes (assistant's judgement, not from a source): " + notes.strip()]
    return {"ok": True, "answer": "\n".join(lines), "next": "Call check_answer with this `answer` (and this kind) BEFORE you send it, then show `answer` to the operator exactly as written. Do not retype, reword or reorder a row, and do not change a number, a pick or a reason. You may add questions after it."}


def mark_unconfirmed(o: "Offer", what: str) -> None:
    """A wish this row cannot be checked against: it stays in the table (marked), is never a pick, and is never counted as 'does not meet' (that is for a row that clearly misses a wish)."""
    if what not in o.unconfirmed:
        o.unconfirmed.append(what)
    if o.fits is not False:
        o.fits = None


def tracking_unconfirmed(offers: list["Offer"]) -> str | None:
    """Flight tracking was asked: a transfer row that does not say 'yes' is unconfirmed ('no' is a clear miss)."""
    unsure = [o for o in offers if o.quotable and o.fits is not False and str((o.details or {}).get("flight_tracking") or "").lower() != "yes"]
    for o in unsure:
        if str((o.details or {}).get("flight_tracking") or "").lower() == "no":
            o.fits = False
        else:
            mark_unconfirmed(o, "flight tracking")
    unsure = [o for o in unsure if o.fits is not False]
    if not unsure:
        return None
    sources = sorted({o.source for o in unsure})
    return f"Flight tracking was asked: the rows of {', '.join(sources)} do not say whether it is included, so they are in the table marked 'not confirmed' and are not picks."


def bag_unconfirmed(offers: list[Offer]) -> str | None:
    """The operator asked for a checked bag: a quotable row whose list does not say whether one is included does not meet that wish (never assumed). Marks them and returns the note
    (24 Oct 2026: El Al's list shows no bag and was still picked as 'meets every wish')."""
    unsure = [o for o in offers if o.quotable and o.fits is not False and str((o.details or {}).get("checked_bag") or "").lower().startswith("not shown")]
    for o in unsure:
        mark_unconfirmed(o, "checked bag")
    if not unsure:
        return None
    best = min((o for o in unsure if o.price_total is not None), key=lambda o: o.price_total, default=None)
    quotable = [o for o in offers if o.quotable]
    parts = []
    for source in sorted({o.source for o in unsure}):         # a source may show the bag on some fares and not on others: say how many rows, not the whole source (26 Oct 2026: RateHawk Air was named as a whole)
        n, total = sum(1 for o in unsure if o.source == source), sum(1 for o in quotable if o.source == source)
        parts.append(f"{source} ({'all its rows' if n == total else f'{n} of its {total} rows'})")
    return (f"A checked bag was asked, but some rows do not show whether one is included: {', '.join(parts)}; those rows are not picks"
            + (f" (the cheapest of them, {best.source} {best.price_total:,.2f} {best.currency}, needs its fare rules checked on the airline's page before quoting)." if best else "."))


def refund_unconfirmed(offers: list[Offer]) -> str | None:
    """The operator asked for refundable fares: a quotable flight row whose list does not show its refund terms does not meet that wish (never assumed), like the checked bag above
    (26 Oct 2026: a RateHawk fare with 'not shown on the list (open More rates)' became the Best fit of a 'refundable only' search)."""
    unsure = [o for o in offers if o.quotable and o.fits is not False and str((o.details or {}).get("refund_change") or "").lower().startswith("not shown")]
    for o in unsure:
        mark_unconfirmed(o, "refund terms")
    if not unsure:
        return None
    best = min((o for o in unsure if o.price_total is not None), key=lambda o: o.price_total, default=None)
    quotable = [o for o in offers if o.quotable]
    parts = []
    for source in sorted({o.source for o in unsure}):
        n, total = sum(1 for o in unsure if o.source == source), sum(1 for o in quotable if o.source == source)
        parts.append(f"{source} ({'all its rows' if n == total else f'{n} of its {total} rows'})")
    return (f"Refundable fares were asked, but some rows do not show their refund terms: {', '.join(parts)}; those rows are not picks"
            + (f" (the cheapest of them, {best.source} {best.price_total:,.2f} {best.currency}, needs its refund terms checked on the airline's page before quoting)." if best else "."))


def apply_wishes(offers: list[Offer], wishes: dict | None) -> None:
    """A row typed in by hand has no `fits` yet. With the operator's wishes, a wish the row cannot show it meets counts as NOT met (never assumed)."""
    if not wishes:
        return
    for o in offers:
        if o.fits is not None or not o.quotable:      # a comparison row (its cancellation is not in the list) is never judged from what the list lacks
            continue
        d = o.details or {}
        ok = True
        if wishes.get("breakfast"):
            meal = str(d.get("meal") or "")
            ok &= bool(re.search(r"breakfast|half board|full board|all inclusive", meal, re.I)) and "no meals" not in meal.lower()
        if wishes.get("free_cancellation"):
            ok &= bool(o.flexible) or str(d.get("cancellation") or "").lower().startswith("free cancellation")
        if wishes.get("stars_min"):
            try:
                ok &= float(d.get("stars")) >= float(wishes["stars_min"])
            except (TypeError, ValueError):
                ok = False
        ok &= meets_limits(o.price_total, d.get("distance_from_centre"), wishes)
        o.fits = ok

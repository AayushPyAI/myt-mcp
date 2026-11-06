"""Viator: the EXACT price of ONE activity for a date and a group (a site module, see myt_mcp/sites/__init__.py), read from Viator's own availability service.

Site rules (read live 5 Nov 2026): an activity page (www.viator.com/tours/<place>/<name>/d<id>-<code>) gets its options and prices from ONE request, POST /orion/ajax/product-availability with
{productCode, searchDate, ageBands: {ADULT: "2", CHILD: "1"}, source: "commerce_module"} and the page's own security token (the page's data names the header and the token; without it the answer is a 403). The answer lists every
option (`tourGrades`) with the price of the WHOLE group (discounted and list), the price per age band, its start times, the spots left, the date until which "reserve now, pay later" is possible and whether it can be booked,
plus the cancellation terms of the date (`cancellationPolicyDetails`) and validation errors (OVER_MAX_TRAVELERS, OUT_OF_AGE_RANGE); a date with nothing bookable has an empty list. The page's age groups differ per activity
(Adult 18-99, Youth 13-17, Child 4-12 on one; Child 0-9 on another): each traveller goes in the band that holds their age. GET /orion/ajax/react/product-price-calendar/<code> lists the bookable dates with their from-price. The
description (duration, languages, what is included, the meeting point, additional information, the cancellation policy) is in the page's embedded data. The prices follow the visitor's currency, which must be EUR (the rows
carry their own currency). Nothing is booked or held; the price shown in the page's own booking box for the same date and group was compared with this answer (5 Nov 2026: equal for 2 adults and 2 adults + 1 child).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, group_title, server_first, with_emit

NAME = "viator_activity"
SOURCE = "Viator"
GROUP = "Activities"
RESULT_MARKS = {"url_path", "activity"}      # keys only this recipe's answers have: a display name that fits a list recipe and a page recipe is told apart by them (resolve_site_names)
HERE = Path(__file__).parent
URL = re.compile(r"^https://www\.viator\.com/tours/[^?#\s]+/d\d+-([A-Za-z0-9_.]+)/?(?:[?#].*)?$")
EUR = {"€", "EUR"}
BAND_NAMES = {"ADULT": "Adult", "YOUTH": "Youth", "CHILD": "Child", "INFANT": "Infant", "SENIOR": "Senior", "TRAVELER": "Traveller", "STUDENT": "Student"}
ERRORS = {"OVER_MAX_TRAVELERS": "the group is larger than Viator allows for this activity in one booking", "OUT_OF_AGE_RANGE": "a traveller's age is outside the activity's age groups",
          "UNSUPPORTED_AGE_BAND": "the activity has no age group of that kind"}


def clean_url(url: str) -> str:
    return url.split("?")[0].split("#")[0]


def viator_activity_recipe(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None) -> dict[str, Any]:
    m = URL.match(url or "")
    if not m:
        raise ValueError("url must be a Viator activity link (https://www.viator.com/tours/<place>/<name>/d123-CODE): take it from the search, never guess it")
    ages = list(children_ages or [])
    if not 0 <= adults <= 15 or not 1 <= adults + len(ages) <= 15 or any(not 0 <= a <= 99 for a in ages):
        raise ValueError("travellers must be 1-15 in total, adults 0-15, ages 0-99 (the ages of everyone who is not a plain adult: children, and seniors for an age group of their own)")
    total = adults + len(ages)
    link = clean_url(url)
    path = "/" + link.split("viator.com/", 1)[1]
    expect = {"day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "total": total, "path": path, "code": m.group(1), "group": group_title(activity, day)}
    steps = [f"Open {link} in the operator's Chrome (a NEW tab). The prices must be in EUR: if the page shows another currency, open the globe menu (top right), choose EUR and reload. If a cookie banner is in the way, decline non-essential cookies.",
             "Run the script with the javascript tool: it asks Viator's own availability service for the date and the group by itself, so the calendar and the traveller box are not touched. Do NOT press Book Now or Reserve Now & Pay Later.",
             "The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row."]
    request = {"code": m.group(1), "day": day.isoformat(), "adults": adults, "ages": ages}
    return {"url": link, "steps": steps, "script": with_emit((HERE / "viator_activity.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request)), "expect": expect}


def _when(text: str | None) -> date | None:
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _page_link(exp: dict[str, Any]) -> str | None:
    """Each priced activity names its own page (28 Oct 2026: three rows, one link in Sources)."""
    path = str((exp or {}).get("path") or "")
    return f"https://www.viator.com{path}" if path.startswith("/tours/") else None


def _band(row: dict[str, Any]) -> str:
    name = BAND_NAMES.get(str(row.get("band") or "").upper()) or str(row.get("band") or "traveller").title()
    if (row.get("n") or 0) != 1:
        name = "Children" if name == "Child" else name + "s"
    unit = row.get("unit")
    return f"{row.get('n')} {name} x {unit:.2f} EUR" if unit is not None else f"{row.get('n')} {name}"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Viator result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Viator script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    offers: list[Offer] = []
    rows = data.get("rows", [])
    title = data.get("activity") or "activity"
    if exp and data.get("url_path") and exp.get("path") and data["url_path"].rstrip("/") != exp["path"].rstrip("/"):
        problems.append(f"the page is {data['url_path']}, not the activity asked ({exp['path']}): open the url again")
    if exp and data.get("day") and data["day"] != exp.get("day"):
        problems.append(f"the answer is for {data['day']}, not {exp['day']}: run the script again")
    if exp and data.get("travellers_sent") is not None and data["travellers_sent"] != exp["total"]:
        problems.append(f"the request had {data['travellers_sent']} traveller(s), not {exp['total']}: run the script again")
    for code in data.get("errors") or []:
        problems.append(f"Viator refused the request: {ERRORS.get(code, code)}" + (f" (at most {data['max_travellers']} travellers in one booking)" if code == "OVER_MAX_TRAVELERS" and data.get("max_travellers") else "")
                        + (f" (its age groups: {data['age_groups']})" if code in ("OUT_OF_AGE_RANGE", "UNSUPPORTED_AGE_BAND") and data.get("age_groups") else ""))
    policy_type = str(data.get("policy_type") or "").upper()
    policy_text = data.get("cancel_policy") or ""
    non_refundable = bool(re.search(r"NON|NO_REFUND|NOT_REFUND", policy_type) or re.search(r"non-?refundable|not refundable", policy_text, re.I))
    free = (policy_type == "REFUNDABLE" and not data.get("refund_deadline_past")) or bool(re.search(r"cancel up to \d+ (?:hours?|days?) in advance.{0,60}full refund", policy_text, re.I))
    free = free and not non_refundable and not data.get("refund_deadline_past")      # the date's own deadline beats the activity's general text
    unavailable = 0
    for r in rows:
        if not r.get("available") or r.get("total") is None:
            unavailable += 1
            continue
        if (r.get("cur") or "EUR") not in EUR:
            problems.append(f"the page prices '{r.get('option')}' in '{r.get('cur')}', not EUR: open the globe menu, choose EUR, open the url again and run the script again")
            continue
        if exp and r.get("date") and _when(r["date"]) != _when(exp.get("day")):
            problems.append(f"the option '{r.get('option')}' is for {r['date']}, not {exp['day']}: run the script again")
        n = sum(int(b.get("n") or 0) for b in r.get("breakdown") or []) or data.get("travellers_sent")
        if exp and n != exp["total"]:
            problems.append(f"the price of '{r.get('option')}' is for {n} traveller(s), not {exp['total']}: run the script again")
        parts = [_band(b) for b in r.get("breakdown") or []]
        unit = bool(data.get("unit_pricing"))      # priced per group: Viator's breakdown then holds the whole price on one line and 0 on the others (read live 5 Nov 2026: '2 Adult at 0 + 1 Adult at 7500' for one flat 7,500)
        if unit and data.get("max_per_unit") and n > data["max_per_unit"]:
            problems.append(f"this activity is priced per group of at most {data['max_per_unit']} travellers: {n} travellers need more than one group")
        times = [t for t in (r.get("times") or []) if t.get("t")]
        open_times = [t for t in times if t.get("ok") is not False]
        prices = {t.get("price") for t in open_times if t.get("price") is not None}
        start = f"{len(open_times)} start time(s): " + ", ".join(t["t"] for t in open_times[:8]) + (f", ... last {open_times[-1]['t']}" if len(open_times) > 8 else "") if open_times else "not listed for this option"
        if len(prices) > 1:
            start += "; the price differs by start time: " + ", ".join(f"{t['t']} {t['price']:g}" for t in open_times[:6] if t.get("price") is not None) + " EUR"
        if data.get("refund_deadline_past"):
            cancel = "Free cancellation is no longer possible for this date (the refund deadline has passed)" + (f"; Viator's general policy: {policy_text}" if policy_text else "")
        elif free:
            cancel = "Free cancellation" + (f" until {data['refund_until']} (Viator's policy for this date" + (f": {policy_text}" if policy_text else "") + "; its page shows the cut-off as 'before the start time chosen on that day'" + (f", so for {open_times[0]['t']} before {open_times[0]['t']} on {data['refund_until']}" if open_times else "") + ")" if data.get("refund_until") else (f" per the page's policy: {policy_text}" if policy_text else ""))
        elif non_refundable:
            cancel = "Non-refundable (Viator's policy for this date)" + (f": {policy_text}" if re.search(r"non-?refundable|not refundable", policy_text, re.I) else "")
        else:
            cancel = policy_text or "not shown"
        pay = (f"Reserve now, pay later possible until {r['pay_by'][:10]}" if r.get("pay_by") else "Reserve now, pay later possible") if r.get("reserve") else "Reserve now, pay later is not offered for this option"
        option = r.get("option") or ""
        name = f"{title} - {option}" if option and option.strip().lower() != title.strip().lower() else title
        extras = (r["extra_charges"] - r["total"]) if r.get("extra_charges") and r["extra_charges"] > r["total"] else None      # `totalRetailPricePlusExtraCharges` is 0 when there are none and the total plus them when there are (7,533 for 7,500 read live 5 Nov 2026: 3 travellers x 11)
        who = f"{n} travellers: a flat price for the whole group of up to {data['max_per_unit'] or n}, not per person" if unit else f"{n} travellers; {'; '.join(parts) or 'breakdown not shown'}"
        basis = f"whole group ({who})" + (f"; discounted from {r['list_total']:g} EUR" if r.get("discounted") and r.get("list_total") else "") \
            + (f"; Viator lists {extras:g} EUR of extra charges on top (its own total with them is {r['extra_charges']:g} EUR), which its booking box does not add: confirm before quoting" if extras else "; Viator lists no extra charges")
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=f"{name} ({(data.get('duration') or 'duration not shown')})", price_total=float(r["total"]), currency="EUR", price_basis=basis,
            flexible=True if free else (False if non_refundable else None), supplier="Viator", link=_page_link(exp),
            details={"duration": data.get("duration") or "not shown", "start_times": start, "language": (f"offered in: {data['offered_in']}" if data.get("offered_in") else "not shown") + (f"; this option: {', '.join(r['langs'])}" + (f" ({', '.join(r['guide'])})" if r.get("guide") else "") if r.get("langs") else ""),
                     "meeting_point": data.get("meeting_text") or "not shown (see the activity page)", "includes": data.get("included") or "not shown", "excludes": data.get("excluded") or None, "additional_info": data.get("additional") or "not shown",
                     "cancellation": cancel, "private_or_group": "private" if re.search(r"private", f"{name} {r.get('about') or ''}", re.I) else "not shown", "pay": pay, "extra_charges": (f"{extras:g} EUR on top of the price" + (f" ({data['extra_per_traveller']:g} EUR per traveller)" if data.get("extra_per_traveller") else "")) if extras else "none listed",
                     "ticket": "mobile ticket" if data.get("mobile_ticket") else "not shown", "seats_left": f"{r['spots']}" if r.get("spots") is not None else "not shown", "option_info": r.get("about") or None}))
    notes = ["Viator's exact price for this date and group, from Viator's own availability service (the same figures the activity page's booking box shows; child discounts included); the activity's own page is the quoted source. The 'from' price in the search is only the lowest starting price."]
    if len(offers) > 1:
        notes.append("This activity has several options: each has its own price, start times and terms.")
    if unavailable:
        notes.append(f"{unavailable} option(s) of this activity cannot be booked on {exp.get('day') or 'this date'} and are not listed.")
    if not rows and not data.get("errors"):
        later = data.get("next_dates") or []
        problems.append(f"Viator has no option to book on {exp.get('day') or data.get('day')}" + (f"; the next bookable dates (from-price): {', '.join(later)}" if later else "") + ("; Viator's calendar does not list this date" if data.get("day_bookable") is False else ""))
    return SiteRows(offers=offers, read=len(offers), total=len(rows), problems=problems, sorted_by_price=False, read_rows=True, extra_notes=notes)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="viator_activity_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def viator_activity_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE VIATOR ACTIVITY on a date for a group: use the activity link from viator_find_recipe (never guess a link). Give `adults` and `children_ages` (the ages of everyone who is not a plain adult, children and seniors; [] if none) as the operator said
        (ask if not said); `activity` = the itinerary activity this answers (it names the row group); `free_cancellation` only if the operator asked for it. THE SERVER READS IT ITSELF in its own browser, from Viator's own
        availability service (every option with the price of the whole group and per age band, start times, spots left, cancellation and pay-later terms), and returns a short receipt with an `ingest` id: call
        compose_answer with `runs`=[that id] (ok=false: put Viator in not_checked with the reason it gives). Without a server browser it returns the url, STEPS and a read-only SCRIPT: open the url in a new tab (EUR), run
        it (no calendar or traveller box is touched): then call compose_answer with `runs`=[its `ingest` id] and the returned `wishes`; never type or pass a row. A human check is never worked
        around. One call per activity."""
        out = viator_activity_recipe(url, day, adults, children_ages, activity)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "Every option of the activity (default: no option filter)"]
        return await server_first(NAME, "VIATOR_ACTIVITY_READ_IN_SERVER", "https://www.viator.com", out)

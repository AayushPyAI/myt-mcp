"""check_answer: a draft price answer is checked against the playbook's must-haves BEFORE it is sent.

The playbook rules are instructions to a language model, which sometimes skips them (a missing "Sources checked" line, a
home-page link instead of the search link, "skipped for time", an invented fee). This tool makes those omissions visible:
it reads the draft and lists what is missing or doubtful. It reads nothing from the sites and changes nothing.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp import answer_watch
from myt_mcp.composed import amount_problems, currency_problems, row_problems, source_warnings
from myt_mcp.errors import tool_errors

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges", "general"]
COMPARING = {"flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"}
NEEDS_FILTERS = {"flights", "hotels", "cars", "transfers", "trains", "activities"}
NEEDS_SUPPLIER_CHECK = {"flights", "hotels", "cars", "transfers", "activities"}
PICKS = ("Cheapest", "Best fit", "Most flexible", "Recommended")
log = logging.getLogger("myt_mcp")
URL = re.compile(r"https?://[^\s)|,;<>\"']+", re.I)
# phrase -> why it is not allowed
BANNED = {
    "for time": "'skipped for time' is not a reason for 'Not checked'; read the source or give an allowed reason (no browser tool, login or captcha, route not served)",
    "out of scope": "'out of scope' is not a reason for 'Not checked'",
    "this pass": "'not this pass' is not a reason for 'Not checked'",
    "to keep it short": "'to keep it short' is not a reason for 'Not checked'",
    "say the word": "never ask permission to read a listed source: read it",
    "not asked": "'not asked' / 'you didn't ask' is not a reason for 'Not checked': read the source",
    "didn't ask": "'you didn't ask' is not a reason for 'Not checked': read the source",
    "did not ask": "'you did not ask' is not a reason for 'Not checked': read the source",
    "on request": "never offer to read a listed source 'on request': read it now",
    "happy to run": "never offer to read a listed source later: read it now",
    "no myt trip attached": "'no MYT trip attached' is not a reason: check the supplier in test trip 906's quotation (type its name in Search supplier, read only)",
    "give me the trip number": "do not ask for a trip number to check suppliers: use test trip 906's quotation (type the name in Search supplier, read only)",
    "would need the quotation": "'In MYT supplier?' is checked by you: open the quotation (or test trip 906) and type the supplier name in Search supplier",
    "fully confirms": "do not claim a missing result 'confirms' something; write what you saw and 'my judgement'",
}


# the draft admits it did not ask the operator first, or that the Chrome sources were skipped because the tool "is not available"
SKIPPED_ASKING = re.compile(r"\b(?:i\s+)?(?:haven'?t|have\s+not|hasn'?t|did\s+not|didn'?t)\s+(?:yet\s+)?(?:asked|checked\s+with\s+you)\b|\bto\s+narrow\s+this\s+down,?\s+tell\s+me\b")
NO_CHROME = re.compile(r"claude in chrome[^.\n]{0,60}(?:isn'?t|is\s+not|not|un)\s*available|(?:can'?t|cannot|unable\s+to)\s+(?:use|open|reach)\s+claude in chrome")


def check_answer_text(text: str, kind: str = "general") -> dict[str, Any]:
    low = text.lower().replace("\u2019", "'")
    missing: list[str] = []
    warnings: list[str] = []

    if "sources checked:" not in low or "not checked:" not in low:
        missing.append('the first line "Sources checked: ... | Not checked: ... (why)"')
    urls = URL.findall(text)
    if not urls:
        missing.append("a link for every source you read (the tool's source/url, or the address of the Chrome page)")
    elif all(re.sub(r"^https?://[^/]+/?$", "", u) == "" for u in urls):
        missing.append("exact links: only home pages were given (flytap.com is not a link; give the search or results page)")
    if kind in COMPARING:
        absent = [p for p in PICKS if p.lower() not in low]
        if absent:
            missing.append("Picks rows: " + ", ".join(absent) + ' (a row you cannot fill says "not determined: why")')
    if kind in NEEDS_FILTERS:
        line = next((l for l in text.splitlines() if "filters used" in l.lower()), None)
        if line is None:
            missing.append('"Filters used: ..." with the source of each filter (operator or trip)')
        elif not any(w in line.lower() for w in ("operator", "trip", "your answer", "you said", "default")):
            warnings.append("Filters used: say where each filter comes from (operator, the trip, or the operator's answer to your question)")
    if kind in COMPARING and not re.search(r"\b\d+\s+of\s+\d+\b", low):
        missing.append('how many results you read per source: "N of M"')
    if kind in NEEDS_SUPPLIER_CHECK and "myt supplier" not in low:
        missing.append('"In MYT supplier?" for the Cheapest, Best fit and Recommended supplier (yes / no / not checked: why)')
    if kind in {"cars", "transfers"} and not re.search(r"pick-?\s?up", low):
        missing.append("the pick-up time used (the same on every source)")

    if kind in NEEDS_FILTERS and SKIPPED_ASKING.search(low):
        missing.append("the draft says the operator was not asked (or asks them afterwards): ask first, before any source is read "
                       "(direct/stops, bags, stars, budget ... as the recipe tool lists), then search with those answers")
    if kind in COMPARING and NO_CHROME.search(low):
        missing.append("do not give a partial comparison because Claude in Chrome 'is not available': call the browser tool once to check; "
                       "if it really is not connected, tell the operator to switch Claude in Chrome on in this chat and stop (do not send a final answer)")

    for phrase, why in BANNED.items():
        if phrase in low:
            missing.append(f'"{phrase}": {why}')
    if "all adults" in low and not any(w in low for w in ("you said", "your answer", "your instruction", "you told", "operator said", "as you chose")):
        missing.append('"all adults" appears without the operator saying so: ask for adults and children\'s ages')
    if "public price" in low and re.search(r"\bnet\b", low):
        warnings.append('the text says "public price" and also "net": the Picks basis must not say net or agent price for a public price')
    for word in ("typically", "usually", "normally", "generally", "as a rule"):
        if re.search(rf"\b{word}\b", low):
            warnings.append(f'"{word}": a statement about what an airline, hotel or site "{word}" does is general knowledge, not a source; remove it or write "not shown"')
            break
    if kind == "flights" and "tap" in low and re.search(r"change (fee|€|eur)|€\s?\d+ change", low):
        warnings.append("a TAP change fee: the TAP tool does not return one (only bag included and refundable). Remove it or write 'not shown'")
    if kind == "hotels":
        if "cheapest" in low and not re.search(r"sort(ed)? by price|price \(low|low to high|cheapest first|lowest price first|price ascending", low):
            missing.append('a hotel is called "Cheapest" but the list sorted by PRICE was not read (a rating-sorted list hides the cheaper hotels): read both sorts, or call it "cheapest of the N read, sorted by rating"')
        if "review" not in low:
            warnings.append("hotels: show the number of reviews next to each score (a 10.0 from three reviews is not a 10.0 from a thousand)")
        if "star" not in low and "★" not in text:
            warnings.append("hotels: show the stars of each hotel (or 'stars not shown')")
    if kind == "hotels" and re.search(r"(review|score|rating)[^.\n]{0,12}8\s?\+|8\s?\+[^.\n]{0,12}(review|score|rating)", low):
        warnings.append('"review 8+" is not a default filter: keep it only if the operator named it')

    ok = not missing
    return {
        "ok": ok,
        "missing": missing,
        "warnings": warnings,
        "next": ("Nothing is missing. Fix the warnings if they apply, then send." if ok
                 else "Fix EVERY item under `missing` (read the source, or write an allowed reason), then call check_answer again with the fixed draft. "
                      "Send the answer only when `ok` is true."),
    }


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def check_answer(draft: str, kind: Kind = "general") -> dict[str, Any]:
        """CALL THIS WITH YOUR DRAFT before you send any price or comparison answer (flights, hotels, cars, transfers, trains,
        activities, lounges). It lists what the playbook requires and your draft lacks: the "Sources checked / Not checked"
        line, a link for every source, the four Picks rows, "Filters used" with their sources, "N of M", forbidden excuses
        ("for time", "out of scope"), "all adults" said without the operator, and numbers a tool never returns (TAP change fees).
        It reads no site and changes nothing. Fix what it lists, then send. `kind` is the kind of answer ("general" for the rest)."""
        answer_watch.checked()
        out = check_answer_text(draft, kind)
        typed = row_problems(draft, kind)
        amounts, amount_warnings = amount_problems(draft)
        amount_warnings += source_warnings(draft)
        typed = [*typed, *amounts, *currency_problems(draft)]
        if amount_warnings:
            out = {**out, "warnings": [*out.get("warnings", []), *amount_warnings]}
        if typed:
            out = {**out, "ok": False, "missing": [*out.get("missing", []), *typed]}
        log.info("CHECK check_answer kind=%s ok=%s missing=%s", kind, out.get("ok"), "; ".join(out.get("missing", []))[:600])      # rule messages only, never the draft
        return out

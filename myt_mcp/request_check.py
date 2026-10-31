"""What the operator really said, against what the assistant passed on (30 Oct 2026).

The filter lines of an answer say "(operator)" for every value a recipe was given, but the recipe is called by the assistant, not by the operator: in the client-style run of 29 Oct the answer said
"within 1.5 km (operator)", "manual gearbox (operator)", "zero excess (operator)" and "flight tracking (operator)" for values nobody had asked for, and a made-up distance limit hid real rows.
The server never saw the operator's message, so `compose_answer` now takes it (`request`, word for word) and checks here:

- a filter line labelled "(operator)" whose topic or number is not in the request is relabelled "(assumed by the assistant, not in the operator's request)";
- a limit or a yes/no wish passed in `wishes` that the request does not support is NOT applied (it would hide real rows), and a filter line says so;
- a line this module cannot judge (no topic it knows, no number) is left as it is: it never downgrades what it does not understand.
Without a request nothing is changed and the answer says the labels were not checked. Pure text logic: it reads no site and changes no row.
"""

from __future__ import annotations

import re
from typing import Any

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple": 2, "pair": 2, "twenty": 20, "thirty": 30, "fifty": 50}
ASSUMED = "assumed by the assistant, not in the operator's request"

# topic -> words that show the operator talked about it
EVIDENCE = {
    "breakfast": r"breakfast|\bbb\b|b&b|half board|full board|meals?\b",
    "cancellation": r"cancel|refund|flexib",
    "stars": r"\bstars?\b|\d\s*\*|★",
    "gearbox": r"automatic|manual|gear|stick|transmission",
    "excess": r"excess|insurance|cover|cdw|deductible|zero",
    "tracking": r"track|flight number|monitor|delay|flight info|flight status",
    "direct": r"direct|non-?stop|no (?:stops?|connections?|layovers?)|without (?:stops?|connections?)",
    "bag": r"\bbags?\b|luggage|suitcase|baggage",
    "seats": r"seats?|passengers?|people|persons?|\bpax\b|adults?|travell?ers?",
    "airport": r"airport|terminal|same airport",
    "cabin": r"economy|business|first class|premium|cabin|executive",
    "comfort": r"comfort|premium|luxury|minivan|\bvan\b|sedan|private|business",
    "distance": r"\bkm\b|kilomet|walking distance|close to|\bnear\b|within|from the (?:centre|center)|minutes? (?:walk|from|away)|walkable",
    "budget": r"budget|up to|under|\bmax|at most|no more than|\d\s*(?:eur|€|euro|usd|\$)|per night|per person|cheap|price",
    "age": r"\bage\b|years?|\byo\b|\bold\b|driver",
    "class": r"first class|1st|second class|2nd|\bclass\b",
    "changes": r"changes?|direct|connections?|transfers?",
    "hours": r"hours?|\bhrs?\b|half.?day|full.?day|day trip|short|long|duration",
    "rating": r"rating|rated|reviews?|score|\bstars?\b|\d\s*\+",
    "walking": r"walk|hike|on foot|stroll",
    "morning": r"morning|\bam\b|early|sunrise",
}
# a filter line (lower case) -> the topic it is about; the first match wins
LINE_TOPICS = [
    (re.compile(r"breakfast"), "breakfast"), (re.compile(r"flight tracking|tracking"), "tracking"), (re.compile(r"refundable|refund|cancellation"), "cancellation"),
    (re.compile(r"\bstars?\b"), "stars"), (re.compile(r"gearbox|automatic|manual"), "gearbox"), (re.compile(r"excess|insurance"), "excess"), (re.compile(r"direct"), "direct"),
    (re.compile(r"airport change"), "airport"), (re.compile(r"large bags|bags|baggage|\bbag\b"), "bag"), (re.compile(r"seats"), "seats"), (re.compile(r"airport"), "airport"),
    (re.compile(r"cabin"), "cabin"), (re.compile(r"comfortable|vehicle"), "comfort"), (re.compile(r"\bkm\b"), "distance"), (re.compile(r"driver age"), "age"),
    (re.compile(r"1st class|2nd class|\bclass\b"), "class"), (re.compile(r"\bchanges?\b"), "changes"), (re.compile(r"\bhours?\b"), "hours"), (re.compile(r"walking"), "walking"),
    (re.compile(r"morning"), "morning"), (re.compile(r"rating"), "rating"), (re.compile(r"budget|at most|up to|\bmax\b|\beur\b|per person|per night"), "budget"),
]
# a wish passed in `wishes` -> (topic, True when its number must also be in the request)
NUMBER_WISHES = {"max_distance_km": ("distance", True), "max_hours": ("hours", True), "max_price": ("budget", True), "max_price_pp": ("budget", True), "stars_min": ("stars", True),
                 "min_rating_10": ("rating", False)}
FLAG_WISHES = {"breakfast": "breakfast", "free_cancellation": "cancellation", "refundable": "cancellation", "checked_bag": "bag", "direct_only": "direct", "flight_tracking": "tracking"}
WISH_WORDS = {"max_distance_km": "within {v:g} km of the centre", "max_hours": "at most {v:g} hours", "max_price": "at most {v:g} EUR per person", "max_price_pp": "at most {v:g} EUR per person",
              "stars_min": "{v:g}+ stars", "min_rating_10": "a minimum rating", "breakfast": "breakfast included", "free_cancellation": "free cancellation", "refundable": "refundable fares only",
              "checked_bag": "a checked bag", "direct_only": "direct flights only", "flight_tracking": "flight tracking"}


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("’", "'"))


def says(request: str | None, topic: str) -> bool:
    """True when the request talks about this topic; a missing request proves nothing and counts as 'yes' (nothing is changed without the operator's words)."""
    if not (request or "").strip():
        return True
    return bool(re.search(EVIDENCE[topic], _clean(request)))


def has_number(request: str | None, value: float) -> bool:
    """The number (1.5, 150, '1,5', 'two') is written in the request."""
    text = _clean(request)
    forms = {f"{value:g}", f"{value:.1f}", f"{value:g}".replace(".", ",")}
    if float(value).is_integer():
        forms.add(str(int(value)))
        forms |= {w for w, n in NUMBER_WORDS.items() if n == int(value)}
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)", text) if re.fullmatch(r"[\d.,]+", f) else re.search(rf"\b{f}\b", text) for f in forms)


def _head(line: str) -> str:
    m = re.search(r"\((?:operator)", line)
    return line[:m.start()] if m else line


def line_supported(line: str, request: str) -> bool:
    """Is the topic and the number of this '(operator)' filter line in the request? A line with no known topic and no number is supported (it is not judged)."""
    head = _clean(_head(line))
    title = re.match(r"title has one of:\s*(.+)", head)
    if title:
        return any(w.strip() and w.strip() in _clean(request) for w in title.group(1).split(","))
    topic = next((t for pat, t in LINE_TOPICS if pat.search(head)), None)
    if topic and not re.search(EVIDENCE[topic], _clean(request)):
        return False
    if re.search(r"\d{4}-\d\d-\d\d|\d{1,2}:\d\d", head):         # a leg or a day with its date and time: the dates travel through the trip, not through a limit
        return True
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", head)]
    return not numbers or any(has_number(request, n) for n in numbers)


def relabel(filters: list[str], request: str | None) -> tuple[list[str], list[str]]:
    """(the filter lines with the unsupported '(operator)' labels replaced, the heads of the lines that were)."""
    if not (request or "").strip():
        return list(filters), []
    out: list[str] = []
    changed: list[str] = []
    for line in filters:
        if re.search(r"\(operator[;)]", line) and not line_supported(line, request):
            out.append(re.sub(r"\(operator(?=[;)])", f"({ASSUMED}", line, count=1))
            changed.append(_head(line).strip())
        else:
            out.append(line)
    return out, changed


def drop_unsupported(wishes: dict[str, Any] | None, request: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    """The wishes without the ones the request does not support (a limit with a number the operator never wrote, a yes/no wish the operator never mentioned), and what was left out in words."""
    if not wishes or not (request or "").strip():
        return wishes, []
    kept = dict(wishes)
    left: list[str] = []
    for key, (topic, needs_number) in NUMBER_WISHES.items():
        v = kept.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            if not says(request, topic) or (needs_number and not has_number(request, float(v))):
                kept.pop(key)
                left.append(WISH_WORDS[key].format(v=float(v)))
    for key, topic in FLAG_WISHES.items():
        if kept.get(key) is True and not says(request, topic):
            kept.pop(key)
            left.append(WISH_WORDS[key])
    if kept.get("vehicle") == "comfortable" and not says(request, "comfort"):
        kept.pop("vehicle")
        left.append("a comfortable vehicle")
    return kept, left


def not_applied_line(left: list[str]) -> str | None:
    return (f"Not applied, the request does not say it: {'; '.join(dict.fromkeys(left))} (the assistant's assumption; ask the operator if it matters)") if left else None

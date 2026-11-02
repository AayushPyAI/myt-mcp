"""What compose_answer built, kept for 3 hours, so check_answer can tell whether the draft's table rows are the server's rows or were typed or changed by the assistant.

Found 24 Oct 2026: the assistant retyped a server table in its own layout and "Business Minivan: Mercedes-Benz V-Class" became "Business Minivan: Toyota Alphard"; check_answer only looked at the
structure of the draft and passed it. The instruction is to show `answer` exactly as written: a table row whose text is not in a composed answer is reported.
"""

from __future__ import annotations

import re
import time
from typing import Any

TTL_SECONDS = 3 * 3600
MAX_KEPT = 12
_AMOUNT = re.compile(r"^(?:[€$£₪]\s?)?\d[\d,]*\.\d\d(?:\s?[A-Z]{3})?(?:\s\(.*\))?$")       # a price cell: "794.50 EUR", "€19.00", "13.00 EUR (per vehicle)"; never a link with a date in it
MIN_CELL = 6          # shorter cells ("yes", "no", "4/3") are too common to prove anything


MAX_OFFERS = 4000


class ComposedStore:
    def __init__(self) -> None:
        self._items: list[tuple[float, str, str]] = []

    def remember(self, kind: str, text: str) -> None:
        self._items = [i for i in self._items if time.time() - i[0] < TTL_SECONDS][-(MAX_KEPT - 1):] + [(time.time(), kind, text)]

    def recent(self, kind: str | None = None) -> list[str]:
        return [t for ts, k, t in self._items if time.time() - ts < TTL_SECONDS and (kind in (None, "general") or k == kind)]

    def last_time(self, kind: str) -> float:
        """When the last compose_answer of this kind succeeded (0 = never in the last 3 hours)."""
        return max((ts for ts, k, _ in self._items if k == kind and time.time() - ts < TTL_SECONDS), default=0.0)

    def clear(self) -> None:
        self._items = []


COMPOSED = ComposedStore()


class OfferStore:
    """The rows of every successful compose_answer, as the server itself held them (29 Oct 2026). A row the operator chooses is found again from what the answer shows (source, name, price), so its
    price, currency and group are never retyped by the assistant (plan_from_answer)."""

    def __init__(self) -> None:
        self._items: list[tuple[float, str, Any]] = []

    @staticmethod
    def _key(o: Any) -> tuple:
        return (o.group, o.source, o.name, o.price_total)

    def remember(self, kind: str, offers: list[Any]) -> None:
        now = time.time()
        fresh = {self._key(o) for o in offers}
        kept = [i for i in self._items if now - i[0] < TTL_SECONDS and not (i[1] == kind and self._key(i[2]) in fresh)]
        self._items = (kept + [(now, kind, o) for o in offers])[-MAX_OFFERS:]

    def recent(self, kind: str) -> list[Any]:
        return [o for ts, k, o in self._items if k == kind and time.time() - ts < TTL_SECONDS]

    def clear(self) -> None:
        self._items = []


OFFERS = OfferStore()


class SummaryStore:
    """The structured summary of the last composed answer of each kind (picks, sources, filters, cautions), kept so compose_summary can build ONE final text for the operator without the assistant writing it
    (2 Nov 2026: the final message of an all-in-one run was the assistant's own prose: no Sources line, no Picks table, filters nobody asked for written as the operator's wishes, check_answer never called)."""

    def __init__(self) -> None:
        self._last: dict[str, dict[str, Any]] = {}

    def remember(self, kind: str, request: str | None, summary: dict[str, Any]) -> None:
        self._last[kind] = {**summary, "time": time.time(), "request": request}

    def recent(self) -> dict[str, dict[str, Any]]:
        return {k: v for k, v in self._last.items() if time.time() - v["time"] < TTL_SECONDS}

    def clear(self) -> None:
        self._last.clear()


SUMMARIES = SummaryStore()


CARRY_SECONDS = 45 * 60          # an earlier answer of the same kind and the same request still counts for this long
CARRY_SECONDS_NO_REQUEST = 20 * 60


def _same_words(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _source_key(name: str | None) -> str:
    return _same_words(str(name or "").split(" (")[0])


class CarryStore:
    """The rows of the last composed answer of each kind, kept so that a second compose_answer of the same kind and the same request does not lose a source (30 Oct 2026: the GetYourGuide list of 14 parts
    was composed once, then the activities were composed again with another source, and the list was gone: the chat would have had to pass every part again). A source the new call does not have, and did
    not put in not_checked, comes back from here with its rows and its 'N of M', and the answer says so. A different request, another kind or an older answer carries nothing."""

    def __init__(self) -> None:
        self._last: dict[str, dict[str, Any]] = {}

    def clear(self) -> None:
        self._last.clear()

    def remember(self, kind: str, request: str | None, offers: list[Any], sources_read: list[Any]) -> None:
        self._last[kind] = {"time": time.time(), "request": _same_words(request), "offers": [o.model_copy(deep=True) for o in offers], "sources": [x.model_copy(deep=True) for x in sources_read]}

    def carry(self, kind: str, request: str | None, offers: list[Any], sources_read: list[Any], skipped: list[str]) -> tuple[list[Any], list[Any], str | None]:
        prev = self._last.get(kind)
        want = _same_words(request)
        if not prev or prev["request"] != want or time.time() - prev["time"] > (CARRY_SECONDS if want else CARRY_SECONDS_NO_REQUEST):
            return [], [], None
        have = {_source_key(x.name) for x in sources_read} | {_source_key(o.source) for o in offers}
        skip = [_same_words(n) for n in skipped if _same_words(n)]
        rows: list[Any] = []
        sources: list[Any] = []
        said: list[str] = []
        for src in prev["sources"]:
            key = _source_key(src.name)
            if not key or key in have or any(key in n or n in key for n in skip):
                continue
            mine = [o.model_copy(deep=True) for o in prev["offers"] if _source_key(o.source) == key]
            if not mine:
                continue
            rows += mine
            sources.append(src.model_copy(deep=True))
            said.append(f"{src.name} ({len(mine)} rows)")
        if not said:
            return [], [], None
        return rows, sources, ("Carried from the earlier answer of this kind (the server kept these rows, nothing was read again): " + ", ".join(said) + ".")


CARRY = CarryStore()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip().lower()


def _rows(draft: str) -> list[list[str]]:
    """The cells of every table row that carries a price (header and divider rows have none)."""
    rows = []
    for line in draft.splitlines():
        if "\t" not in line and not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.strip().strip("|").split("|"))]
        if len(cells) >= 4 and any(_AMOUNT.match(c.replace("**", "").strip()) for c in cells):
            rows.append(cells)
    return rows


def is_unchanged(draft: str, kind: str, store: ComposedStore = COMPOSED) -> bool:
    """True when the draft holds a compose_answer text of this kind word for word (spaces and line breaks aside): the chat showed the server's own text and added nothing to a row, a pick or a number."""
    flat = _norm(draft)
    return any(_norm(t) and _norm(t) in flat for t in store.recent(kind))


def row_problems(draft: str, kind: str, store: ComposedStore = COMPOSED) -> list[str]:
    rows = _rows(draft)
    if not rows:
        return []
    composed = store.recent(kind)
    if not composed:
        return ["the draft has price rows but no compose_answer result of the last 3 hours exists on this server: call task_plan, read the sources and send what compose_answer returns (never an earlier chat's table)"]
    known = " ".join(_norm(t) for t in composed)
    changed: list[str] = []
    for cells in rows:
        for cell in cells:
            text = _norm(cell)
            if len(text) >= MIN_CELL and text not in known and text not in changed:
                changed.append(text)
    if not changed:
        return []
    shown = "; ".join(f"'{c[:60]}'" for c in changed[:4]) + (f" and {len(changed) - 4} more" if len(changed) > 4 else "")
    return [f"table rows were typed or changed by hand (not in the compose_answer text): {shown}. Show compose_answer's `answer` exactly as written; do not retype, reword or reorder its rows"]


def shortened_warnings(draft: str, kind: str, store: ComposedStore = COMPOSED) -> list[str]:
    """The draft has fewer table rows than the compose_answer text of its kind (28 Oct 2026: a draft of 3 of 23 flight rows was checked 'ok' and the whole text was shown afterwards, so the check had covered a text nobody saw).
    A warning, never a refusal: it says what this check covered."""
    composed = store.recent(kind)
    if not composed or kind in (None, "general"):
        return []
    want = _rows(composed[-1])
    if len(want) < 2:
        return []
    low = _norm(draft)
    missing = [r for r in want if not all(_norm(c) in low for c in r[:2] if _norm(c))]
    if not missing:
        return []
    shown = len(want) - len(missing)
    return [f"this draft shows {shown} of the {len(want)} table rows of the compose_answer text ({len(missing)} missing): this check covers only the rows you pasted, not the text the operator will see. "
            "Show the composed answer unchanged and in full, and check that same text."]


_NUMBER = re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|(?<![\d.,])\d+(?:\.\d+)?(?![\d,])")
_PRICE_IN_PROSE = re.compile(r"[€$£₪]\s?(\d[\d,]*(?:\.\d\d?)?)|(\d[\d,]*\.\d\d)\s?(?:EUR|USD|GBP|ILS)\b")
MAX_MULTIPLE = 9      # a per-person price times the group ("80.00 per person" -> 240.00 for three) is the assistant's own arithmetic, not a typed price


def known_amounts(store: ComposedStore = COMPOSED) -> set[float]:
    """Every number in a compose_answer text or a calculate_quote answer of the last 3 hours."""
    found: set[float] = set()
    for text in store.recent(None):
        for n in _NUMBER.findall(text):
            try:
                found.add(round(float(n.replace(",", "")), 2))
            except ValueError:
                pass
    return found


def _is_known(value: float, known: set[float]) -> bool:
    value = round(value, 2)
    return value in known or any(round(k * m, 2) == value for k in known for m in range(2, MAX_MULTIPLE + 1))


def _amount_cells(draft: str) -> list[float]:
    cells = []
    for line in draft.splitlines():
        if "\t" not in line and not line.lstrip().startswith("|"):
            continue
        for c in (line.split("\t") if "\t" in line else line.strip().strip("|").split("|")):
            c = c.replace("**", "").strip()
            if _AMOUNT.match(c):
                cells.append(float(re.sub(r"[^\d.]", "", c.split("(")[0].replace(",", "")) or 0))
    return cells


def amount_problems(draft: str, store: ComposedStore = COMPOSED) -> tuple[list[str], list[str]]:
    """(problems, warnings): a price in a table cell that no compose_answer or calculate_quote of the last 3 hours holds was read or typed by hand (24 Oct 2026: hotel and tour prices
    read off the pages went into the final table). A price in a sentence is only a warning: a difference ('+157') is the assistant's own sum."""
    known = known_amounts(store)
    if not known:
        return [], []
    cells = [c for c in _amount_cells(draft) if c and not _is_known(c, known)]
    prose = []
    for m in _PRICE_IN_PROSE.finditer(draft):
        v = float((m.group(1) or m.group(2)).replace(",", ""))
        if v >= 20 and not _is_known(v, known) and v not in cells and f"{v:g}" not in prose:
            prose.append(f"{v:g}")
    problems = [f"price(s) in the table that no compose_answer or calculate_quote of the last 3 hours holds: {', '.join(f'{c:g}' for c in dict.fromkeys(cells))}. "
                "Use only prices from the tools' answers; never read a price off a page by hand (run the site's recipe, or write that it was not read)"] if cells else []
    warnings = [f"amounts in the text that no tool answer holds: {', '.join(prose[:6])}: if one is your own sum, say how it is calculated; if you read it off a page, remove it"] if prose else []
    return problems, warnings


_FOREIGN_IN_CELL = re.compile(r"[$£₪₹]\s?\d|\d\s?(?:USD|GBP|ILS|INR|CHF)\b")


def currency_problems(draft: str, store: ComposedStore = COMPOSED) -> list[str]:
    """The server converts a price shown in another currency to euro and says so in the row ("converted from USD 86.50 at 1 USD = 0.8885 EUR"): a table cell of the draft in the OTHER currency
    shows the unconverted price next to euro rows (27 Oct 2026: Europcar prices Israeli drivers in dollars). Only the text of the server's own table is shown."""
    if not any("converted from" in t for t in store.recent(None)):
        return []
    cells = [c.strip() for line in draft.splitlines() if line.lstrip().startswith("|") for c in line.strip().strip("|").split("|") if "converted from" not in c and _FOREIGN_IN_CELL.search(c)]
    if not cells:
        return []
    return [f"a table cell shows a price in another currency ({'; '.join(c[:40] for c in cells[:3])}) although the server converted that source to euro: show compose_answer's euro price and its price basis exactly, never the "
            "original or your own conversion"]


_SOURCES_LINE = re.compile(r"Sources checked:\s*(.*?)(?:\s*\|\s*Not checked:|$)", re.I | re.M)


def source_warnings(draft: str, kind: str | None = None, store: ComposedStore = COMPOSED) -> list[str]:
    """Sources a compose_answer of the last 3 hours says it read that the draft does not name at all (24 Oct 2026: El Al, Arbitrip, Ofran and RateHawk Air were read and missing from the final Sources).
    Only answers of the draft's own kind count (28 Oct 2026: a train answer was warned about Kiwitaxi and iWay, the sources of the transfer answer written before it)."""
    low = draft.lower()
    missing: list[str] = []
    for text in store.recent(kind):
        for line in _SOURCES_LINE.findall(text):
            for part in line.split(";"):
                name = re.sub(r"\s*\(.*$", "", part).strip()
                words = [w for w in re.split(r"[^\w]+", name.lower()) if len(w) >= 4] or [name.lower()]      # "El Al" has no long word: its whole name must appear
                if name and not any(w in low for w in words) and name not in missing:
                    missing.append(name)
    return [f"sources the compose_answer results say were read but the draft does not name: {', '.join(missing[:8])}: add them to the Sources and to 'Sources checked' (or say why they are left out)"] if missing else []

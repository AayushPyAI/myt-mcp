"""What compose_answer built, kept for 3 hours, so check_answer can tell whether the draft's table rows are the server's rows or were typed or changed by the assistant.

Found 24 Oct 2026: the assistant retyped a server table in its own layout and "Business Minivan: Mercedes-Benz V-Class" became "Business Minivan: Toyota Alphard"; check_answer only looked at the
structure of the draft and passed it. The instruction is to show `answer` exactly as written: a table row whose text is not in a composed answer is reported.
"""

from __future__ import annotations

import re
import time

TTL_SECONDS = 3 * 3600
MAX_KEPT = 12
_PRICE = re.compile(r"\d[\d,]*\.\d\d\b")
MIN_CELL = 6          # shorter cells ("yes", "no", "4/3") are too common to prove anything


class ComposedStore:
    def __init__(self) -> None:
        self._items: list[tuple[float, str, str]] = []

    def remember(self, kind: str, text: str) -> None:
        self._items = [i for i in self._items if time.time() - i[0] < TTL_SECONDS][-(MAX_KEPT - 1):] + [(time.time(), kind, text)]

    def recent(self, kind: str | None = None) -> list[str]:
        return [t for ts, k, t in self._items if time.time() - ts < TTL_SECONDS and (kind in (None, "general") or k == kind)]

    def clear(self) -> None:
        self._items = []


COMPOSED = ComposedStore()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip().lower()


def _rows(draft: str) -> list[list[str]]:
    """The cells of every table row that carries a price (header and divider rows have none)."""
    rows = []
    for line in draft.splitlines():
        cells = [c.strip() for c in (line.split("\t") if "\t" in line else line.strip().strip("|").split("|"))]
        if len(cells) >= 4 and any(_PRICE.search(c) for c in cells):
            rows.append(cells)
    return rows


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

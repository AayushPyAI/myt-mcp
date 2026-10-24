"""MYT supplier directory: id, type and subtype of the suppliers seen on real trips, found by name.

A reservation needs an existing MYT supplier id and the supplier's type decides which product types MYT keeps
(see reservations.SUPPLIER_KIND). The API has no supplier search, so the ids are collected from trips'
`suppliers` blocks by scripts/build_supplier_directory.py into suppliers.json. A supplier that is not in the file is
NOT guessed: the operator names it, or it is read from the MYT screen.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PATH = Path(__file__).with_name("suppliers.json")
KINDS = ("transportation", "lodging", "attraction", "dmc", "staff", "food", "other")
# words that say nothing about which supplier it is
FILLER = {"inc", "ltd", "limited", "llc", "the", "and", "of", "de", "la", "co", "company", "services", "service", "travel", "tours", "tour", "worldwide"}


def kind_of(flags: dict[str, Any] | None) -> str | None:
    """The supplier type MYT reports as {"lodging": true}, as a plain word."""
    return next((k for k, v in (flags or {}).items() if v is True and k in KINDS), None)


def subtype_of(sub: dict[str, Any] | None) -> str | None:
    return (sub or {}).get("name")


def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in FILLER}


@lru_cache(maxsize=1)
def load() -> tuple[dict[str, Any], ...]:
    return tuple(json.loads(PATH.read_text())) if PATH.exists() else ()


def find_suppliers(query: str, kind: str | None = None) -> list[dict[str, Any]]:
    """Suppliers whose name or private name contains every distinctive word of `query` (best match first)."""
    want = _words(query)
    if not want:
        return []
    hits = []
    for s in load():
        if kind and s.get("type") != kind:
            continue
        have = _words(s.get("name")) | _words(s.get("private_name"))
        if want <= have:
            hits.append((len(have - want), s))      # fewer extra words = closer match
    return [s for _, s in sorted(hits, key=lambda x: (x[0], x[1]["id"]))]

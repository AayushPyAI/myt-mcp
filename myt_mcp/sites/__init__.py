"""One module per Chrome-only site: a tested read-only script for the operator's own logged-in Chrome, a URL builder and a converter.

A site module (myt_mcp/sites/<name>.py) must define:
    NAME: str                                  the site key, e.g. "ratehawk_hotels"
    def register(mcp) -> None                  registers the recipe tool (returns the url + script, see ratehawk_hotels.py)
    def convert(result_json: str, wishes: dict, group: str) -> SiteRows
and sits next to its script (myt_mcp/sites/<name>.js). Modules are discovered automatically: no shared file needs editing.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from myt_mcp.compose import Offer, SourceRead


@dataclass
class SiteRows:
    offers: list[Offer] = field(default_factory=list)
    read: int | None = None            # how many results the script read
    total: int | None = None           # how many exist after the filters (M)
    problems: list[str] = field(default_factory=list)
    sorted_by_price: bool = False
    extra_notes: list[str] = field(default_factory=list)
    read_rows: bool = False           # True when `read` / `total` count rows (rooms of a hotel), not the offers that are kept


def modules() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "NAME") and hasattr(mod, "convert"):
            found[mod.NAME] = mod
    return found


def register_all(mcp: Any) -> None:
    for mod in modules().values():
        if hasattr(mod, "register"):
            mod.register(mcp)


def convert_all(site_results: list[dict[str, Any]], wishes: dict[str, Any] | None, group_for: dict[str, str] | None = None) -> tuple[list[Offer], list[SourceRead], list[str], bool, list[str]]:
    """site_results: [{"site": "ratehawk_hotels", "result": "<the script's answer text>", "url": "<the page address>"}]."""
    mods = modules()
    offers: list[Offer] = []
    sources: dict[str, SourceRead] = {}
    problems: list[str] = []
    notes: list[str] = []
    by_price = False
    reads: dict[str, set[str]] = {}
    counted: dict[str, tuple[int, int]] = {}
    problems += check_parts(site_results)
    for item in site_results:
        site = item.get("site", "")
        mod = mods.get(site)
        if mod is None:
            problems.append(f"unknown site '{site}': known sites are {sorted(mods)}")
            continue
        rows = mod.convert(expand(item.get("result", "")), wishes or {}, (group_for or {}).get(site, getattr(mod, "GROUP", "Options")))
        problems += rows.problems
        notes += rows.extra_notes
        by_price = by_price or rows.sorted_by_price
        seen = reads.setdefault(site, {o.link or f"{o.name}|{o.price_total}" for o in offers if o.source == getattr(mod, "SOURCE", site)})
        for o in rows.offers:
            key = o.link or f"{o.name}|{o.price_total}"
            if key not in seen:
                seen.add(key)
                offers.append(o)
        src_name = getattr(mod, "SOURCE", site)
        cur = sources.get(site)
        if rows.read_rows:       # e.g. the rooms read on hotel pages: every room read counts, one offer is kept per hotel
            counted[site] = (counted.get(site, (0, 0))[0] + (rows.read or 0), counted.get(site, (0, 0))[1] + (rows.total or 0))
            read, of = counted[site]
        else:
            read, of = len(seen) or None, rows.total or (cur.of if cur else None)
        sources[site] = SourceRead(name=src_name, read=read, of=of, link=item.get("url") or (cur.link if cur else None))
    return offers, list(sources.values()), problems, by_price, notes



def with_emit(script: str) -> str:
    """Adds the short-parts output step (emit.js) to a site script: it must start its body with 'await (async () => {' and end with emit(head, rows)."""
    head = "await (async () => {\n"
    if head not in script:
        raise ValueError("site script must start its body with 'await (async () => {'")
    return script.replace(head, head + Path(__file__).with_name("emit.js").read_text(encoding="utf-8"), 1)


def expand(raw: str) -> str:
    """The compact form the scripts emit (columns, common values, path base) back to the plain `rows` of dicts the converters read. Other text passes unchanged."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict) or "cols" not in data:
        return raw
    cols, common, base = data.pop("cols"), data.pop("common", None) or {}, data.pop("path_base", "") or ""
    rows = []
    for values in data.get("rows", []):
        row = dict(common)
        row.update(zip(cols, values))
        if row.get("path") and "path" in cols:
            row["path"] = base + row["path"]
        rows.append(row)
    data["rows"] = rows
    return json.dumps(data)


def check_parts(site_results: list[dict[str, Any]]) -> list[str]:
    """Every run of a script is sent in parts: all of them must be here, and together they must hold every row the script says it read."""
    runs: dict[tuple[str, str], dict[int, int]] = {}
    meta: dict[tuple[str, str], tuple[int, int]] = {}
    for item in site_results:
        try:
            data = json.loads(item.get("result", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("parts") and data.get("run"):
            key = (str(item.get("site", "")), str(data["run"]))
            runs.setdefault(key, {})[int(data.get("part", 0))] = len(data.get("rows") or [])
            meta[key] = (int(data["parts"]), int(data.get("rows_read") or 0))
    problems = []
    for key, got in runs.items():
        parts, rows_read = meta[key]
        missing = [i for i in range(1, parts + 1) if i not in got]
        if missing:
            problems.append(f"{key[0]}: part(s) {', '.join(map(str, missing))} of {parts} are missing: run window.__mytParts[<number minus 1>] in the same Chrome tab (the answer's `more` line) and pass each part unchanged as its own item of site_results")
        elif sum(got.values()) != rows_read:
            problems.append(f"{key[0]}: the parts hold {sum(got.values())} rows but the script read {rows_read}: run the script again and pass every part unchanged")
    return problems


GENERIC_PLACE_WORDS = {"airport", "station", "railway", "terminal", "international", "intl", "city", "center", "centre", "downtown", "the", "of", "de", "da", "di", "and"}


def place_matches(expected: str | None, got: str | None) -> bool:
    """Is the place the page searched the place that was asked? Compared by the DISTINCTIVE words (not 'airport', 'station'...): 'Faro Airport' is 'Portugal, Faro Airport', never 'Spain, Malaga Airport'."""
    def words(x: str | None) -> set[str]:
        return {w for w in re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).split() if w not in GENERIC_PLACE_WORDS}
    want, have = words(expected), words(got)
    return not want or not have or bool(want & have)

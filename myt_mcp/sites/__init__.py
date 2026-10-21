"""One module per Chrome-only site: a tested read-only script for the operator's own logged-in Chrome, a URL builder and a converter.

A site module (myt_mcp/sites/<name>.py) must define:
    NAME: str                                  the site key, e.g. "ratehawk_hotels"
    def register(mcp) -> None                  registers the recipe tool (returns the url + script, see ratehawk_hotels.py)
    def convert(result_json: str, wishes: dict, group: str) -> SiteRows
and sits next to its script (myt_mcp/sites/<name>.js). Modules are discovered automatically: no shared file needs editing.
"""

from __future__ import annotations

import importlib
import pkgutil
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
    for item in site_results:
        site = item.get("site", "")
        mod = mods.get(site)
        if mod is None:
            problems.append(f"unknown site '{site}': known sites are {sorted(mods)}")
            continue
        rows = mod.convert(item.get("result", ""), wishes or {}, (group_for or {}).get(site, getattr(mod, "GROUP", "Options")))
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
        sources[site] = SourceRead(name=src_name, read=len(seen) or None, of=rows.total or (cur.of if cur else None), link=item.get("url") or (cur.link if cur else None))
    return offers, list(sources.values()), problems, by_price, notes

"""Ofran pick-up points: parsing /api/locations and matching names typed by the operator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = {"1": "airport", "2": "city", "3": "railway", "4": "other"}
# Ofran names some cities in the local language with no English alias (e.g. "Firenze Airport").
EXONYMS = {
    "florence": "firenze", "rome": "roma", "milan": "milano", "venice": "venezia", "naples": "napoli",
    "turin": "torino", "genoa": "genova", "munich": "münchen", "cologne": "köln", "vienna": "wien",
    "prague": "praha", "lisbon": "lisboa", "seville": "sevilla", "athens": "athina", "copenhagen": "københavn",
}


def _first(v: Any) -> Any:
    return (v[0] if v else None) if isinstance(v, list) else v


@dataclass(frozen=True)
class Location:
    name: str
    code: str
    kind: str
    country_id: str
    iata_id: str
    preferred: bool
    aliases: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "code": self.code, "kind": self.kind, "country_id": self.country_id, "iata_id": self.iata_id}


def parse_locations(raw: Any) -> list[Location]:
    """Pick-up points only (country rows are skipped); malformed rows are dropped."""
    out = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or _first(r.get("field_type")) != "iata":
            continue
        name, iata_id, country = _first(r.get("description")), _first(r.get("field_id")), _first(r.get("field_country_id"))
        if not (name and iata_id and country):
            continue
        out.append(Location(
            name=name, code=_first(r.get("name")) or "", kind=KINDS.get(_first(r.get("field_iata_code_type_id")), "other"),
            country_id=str(country), iata_id=str(iata_id), preferred=_first(r.get("field_preferred")) == "1",
            aliases=tuple(a for a in r.get("field_alternate_names") or [] if isinstance(a, str) and a),
        ))
    return out


class LocationIndex:
    """Lower-cased fields computed once, so each lookup is a single pass over ~1,500 points."""

    def __init__(self, locations: list[Location]):
        self._rows = [(loc, loc.code.lower(), loc.name.lower(), tuple(a.lower() for a in loc.aliases)) for loc in locations]

    def __len__(self) -> int:
        return len(self._rows)

    def match(self, query: str, limit: int = 8) -> list[Location]:
        """Rank: exact code, name starts with, name contains, alias contains. Airports and
        preferred points first within a rank."""
        q = " ".join(query.lower().split())
        if not q:
            return []
        variants = [q] + [q.replace(en, local) for en, local in EXONYMS.items() if en in q]
        ranked = []
        for loc, code, name, aliases in self._rows:
            if code in variants:
                rank = 0
            elif any(name.startswith(v) for v in variants):
                rank = 1
            elif any(v in name for v in variants):
                rank = 2
            elif any(v in a for v in variants for a in aliases):
                rank = 3
            else:
                continue
            ranked.append((rank, loc.kind != "airport", not loc.preferred, loc.name, loc))
        ranked.sort(key=lambda r: r[:4])
        return [r[4] for r in ranked[:limit]]

"""Build myt_mcp/myt/suppliers.json from the GetTrip/v3 answers of a few trips (read only, one GET per trip).

    PYTHONPATH=. .venv/bin/python scripts/build_supplier_directory.py 235475 189423 276310 197794

A supplier is taken from the trip's `suppliers` block, from its reservations and from its quotation lines. Only id, names, type and
subtype are kept (no contact data). Entries already in the file are kept and extended, so the directory grows trip by trip.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.disable(logging.CRITICAL)
for _l in open(".env"):
    if "=" in _l and not _l.startswith("#"):
        _k, _v = _l.rstrip("\n").split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from myt_mcp.config import Settings
from myt_mcp.myt.supplier_directory import PATH, kind_of, subtype_of
from myt_mcp.services import Services


def _entries(v3: dict) -> list[dict]:
    """Suppliers with their type (trip `suppliers` block, reservations, quotation hotels) and suppliers seen only on quotation lines
    (id and name; a line carries the PRODUCT type, which is not the supplier's type)."""
    rows = list(v3.get("suppliers") or []) + list(v3.get("reservations") or [])
    for pkg in (v3.get("quotation") or {}).get("product_packages") or []:
        rows += [h for h in pkg.get("hotels") or [] if isinstance(h, dict)]
        for p in pkg.get("products") or []:
            if isinstance(p, dict):
                rows.append({"supplier_id": p.get("supplier_id"), "supplier_name": p.get("supplier_name"),
                             "_product_type": (p.get("type") or {}).get("name")})
    return [r for r in rows if r.get("supplier_id")]


async def main(trip_ids: list[int]) -> None:
    myt = Services(Settings.from_env()).myt()
    known = {s["id"]: s for s in json.loads(PATH.read_text())} if PATH.exists() else {}
    for trip_id in trip_ids:
        v3 = await myt.get_trip_v3(trip_id)
        for r in _entries(v3):
            sid = r["supplier_id"]
            entry = known.setdefault(sid, {"id": sid, "name": r.get("supplier_name"), "private_name": r.get("supplier_private_name"),
                                            "type": None, "subtype": None, "trips": []})
            if r.get("_product_type") and r["_product_type"] not in entry.setdefault("product_types", []):
                entry["product_types"].append(r["_product_type"])
            entry["type"] = entry["type"] or kind_of(r.get("supplier_type"))
            entry["subtype"] = entry["subtype"] or subtype_of(r.get("supplier_subtype"))
            entry["name"] = entry["name"] or r.get("supplier_name")
            entry["private_name"] = entry["private_name"] or r.get("supplier_private_name")
            if trip_id not in entry["trips"]:
                entry["trips"].append(trip_id)
    rows = sorted(known.values(), key=lambda s: (s["type"] or "", (s["name"] or "").lower()))
    PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(rows)} suppliers in {PATH}")


if __name__ == "__main__":
    asyncio.run(main([int(x) for x in sys.argv[1:]]))

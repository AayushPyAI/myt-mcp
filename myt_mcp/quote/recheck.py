"""Re-checking the prices of a quotation that already exists: read only, nothing is written in MYT.

Two steps, both done by the server so that the assistant only runs the sources and shows the text:
1. `plan(v3)`: every cost line of the selected quotation, the net the MYT reservation holds for it, and which tools can price it again (or why none can).
2. `report(v3, checks)`: the new prices the assistant found are accepted only if the very row, with that very price, is in a compose_answer of the last 3 hours
   (the server's own text); the answer is the old net against the new price per line, the counts, and what was not checked and why.

Why: the 26 Oct 2026 re-check of trip 168 was written by the assistant in its own table (a count of 12 of 14 for 11 lines, two GetYourGuide prices that never went through
compose_answer). Net prices come from the supplier reservations because the quotation API shows only prices with the profit added.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from myt_mcp.composed import ComposedStore
from myt_mcp.myt.reservations import _quote_lines, reconcile

TRANSFER_WORDS = re.compile(r"transfer|trf", re.I)
SAME = 0.005


def classify(line: dict[str, Any]) -> dict[str, Any]:
    """What a quotation line is, which tools can price it again, and what the assistant must ask first."""
    product, supplier = str(line.get("product") or ""), str(line.get("supplier") or "")
    s = supplier.lower()
    transport, category = line.get("transport"), line.get("category")
    if transport == "Plane":
        first = "tap_recipe" if "tap" in s else "sata_recipe" if ("sata" in s or "azores" in s) else "elal_recipe" if "el al" in s else "ratehawk_air_recipe"
        return {"kind": "flights", "tools": [first] + ([] if first == "ratehawk_air_recipe" else ["ratehawk_air_recipe"]), "needs": "direct or not, checked bags, the travellers' ages"}
    if transport == "Train":
        first = "train_prices (Trenitalia)" if "trenitalia" in s else "cp_trains_recipe" if "cp" in s.split() or "comboios" in s else "ratehawk_trains_recipe"
        return {"kind": "trains", "tools": [first], "needs": "the train's time and class"}
    if transport == "Car":
        if TRANSFER_WORDS.search(product):
            return {"kind": "transfers", "tools": ["ratehawk_transfers_recipe", "kiwitaxi_transfer_prices"], "needs": "the real flight time and the number of bags"}
        return {"kind": "cars", "tools": ["ratehawk_cars_recipe", "ofran_recipe"], "needs": "pick-up and return times and the driver's age"}
    if category == "Attraction":
        tool = "getyourguide_activity_recipe" if "guide" in s else "viator_activity_recipe" if "viator" in s else None
        return {"kind": "activities", "tools": [tool] if tool else [], "needs": "the link of the activity (it is not in MYT)", **({} if tool else {"no_tool": "its supplier has no price tool here"})}
    if category == "Lodging" and line.get("line_type") == "Room":
        return {"kind": "hotels", "tools": ["ratehawk_hotels_recipe", "arbitrip_hotels_recipe"], "needs": "the bed set-up and the cancellation terms"}
    if "lounge" in product.lower():
        return {"kind": "lounges", "tools": ["lounge_prices (Aspire)", "loungepair_lounges"], "needs": "the flight's departure time"}
    return {"kind": "other", "tools": [], "needs": "", "no_tool": "no tool here has a price for this line: ask the operator"}


def _lines(v3: dict[str, Any], today: date) -> list[dict[str, Any]]:
    lines, _ = _quote_lines(v3)
    rows = list(reconcile(v3, today)["rows"])
    out = []
    for n, line in enumerate(lines, 1):
        match = next((r for r in rows if r["quote_line"] == line.get("product")), None)
        if match:
            rows.remove(match)
        out.append({"line": n, "product": line.get("product"), "supplier": line.get("supplier"), "date": line.get("date"), "package": line.get("package"),
                    "quote_total": match["quote_line_total"] if match else None, "net": match["reservation_cost"] if match else None,
                    "net_currency": match["reservation_currency"] if match else None, "quote_currency": match.get("quote_currency") if match else None, **classify(line)})
    return out


def plan(v3: dict[str, Any], today: date) -> dict[str, Any]:
    lines = _lines(v3, today)
    quote = (v3.get("quotation") or {})
    priced = [x for x in lines if x["tools"]]
    return {"quotation": f"{quote.get('number')} (version {quote.get('version')}, {quote.get('status')})", "lines": lines,
            "counts": {"lines": len(lines), "can_be_priced_again": len(priced), "no_tool": len(lines) - len(priced), "without_reservation_net": sum(1 for x in lines if x["net"] is None)},
            "next": ("For every line with `tools`: ask the operator what `needs` says (once, for all lines), run the tool with the line's date and the trip's travellers, and call compose_answer "
                     "for the kind (its text is the only source of a new price). Then call recheck_report(trip_id, checks=[{line, option, price, currency}]) with, for each line, the exact "
                     "`option` text of the row you chose in the compose_answer table and its price. Never type a price that is not in a compose_answer."),
            "net_note": "net = the cost on the line's supplier reservation (MYT shows quote lines only with the profit added); a line with no reservation has no net to compare with"}


def _found(store: ComposedStore, option: str, price: float, currency: str) -> bool:
    option = " ".join(option.lower().split())
    amount = re.compile(rf"(?<![\d.,])(?:{re.escape(f'{price:.2f}')}|{re.escape(f'{price:,.2f}')})\s?{re.escape(currency)}", re.I)
    return any(option and option in " ".join(line.lower().split()) and amount.search(line) for text in store.recent(None) for line in text.splitlines())


def report(v3: dict[str, Any], checks: list[dict[str, Any]], store: ComposedStore, today: date) -> dict[str, Any]:
    lines = {x["line"]: x for x in _lines(v3, today)}
    problems, rows, seen = [], [], set()
    for c in checks:
        n = c.get("line")
        line = lines.get(n)
        if line is None:
            problems.append(f"line {n}: the quotation has no such line (1 to {len(lines)})")
            continue
        if n in seen:
            problems.append(f"line {n}: given twice")
            continue
        seen.add(n)
        price, cur = float(c["price"]), str(c.get("currency") or "EUR").upper()
        if not _found(store, str(c.get("option") or ""), price, cur):
            problems.append(f"line {n} ({line['product']}): '{c.get('option')}' at {price:.2f} {cur} is in no compose_answer of the last 3 hours. Use the exact option text and price of a row the server built; "
                            "never a price you read or typed yourself")
            continue
        net, ncur = line["net"], line["net_currency"]
        if net is None:
            verdict, diff, pct = "no net", None, None
        elif ncur and ncur != cur:
            verdict, diff, pct = f"currency differs ({ncur} against {cur})", None, None
        else:
            diff = round(price - net, 2)
            pct = round(diff / net * 100, 1) if net else None
            verdict = "same" if abs(diff) < SAME else "changed"
        rows.append({"line": n, "product": line["product"], "supplier": line["supplier"], "date": line["date"], "net": net, "today": price, "currency": cur, "difference": diff, "pct": pct,
                     "verdict": verdict, "option": c.get("option")})
    if problems:
        return {"ok": False, "problems": problems, "next": "Fix these and call recheck_report again. Do not write the comparison yourself."}
    not_checked = [{"line": x["line"], "product": x["product"], "reason": x.get("no_tool") or "not re-read in this answer"} for n, x in lines.items() if n not in seen]
    count = lambda v: sum(1 for r in rows if r["verdict"] == v)      # noqa: E731
    changed = [r for r in rows if r["verdict"] == "changed"]
    table = ["| Line | Product | Net in MYT | Today | Difference | Verdict |", "|---|---|---|---|---|---|"]
    for r in rows:
        net = f"{r['net']:.2f}" if r["net"] is not None else "not on a reservation"
        diff = f"{r['difference']:+.2f} ({r['pct']:+.1f}%)" if r["difference"] is not None else "n/a"
        table.append(f"| {r['line']} | {str(r['product'])[:60]} ({r['option']}) | {net} | {r['today']:.2f} {r['currency']} | {diff} | {r['verdict']} |")
    summary = (f"{len(rows)} of {len(lines)} lines re-checked: {count('same')} same, {len(changed)} changed"
               + (f" (together {sum(r['difference'] for r in changed):+.2f})" if changed else "") + f"; {len(not_checked)} not checked.")
    answer = "\n".join([summary, "", *table, "", "Not checked:", *[f"- line {x['line']} {x['product']}: {x['reason']}" for x in not_checked]]) if rows or not_checked else summary
    store.remember("recheck", answer)
    return {"ok": True, "answer": answer, "counts": {"lines": len(lines), "re_checked": len(rows), "same": count("same"), "changed": len(changed), "not_checked": len(not_checked)},
            "next": "Show `answer` exactly as written, then call check_answer with it. A changed price is a finding, not a correction: nothing was changed in MYT."}

"""Does every supplier reservation have its voucher, supplier invoice and supplier payment?

The API gives the reservations and the order status. Voucher numbers, supplier invoices and supplier payments exist only
on MYT's screens, so Claude reads them from the trip's own pages and passes them in; this module does the matching and
the amount checks, the same way every time.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from myt_mcp.myt.reservations import reservations_summary

AMOUNT_TOLERANCE = 1.0      # in the reservation's currency, for rounding and conversion cents


def _key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _same_supplier(a: str | None, b: str | None) -> bool:
    ka, kb = _key(a), _key(b)
    return bool(ka and kb) and (ka in kb or kb in ka)


def _match(doc: dict[str, Any], rows: list[dict[str, Any]], tolerance: float) -> tuple[dict[str, Any] | None, str | None]:
    """The reservation a screen document belongs to: its order id, else the supplier name (and amount when several)."""
    if doc.get("order_id") is not None:
        hit = next((r for r in rows if r["order_id"] == doc["order_id"]), None)
        return (hit, None) if hit else (None, f"order {doc['order_id']} is not a reservation of this trip")
    candidates = [r for r in rows if _same_supplier(doc.get("supplier"), r["supplier"])]
    if len(candidates) > 1 and doc.get("amount") is not None:
        narrowed = [r for r in candidates if abs(r["total_cost"] - float(doc["amount"])) <= tolerance]
        candidates = narrowed or candidates
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, f"no reservation of supplier '{doc.get('supplier')}'"
    return None, f"supplier '{doc.get('supplier')}' has {len(candidates)} reservations: give the order id"


def _total(docs: list[dict[str, Any]]) -> float:
    return round(sum(float(d.get("amount") or 0) for d in docs), 2)


def _orders(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per supplier order. A voucher, invoice or payment belongs to the ORDER, and an order can hold several product rows
    (trip 435: Arbitrip is one order of six rows, ILS 12,043 in total, with one voucher of ILS 12,043), so costs are added per order."""
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["order_id"], []).append(r)
    orders = []
    for members in grouped.values():
        first = members[0]
        starts = [m["start"] for m in members if m["start"]]
        orders.append({**first, "total_cost": round(sum(m["total_cost"] for m in members), 2), "items": len(members), "start": min(starts) if starts else None,
                       "product": first["product"] if len(members) == 1 else f"{len(members)} items, first: {first['product']}"})
    return orders


def paperwork_check(v3: dict[str, Any], today: date, vouchers: list[dict[str, Any]] | None, invoices: list[dict[str, Any]] | None,
                    payments: list[dict[str, Any]] | None, tolerance: float = AMOUNT_TOLERANCE) -> dict[str, Any]:
    """A document kind passed as None was NOT read from the screen: it is reported as "not checked", never as "missing"."""
    not_checked = [name for name, docs in (("voucher", vouchers), ("supplier invoice", invoices), ("supplier payment", payments)) if docs is None]
    vouchers, invoices, payments = vouchers or [], invoices or [], payments or []
    base = reservations_summary(v3, today)
    rows = _orders(base["reservations"])
    found: dict[int, dict[str, list[dict[str, Any]]]] = {r["order_id"]: {"voucher": [], "invoice": [], "payment": []} for r in rows}
    unmatched: list[str] = []
    for kind, docs in (("voucher", vouchers), ("invoice", invoices), ("payment", payments)):
        for doc in docs:
            row, why = _match(doc, rows, tolerance)
            if row is None:
                unmatched.append(f"{kind} {doc.get('number') or ''} {doc.get('amount') or ''}: {why}".replace("  ", " ").strip())
            else:
                found[row["order_id"]][kind].append(doc)

    out_rows, complete, skipped = [], 0, 0
    for r in rows:
        f = found[r["order_id"]]
        flags: list[str] = []
        missing: list[str] = []
        cost, currency = r["total_cost"], r["currency"]

        def same_currency(docs: list[dict[str, Any]]) -> bool:
            return all(not d.get("currency") or d["currency"] == currency for d in docs)

        voucher_numbers = [d.get("number") for d in f["voucher"] if d.get("number")]
        if not f["voucher"] and "voucher" not in not_checked:
            missing.append("voucher")
            if r["status_api"] in ("VoucherSent", "VoucherPaid"):
                flags.append(f"status says {r['status']} but no voucher was found on the screen")
        invoice_amount = _total(f["invoice"]) if f["invoice"] else None
        if not f["invoice"]:
            if "supplier invoice" not in not_checked:
                missing.append("supplier invoice")
        elif not same_currency(f["invoice"]):
            flags.append(f"invoice is not in {currency}: amount not compared")
        elif abs(invoice_amount - cost) > tolerance:
            flags.append(f"invoice {invoice_amount} differs from the reservation cost {cost} ({round(invoice_amount - cost, 2)})")
        paid = _total(f["payment"]) if f["payment"] else None
        if not f["payment"]:
            if "supplier payment" not in not_checked:
                missing.append("supplier payment")
        elif not same_currency(f["payment"]):
            flags.append(f"payment is not in {currency}: amount not compared")
        else:
            expected = invoice_amount if invoice_amount is not None and same_currency(f["invoice"]) else cost
            if paid - expected > tolerance:
                flags.append(f"paid {paid} is MORE than {'the invoice' if expected == invoice_amount else 'the reservation cost'} {expected}")
            elif expected - paid > tolerance:
                flags.append(f"paid {paid} is LESS than {'the invoice' if expected == invoice_amount else 'the reservation cost'} {expected} (partial)")
        not_expected = r["status_api"] == "RejectedByTo" and not (f["voucher"] or f["invoice"] or f["payment"])
        if not_expected:        # rejected by the operator and replaced: no voucher, invoice or payment is expected
            missing, flags = [], []
        ok = not missing and not flags and not not_checked
        complete += ok and not not_expected
        skipped += not_expected
        out_rows.append({
            "order_id": r["order_id"], "supplier": r["supplier"], "product": r["product"], "items": r["items"], "start": r["start"], "status": r["status"],
            "reservation_cost": cost, "currency": currency,
            "voucher": {"found": None if "voucher" in not_checked else bool(f["voucher"]), "numbers": voucher_numbers},
            "supplier_invoice": {"found": None if "supplier invoice" in not_checked else bool(f["invoice"]), "amount": invoice_amount},
            "supplier_payment": {"found": None if "supplier payment" in not_checked else bool(f["payment"]), "paid": paid},
            "missing": missing, "flags": flags, "complete": ok and not not_expected, "documents_expected": not not_expected,
        })
    return {
        **({"NOT_CHECKED": f"You did not pass the {', '.join(not_checked)} of this trip, so nothing is known about them: they are NOT 'missing', "
                           "they were not looked at. Read them from the trip's MYT screens (quote_guide('reservations')) and call again, "
                           "or tell the operator they were not checked. Never report 'incomplete' or 'no voucher' from this answer."} if not_checked else {}),
        "rows": out_rows,
        "totals": {"reservations": len(rows), "orders": len(rows), "product_rows": len(base["reservations"]), "complete": None if not_checked else complete, "not_expected_rejected": skipped,
                   "incomplete": None if not_checked else len(rows) - complete - skipped},
        "documents_not_matched": unmatched,
        "tolerance": f"{tolerance} {rows[0]['currency'] if rows else ''}".strip(),
        "note": "'Missing' means not found among the documents you passed. Read them from this trip's MYT screens only; a payment can legitimately come after the service date.",
    }

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


def paperwork_check(v3: dict[str, Any], today: date, vouchers: list[dict[str, Any]], invoices: list[dict[str, Any]],
                    payments: list[dict[str, Any]], tolerance: float = AMOUNT_TOLERANCE) -> dict[str, Any]:
    base = reservations_summary(v3, today)
    rows = base["reservations"]
    found: dict[int, dict[str, list[dict[str, Any]]]] = {r["order_id"]: {"voucher": [], "invoice": [], "payment": []} for r in rows}
    unmatched: list[str] = []
    for kind, docs in (("voucher", vouchers), ("invoice", invoices), ("payment", payments)):
        for doc in docs:
            row, why = _match(doc, rows, tolerance)
            if row is None:
                unmatched.append(f"{kind} {doc.get('number') or ''} {doc.get('amount') or ''}: {why}".replace("  ", " ").strip())
            else:
                found[row["order_id"]][kind].append(doc)

    out_rows, complete = [], 0
    for r in rows:
        f = found[r["order_id"]]
        flags: list[str] = []
        missing: list[str] = []
        cost, currency = r["total_cost"], r["currency"]

        def same_currency(docs: list[dict[str, Any]]) -> bool:
            return all(not d.get("currency") or d["currency"] == currency for d in docs)

        voucher_numbers = [d.get("number") for d in f["voucher"] if d.get("number")]
        if not f["voucher"]:
            missing.append("voucher")
            if r["status_api"] == "VoucherSent":
                flags.append("status says Voucher Issued but no voucher was found on the screen")
        invoice_amount = _total(f["invoice"]) if f["invoice"] else None
        if not f["invoice"]:
            missing.append("supplier invoice")
        elif not same_currency(f["invoice"]):
            flags.append(f"invoice is not in {currency}: amount not compared")
        elif abs(invoice_amount - cost) > tolerance:
            flags.append(f"invoice {invoice_amount} differs from the reservation cost {cost} ({round(invoice_amount - cost, 2)})")
        paid = _total(f["payment"]) if f["payment"] else None
        if not f["payment"]:
            missing.append("supplier payment")
        elif not same_currency(f["payment"]):
            flags.append(f"payment is not in {currency}: amount not compared")
        else:
            expected = invoice_amount if invoice_amount is not None and same_currency(f["invoice"]) else cost
            if paid - expected > tolerance:
                flags.append(f"paid {paid} is MORE than {'the invoice' if expected == invoice_amount else 'the reservation cost'} {expected}")
            elif expected - paid > tolerance:
                flags.append(f"paid {paid} is LESS than {'the invoice' if expected == invoice_amount else 'the reservation cost'} {expected} (partial)")
        ok = not missing and not flags
        complete += ok
        out_rows.append({
            "order_id": r["order_id"], "supplier": r["supplier"], "product": r["product"], "start": r["start"], "status": r["status"],
            "reservation_cost": cost, "currency": currency,
            "voucher": {"found": bool(f["voucher"]), "numbers": voucher_numbers},
            "supplier_invoice": {"found": bool(f["invoice"]), "amount": invoice_amount},
            "supplier_payment": {"found": bool(f["payment"]), "paid": paid},
            "missing": missing, "flags": flags, "complete": ok,
        })
    return {
        "rows": out_rows,
        "totals": {"reservations": len(rows), "complete": complete, "incomplete": len(rows) - complete},
        "documents_not_matched": unmatched,
        "tolerance": f"{tolerance} {rows[0]['currency'] if rows else ''}".strip(),
        "note": "'Missing' means not found among the documents you passed. Read them from this trip's MYT screens only; a payment can legitimately come after the service date.",
    }

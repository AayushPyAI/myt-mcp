"""Supplier reservations, voucher status and reconciliation from MYT's GetTrip/v3 payload.

Only what the public API carries: the reservations (supplier, product, quantity, price, dates) and each supplier
order's status. Voucher numbers, supplier invoices and payments are NOT in the API; they are read from the MYT screens.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from myt_mcp.myt.summaries import _amount, _date, quotation_summary

# API status name -> the name MYT's Supplier Reservations screen shows (seen on the test trip; others pass through unchanged).
STATUS_ON_SCREEN = {"NotSent": "Ready To Send", "VoucherSent": "Voucher Issued", "ConfirmedByTo": "Reservation Confirmed",
                    "VoucherPaid": "Voucher Paid", "VoucherInPayment": "Voucher In Payment Process", "RejectedByTo": "Rejected By Operator"}
DEFAULT_PROFIT_PCTS = (3.0, 13.0, 15.0)     # contract rate, default and usual line profit (to be confirmed by the client)
RATIO_TOLERANCE = 0.005
NOT_IN_API = ("Voucher numbers, supplier invoices, supplier payments and customer invoices are not in MYT's API. Read them from the "
              "trip's own MYT screens (quote_guide('reservations')); never from the account-wide Reports pages.")


def _iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _key(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _same_product(a: str | None, b: str | None) -> bool:
    ka, kb = _key(a), _key(b)
    return bool(ka and kb) and (ka in kb or kb in ka)


NEXT_STEP = {
    "NotSent": "Confirm it (row menu > Skip To COR) or issue the voucher (Skip To Voucher & Download). Never Send Request: it emails the supplier.",
    None: "Confirm it (row menu > Skip To COR) or issue the voucher (Skip To Voucher & Download). Never Send Request: it emails the supplier.",
    "ConfirmedByTo": "Voucher not issued yet (by status). Issue it (Print Voucher on the row menu: not tested yet), then check the supplier invoice and the payment on the MYT screens: the API cannot show whether they exist.",
    "VoucherPaid": "Voucher paid (by status). Check on the PAYMENTS tab that the payment amount and supplier match this reservation.",
    "VoucherInPayment": "Payment is in process (by status). Check the PAYMENTS tab for the payment and its date; mark nothing yourself.",
    "RejectedByTo": "Rejected by the operator (by status): no voucher is expected. If the service is still in the future, ask the operator whether to re-request or replace it.",
    "VoucherSent": "Voucher issued (by status). Check the supplier invoice (Create/Edit Invoice) and the PAYMENTS tab on the MYT screen: the API cannot show them. Mark paid only after the operator confirms the payment.",
}
URGENCY_ORDER = {"overdue": 0, "today": 1, "soon": 2, "later": 3, "done": 4}


def _urgency(api_status: str | None, days: int | None, soon_days: int) -> str:
    """How pressing the reservation is: a service that has started or starts today without a voucher comes first."""
    if api_status in ("VoucherSent", "VoucherPaid"):
        return "done"
    if api_status == "RejectedByTo" and (days is None or days < 0):
        return "done"           # rejected and the service date has passed: nothing is expected any more
    if days is None:
        return "later"
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    return "soon" if days <= soon_days else "later"


def reservations_summary(v3: dict[str, Any], today: date, soon_days: int = 7) -> dict[str, Any]:
    """One row per supplier reservation, with the supplier order's status and the amounts as the MYT screen shows them."""
    orders = {o.get("order_id"): o for o in v3.get("order_documents") or []}
    rows, flags = [], []
    for r in v3.get("reservations") or []:
        unit = _amount(r.get("price")) or 0.0
        qty, duration = r.get("quantity") or 1, r.get("duration") or 1
        start = _date((r.get("dates") or {}).get("start"))
        end = _date((r.get("dates") or {}).get("end"))
        api_status = ((orders.get(r.get("order_id")) or {}).get("status") or {}).get("name")
        row = {
            "order_id": r.get("order_id"),
            "reservation_id": r.get("reservation_id"),
            "supplier": r.get("supplier_name"),
            "supplier_id": r.get("supplier_id"),
            "product": r.get("product_name"),
            "start": start,
            "end": end,
            "quantity": qty,
            "duration": duration,
            "unit_cost": unit,
            "total_cost": round(unit * qty * duration, 2),     # what the MYT screen shows for the order
            "currency": (r.get("currency") or {}).get("name"),
            "status": STATUS_ON_SCREEN.get(api_status, api_status),
            "status_api": api_status,
        }
        days = (_iso(start) - today).days if _iso(start) else None
        row["service_in_days"] = days
        row["urgency"] = _urgency(api_status, days, soon_days)
        row["next_step"] = NEXT_STEP.get(api_status, "Read the row on the MYT screen: this status is not one of the six seen so far.")
        rows.append(row)
        if api_status in (None, "NotSent") and days is not None and days <= soon_days:
            when = f"starts in {days} day(s)" if days >= 0 else f"started {-days} day(s) ago"
            flags.append(f"{row['supplier']} / {row['product']} (order {row['order_id']}): status '{row['status']}' but the service {when}.")
    rows.sort(key=lambda x: (x["start"] or "", x["order_id"] or 0))
    by_status: dict[str, int] = {}
    for row in rows:
        by_status[row["status"] or "unknown"] = by_status.get(row["status"] or "unknown", 0) + 1
    totals: dict[str, float] = {}
    for row in rows:        # never add EUR and ILS together: one total per currency
        totals[row["currency"] or "?"] = round(totals.get(row["currency"] or "?", 0.0) + row["total_cost"], 2)
    return {
        "reservations": rows,
        "count": len(rows),
        "orders": len({r["order_id"] for r in rows}),
        "total_cost": next(iter(totals.values())) if len(totals) == 1 else (0.0 if not totals else None),
        "total_cost_by_currency": totals,
        "by_status": by_status,
        "voucher_flags": flags,
        "worklist": [
            {"order_id": r["order_id"], "supplier": r["supplier"], "product": r["product"], "start": r["start"], "status": r["status"],
             "urgency": r["urgency"], "service_in_days": r["service_in_days"], "next_step": r["next_step"]}
            for r in sorted(rows, key=lambda x: (URGENCY_ORDER[x["urgency"]], x["start"] or "", x["order_id"] or 0)) if r["urgency"] != "done"
        ],
        "status_names": "status is the name MYT's screen shows; status_api is the API's own name. Seen so far: Ready To Send, Voucher Issued, Reservation Confirmed, Voucher Paid, Voucher In Payment Process, Rejected By Operator. count is the number of product rows; orders is the number of supplier orders.",
        "not_in_api": NOT_IN_API,
    }


def _quote_lines(v3: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    quote = quotation_summary(v3)
    if not quote:
        return [], None
    lines = [{**line, "package": pkg["package"]} for pkg in quote["packages"] for line in pkg["lines"]]
    return lines, f"{quote['number']} (version {quote['version']}, {quote['status']})"


def _line_total(line: dict[str, Any]) -> float | None:
    if line.get("total_with_profit") is not None:
        return float(line["total_with_profit"])
    unit = line.get("unit_price_with_profit")
    return round(unit * (line.get("qty") or 1) * (line.get("nights") or 1), 2) if unit is not None else None


def _candidates(res: dict[str, Any], lines: list[dict[str, Any]], used: set[int]) -> tuple[int, dict[str, Any]] | None:
    """The quote line this reservation belongs to: same supplier, then the one whose product name matches."""
    same_supplier = [(i, ln) for i, ln in enumerate(lines)
                     if i not in used and (ln.get("supplier_id") == res["supplier_id"] or _key(ln.get("supplier")) == _key(res["supplier"]))]
    by_name = [(i, ln) for i, ln in same_supplier if _same_product(ln.get("product"), res["product"])]
    if by_name:
        return by_name[0]
    return same_supplier[0] if len(same_supplier) == 1 else None


def reconcile(v3: dict[str, Any], today: date, soon_days: int = 7, profit_pcts: tuple[float, ...] = DEFAULT_PROFIT_PCTS) -> dict[str, Any]:
    """Each supplier reservation against its quote line: the quote line price is cost plus the line profit, so the ratio
    line total / reservation total should be 1 + one of the usual profit percentages."""
    summary = reservations_summary(v3, today, soon_days)
    lines, quote_label = _quote_lines(v3)
    expected = [1 + p / 100 for p in profit_pcts]
    used: set[int] = set()
    rows, without_line = [], []
    for res in summary["reservations"]:
        found = _candidates(res, lines, used)
        if not found:
            without_line.append(f"{res['supplier']} / {res['product']} (order {res['order_id']}, {res['total_cost']} {res['currency'] or ''})".strip())
            continue
        index, line = found
        used.add(index)
        quote_total, notes = _line_total(line), []
        ratio = round(quote_total / res["total_cost"], 4) if quote_total and res["total_cost"] else None
        if ratio is None:
            verdict = "cannot compare"
        elif any(abs(ratio - e) / e <= RATIO_TOLERANCE for e in expected):
            verdict = "ok"
        else:
            verdict = "MISMATCH"
            notes.append(f"line total {quote_total} is {ratio}x the reservation cost {res['total_cost']}; implied profit {round((ratio - 1) * 100, 1)}%")
        if line.get("date") and res["start"] and line["date"] != res["start"]:
            notes.append(f"date differs: reservation {res['start']}, quote line {line['date']}")
            verdict = "MISMATCH"
        rows.append({
            "order_id": res["order_id"], "supplier": res["supplier"], "product": res["product"], "status": res["status"],
            "reservation_cost": res["total_cost"], "quote_line": line.get("product"), "quote_line_total": quote_total,
            "ratio": ratio, "implied_profit_pct": round((ratio - 1) * 100, 1) if ratio else None, "verdict": verdict, "notes": notes,
        })
    lines_without_reservation = [f"{ln.get('supplier')} / {ln.get('product')} ({ln.get('package')})" for i, ln in enumerate(lines) if i not in used]
    bad = sum(1 for r in rows if r["verdict"] != "ok")
    return {
        "quotation": quote_label,
        "profit_pcts_accepted": list(profit_pcts),
        "profit_note": "A line is 'ok' when its total is the reservation cost plus 3%, 13% or 15% (assumed from the client's rules; confirm with the client).",
        "rows": rows,
        "reservations_without_quote_line": without_line,
        "quote_lines_without_reservation": lines_without_reservation,
        "voucher_flags": summary["voucher_flags"],
        "by_status": summary["by_status"],
        "totals": {"reservations_cost": summary["total_cost"], "rows_ok": len(rows) - bad, "rows_to_check": bad},
        "not_in_api": NOT_IN_API,
    }


def customer_invoices(v3: dict[str, Any]) -> dict[str, Any]:
    """The customer's invoices of a trip as the API carries them (pro forma or tax invoice): number, total, dates and the payment schedule.
    The API gives no paid status and no currency: both are on the MYT screen (Reports > Balance by trip > Customer invoice)."""
    rows = []
    for inv in v3.get("invoices") or []:
        total = _amount(inv.get("total"))
        installments = [{"date": _date(i.get("date")) if isinstance(i.get("date"), dict) else i.get("date"), "amount": float(str(i.get("amount") or 0).replace(",", ""))}
                        for i in inv.get("installments") or []]
        scheduled = round(sum(i["amount"] for i in installments), 2)
        rows.append({
            "invoice_number": inv.get("invoice_number"), "invoice_id": inv.get("invoice_id"),
            "type": "pro forma" if inv.get("is_proforma") else "invoice", "description": inv.get("description") or None,
            "total": total, "document_date": _date(inv.get("document_date")), "payable_until": _date(inv.get("payable_until")),
            "installments": installments, "installments_total": scheduled if installments else None,
            "installments_match_total": (abs(scheduled - float(total)) <= 0.01) if installments and total is not None else None,
        })
    return {
        "invoices": rows, "count": len(rows),
        "total_of_invoices": round(sum(float(r["total"] or 0) for r in rows), 2),
        "not_in_api": "Paid status, the currency and receipts are not in the API. Read them on the MYT screen: Reports > Balance by trip > Customer invoice (trip filtered).",
    }

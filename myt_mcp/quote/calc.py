"""Reproduces MYT's quotation pricing so Claude can preview a quote before writing it.

Derived from the client's quotation 352280 (MARGING PRICES tab) and checked to
the cent on Transport, Lodging, Attraction and Other:

    line net (group)  = unit_price * qty * days * (pax + free if PP else 1)
    line gross        = line net * (1 + profit%) * (1 + vat%)
    category gross    = sum(line gross) * (1 + conversion%)
                        + fixed markup per person * (1 + conversion%) * paying pax
    per person        = group amount / paying pax
    publish price pp  = floor(gross pp)

Unverified assumptions: how VAT is applied (it was 0 on every line we saw), how
free participants split the cost, and the rounding rule for the publish price.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["Transport", "Food", "Staff", "Lodging", "Attraction", "Other", "DMC"]
CATEGORIES: tuple[str, ...] = ("Transport", "Food", "Staff", "Lodging", "Attraction", "Other", "DMC")


class CostLine(BaseModel):
    """One row in the MYT quotation COST tab."""

    category: Category = Field(description="Quote section: Transport (flights, cars, transfers), Lodging (hotels), Attraction (tours), Staff, Food, Other, DMC")
    supplier: str = Field(description="Supplier name as saved in MYT, e.g. 'Sixt', 'RateHawk', 'Azore Airlines'")
    product_name: str = Field(description="e.g. 'Peugeot E-2008 (Lisbon)' or 'LIS-TER-PDL-OPO'")
    pricing: Literal["PP", "PS"] = Field(description="PP = price per person, PS = price per service/group")
    unit_price: float = Field(ge=0, le=10_000_000, description="Net cost per unit, before profit")
    qty: float = Field(default=1, gt=0)
    days: float = Field(default=1, gt=0, description="Leave 1 when unit_price already covers the whole rental/stay")
    currency: str = "EUR"
    profit_pct: float = Field(default=13, description="Profit per unit in %, MYT default is 13")
    vat_pct: float = 0
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    line_type: Literal["Day", "Ride"] | None = Field(default=None, description="MYT 'Category' column")
    transport_type: Literal["Car", "Flight", "Bus", "Train", "Boat"] | None = None
    seats: int | None = None


class CategoryTotal(BaseModel):
    net_pp: float
    margin_pp: float
    gross_pp: float


class LinePrice(BaseModel):
    """What one line should look like in MYT after it is added."""

    product: str
    pricing: str
    net_group: float
    with_profit_group: float
    myt_price_column: float = Field(description="The 'Price' column of the COST tab: unit x qty x days with profit, per person for PP lines (not yet multiplied by travellers). Unverified until the first line is written.")


class QuoteTotals(BaseModel):
    lines: list[LinePrice]
    paying_pax: int
    free_pax: int
    currency: str
    categories: dict[str, CategoryTotal]
    net_pp: float
    net_pg: float
    margin_pp: float
    margin_pct: float
    gross_pp: float
    gross_pg: float
    publish_pp: int
    publish_pg: int
    notes: list[str] = Field(default_factory=list, description="Assumptions Claude must repeat to the operator")


def _money(x: float) -> float:
    """Round half-up to cents like MYT (Python's round() would turn 229.395 into 229.39)."""
    return math.floor(x * 100 + 0.5 + 1e-9) / 100


def line_net_group(line: CostLine, paying_pax: int, free_pax: int = 0) -> float:
    units = paying_pax + free_pax if line.pricing == "PP" else 1
    return line.unit_price * line.qty * line.days * units


def calculate(
    lines: list[CostLine],
    paying_pax: int,
    free_pax: int = 0,
    conversion_pct: float = 5,
    fixed_markups_pp: dict[str, float] | None = None,
    percent_markups: dict[str, float] | None = None,
) -> QuoteTotals:
    if paying_pax <= 0:
        raise ValueError("paying_pax must be at least 1")
    percent = percent_markups or {}
    unknown = sorted(set(percent) - set(CATEGORIES) - {"General"})
    if unknown:
        raise ValueError(f"Unknown markup category {unknown}; use {list(CATEGORIES)} or 'General'")
    currencies = {line.currency for line in lines}
    if len(currencies) > 1:
        raise ValueError(f"Lines use several currencies {sorted(currencies)}; convert them first")
    conv = 1 + conversion_pct / 100
    markups = fixed_markups_pp or {}

    categories: dict[str, CategoryTotal] = {}
    for cat in CATEGORIES:
        cat_lines = [line for line in lines if line.category == cat]
        net = sum(line_net_group(line, paying_pax, free_pax) for line in cat_lines)
        markup = 1 + (percent.get(cat, 0) + percent.get("General", 0)) / 100
        # % markup multiplies the category total AFTER the line profits (verified on MYT, trip 906 / V3, 2026-10-14:
        # Transport 98.19 with a 10% markup became 108.01). Whether it comes before or after the conversion
        # difference is not verified; it is applied before.
        gross = sum(
            line_net_group(line, paying_pax, free_pax) * (1 + line.profit_pct / 100) * (1 + line.vat_pct / 100)
            for line in cat_lines
        ) * markup * conv
        gross += markups.get(cat, 0) * conv * paying_pax
        if net == 0 and gross == 0:
            continue
        net_pp, gross_pp = _money(net / paying_pax), _money(gross / paying_pax)
        categories[cat] = CategoryTotal(net_pp=net_pp, margin_pp=_money(gross_pp - net_pp), gross_pp=gross_pp)

    net_pp = sum(c.net_pp for c in categories.values())
    gross_pp = sum(c.gross_pp for c in categories.values())
    publish_pp = math.floor(gross_pp)
    line_prices = [
        LinePrice(
            product=line.product_name, pricing=line.pricing,
            net_group=_money(line_net_group(line, paying_pax, free_pax)),
            with_profit_group=_money(line_net_group(line, paying_pax, free_pax) * (1 + line.profit_pct / 100) * (1 + line.vat_pct / 100)),
            myt_price_column=_money(line.unit_price * line.qty * line.days * (1 + line.profit_pct / 100) * (1 + line.vat_pct / 100)),
        )
        for line in lines
    ]
    notes = []
    if percent:
        notes.append("% markup = category total after line profits x (1 + markup %) (checked once on MYT). Its order relative to the "
                     "Conversion difference is not checked, so after entering it compare MYT's Gross PG with gross_pg; "
                     "if they differ by more than EUR 1, stop and tell the operator.")
    if conversion_pct:
        notes.append(f"Conversion difference {conversion_pct}% is included. MYT only applies it when that item is on the Margin Prices tab "
                     "(Quotation Management); if it is not there (trip 906 / V3 has none), call again with conversion_pct=0.")
    return QuoteTotals(
        lines=line_prices,
        paying_pax=paying_pax,
        free_pax=free_pax,
        currency=next(iter(currencies), "EUR"),
        categories=categories,
        net_pp=_money(net_pp),
        net_pg=_money(sum(line_net_group(l, paying_pax, free_pax) for l in lines)),
        margin_pp=_money(gross_pp - net_pp),
        margin_pct=_money((gross_pp - net_pp) / net_pp * 100) if net_pp else 0.0,
        gross_pp=_money(gross_pp),
        gross_pg=_money(gross_pp * paying_pax),
        publish_pp=publish_pp,
        publish_pg=publish_pp * paying_pax,
        notes=notes,
    )

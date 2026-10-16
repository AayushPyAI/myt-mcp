"""Compare two versions of a quotation: what was added, removed or changed, and what it did to the price.

Both sides use the cost-line shape that `get_quotation` returns (prices already include the line profit), so the
selected version can be passed as it is. The other version is read by Claude in the MYT website (read-only).
The result is deterministic: Claude explains the difference only from `changes`, never from memory.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from myt_mcp.quote.calc import CATEGORIES

CATEGORY_ALIASES = {"Transportation": "Transport", "Accommodation": "Lodging", "Attractions": "Attraction"}


class CompareLine(BaseModel):
    """One cost line of a quotation, with prices including the line profit."""

    category: str = Field(description="As MYT shows it: Transportation, Food, Lodging, Attraction, Staff, Other, DMC")
    supplier: str
    product: str = Field(description="Product name exactly as in MYT")
    pricing: Literal["PP", "PS"]
    date: str | None = Field(default=None, description="YYYY-MM-DD")
    qty: float = Field(default=1, description="For a line copied from get_quotation, pass its qty as is")
    nights: float = Field(default=1, description="MYT 'Days' / nights")
    unit_price_with_profit: float = Field(ge=0, description="Price per unit including the line profit")
    unit_price_net: float | None = Field(default=None, description="'Price Per Unit' on the COST tab: the supplier's price before profit")
    profit_pct: float | None = Field(default=None, description="'Profit Per Unit' % on the COST tab")
    total_with_profit: float | None = Field(
        default=None,
        description="Group total of the line. Pass it when you have it (get_quotation gives it). Leave it out for a "
        "line read on the MYT cost tab: the tool then calculates PS = unit x qty x nights, PP = unit x qty x nights x travellers.",
    )


class MarginCategory(BaseModel):
    net_pp: float | None = None
    margin_pp: float | None = None
    gross_pp: float | None = None
    markup_pct: float | None = Field(default=None, description="Markup % of this category on the Margin Prices tab")


class MarginTab(BaseModel):
    """The MARGIN PRICES tab of one version: the table and the totals MYT shows (leave out what you cannot read)."""

    categories: dict[str, MarginCategory] = Field(default_factory=dict, description="Lodging, Food, Transport, Attraction, Other, ...")
    conversion_pct: float | None = Field(default=None, description="'Conversion differences' %")
    net_pp: float | None = None
    margin_pp: float | None = None
    gross_pp: float | None = None
    net_pg: float | None = None
    margin_pg: float | None = None
    gross_pg: float | None = None
    publish_pp: float | None = Field(default=None, description="Price to publish per person")
    publish_pg: float | None = Field(default=None, description="Price to publish for the group")


class QuoteSnapshot(BaseModel):
    label: str = Field(description='e.g. "352-1 (V1)"')
    paying_pax: int = Field(ge=1)
    free_pax: int = 0
    lines: list[CompareLine]
    selling_price_pp: float | None = Field(default=None, description="MYT's price per person, if MYT shows one")
    selling_price_group: float | None = None
    markup: dict[str, float] | None = Field(default=None, description="Markup % per category from the Margin Prices tab, if read (or put it in margin.categories)")
    margin: MarginTab | None = Field(default=None, description="The Margin Prices tab of this version, if read")


class LineChange(BaseModel):
    kind: Literal["added", "removed", "changed"]
    category: str
    supplier: str
    product: str
    what: str
    before_total: float | None = None
    after_total: float | None = None
    effect: float
    profit_before_pct: float | None = None
    profit_after_pct: float | None = None
    margin_before: float | None = Field(default=None, description="Line profit in EUR for the group: total with profit minus net, when the net price was given")
    margin_after: float | None = None


class CategoryDiff(BaseModel):
    category: str
    before: float
    after: float
    effect: float


class Delta(BaseModel):
    before: float | None
    after: float | None
    effect: float | None


class QuoteComparison(BaseModel):
    before: str
    after: str
    currency_note: str
    lines_before: int
    lines_after: int
    subtotal_before: float
    subtotal_after: float
    subtotal_effect: float
    subtotal_effect_pct: float | None
    travellers_before: int
    travellers_after: int
    selling_price: dict[str, float | None]
    markup_changes: list[str]
    margin_summary: dict[str, Delta]
    margin_by_category: dict[str, dict[str, Delta]]
    price_bridge: str | None
    categories: list[CategoryDiff]
    changes: list[LineChange]
    notes: list[str]


def _cat(name: str) -> str:
    c = CATEGORY_ALIASES.get(name.strip(), name.strip())
    return c if c in CATEGORIES else name.strip()


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _total(line: CompareLine, pax: int) -> float:
    if line.total_with_profit is not None:
        return round(line.total_with_profit, 2)
    mult = line.qty * line.nights * (pax if line.pricing == "PP" else 1)
    return round(line.unit_price_with_profit * mult, 2)


def _key(line: CompareLine, with_date: bool) -> tuple:
    return (_cat(line.category), _norm(line.supplier), _norm(line.product)) + ((line.date,) if with_date else ())


def _match(before: list, after: list) -> tuple[list[tuple], list, list]:
    """Pairs lines by category+supplier+product+date, then by category+supplier+product (a moved date)."""
    pairs: list[tuple] = []
    left_b, left_a = list(before), list(after)
    for with_date in (True, False):
        rest_a = list(left_a)
        rest_b = []
        for b in left_b:
            hit = next((a for a in rest_a if _key(a[0], with_date) == _key(b[0], with_date)), None)
            if hit is None:
                rest_b.append(b)
            else:
                rest_a.remove(hit)
                pairs.append((b, hit))
        left_b, left_a = rest_b, rest_a
    return pairs, left_b, left_a


def _net_group(line: CompareLine, pax: int) -> float | None:
    """The line's supplier cost for the group, when the net unit price was read."""
    if line.unit_price_net is None:
        return None
    per_person_in_qty = line.pricing == "PP" and line.total_with_profit is not None   # a get_quotation line: qty already holds the travellers
    mult = line.qty * line.nights * (pax if line.pricing == "PP" and not per_person_in_qty else 1)
    return round(line.unit_price_net * mult, 2)


def _margin(line: CompareLine, total: float, pax: int) -> float | None:
    net = _net_group(line, pax)
    return None if net is None else round(total - net, 2)


def _diff_fields(b: CompareLine, a: CompareLine, bt: float, at: float) -> list[str]:
    out = []
    if b.date != a.date:
        out.append(f"date {b.date} -> {a.date}")
    if b.pricing != a.pricing:
        out.append(f"{b.pricing} -> {a.pricing}")
    if b.unit_price_net is not None and a.unit_price_net is not None and b.unit_price_net != a.unit_price_net:
        out.append(f"supplier price {b.unit_price_net:g} -> {a.unit_price_net:g}")
    if b.profit_pct is not None and a.profit_pct is not None and b.profit_pct != a.profit_pct:
        out.append(f"profit {b.profit_pct:g}% -> {a.profit_pct:g}%")
    if b.unit_price_with_profit != a.unit_price_with_profit:
        out.append(f"price with profit {b.unit_price_with_profit:g} -> {a.unit_price_with_profit:g}")
    if b.qty != a.qty and b.total_with_profit is None and a.total_with_profit is None:
        out.append(f"qty {b.qty:g} -> {a.qty:g}")
    if b.nights != a.nights:
        out.append(f"nights/days {b.nights:g} -> {a.nights:g}")
    if not out and bt != at:
        out.append(f"total {bt:g} -> {at:g}")
    return out


TOTAL_FIELDS = ("net_pp", "margin_pp", "gross_pp", "net_pg", "margin_pg", "gross_pg", "publish_pp", "publish_pg", "conversion_pct")


def _delta(b: float | None, a: float | None) -> Delta:
    return Delta(before=b, after=a, effect=round(a - b, 2) if a is not None and b is not None else None)


def _margin_pct(m: MarginTab | None) -> float | None:
    return round(m.margin_pp / m.net_pp * 100, 2) if m and m.net_pp and m.margin_pp is not None else None


def _margin_comparison(before: QuoteSnapshot, after: QuoteSnapshot) -> tuple[dict[str, Delta], dict[str, dict[str, Delta]], str | None, list[str]]:
    mb, ma = before.margin, after.margin
    if mb is None or ma is None:
        return {}, {}, None, []
    summary = {f: _delta(getattr(mb, f), getattr(ma, f)) for f in TOTAL_FIELDS}
    summary["margin_pct"] = _delta(_margin_pct(mb), _margin_pct(ma))
    summary = {k: v for k, v in summary.items() if v.before is not None or v.after is not None}

    by_cat: dict[str, dict[str, Delta]] = {}
    markups: list[str] = []
    for cat in sorted(set(mb.categories) | set(ma.categories)):
        cb, ca = mb.categories.get(cat, MarginCategory()), ma.categories.get(cat, MarginCategory())
        row = {f: _delta(getattr(cb, f), getattr(ca, f)) for f in ("net_pp", "margin_pp", "gross_pp", "markup_pct")}
        row = {k: v for k, v in row.items() if (v.before is not None or v.after is not None)}
        if any(v.effect != 0 for v in row.values()):
            by_cat[cat] = row
        if cb.markup_pct != ca.markup_pct and (cb.markup_pct is not None or ca.markup_pct is not None):
            markups.append(f"{cat} markup {cb.markup_pct if cb.markup_pct is not None else 'not set'}% -> {ca.markup_pct if ca.markup_pct is not None else 'not set'}%")
    if mb.conversion_pct != ma.conversion_pct and (mb.conversion_pct is not None or ma.conversion_pct is not None):
        markups.append(f"conversion difference {mb.conversion_pct}% -> {ma.conversion_pct}%")

    bridge = None
    d_gross, d_net, d_margin = summary.get("gross_pg"), summary.get("net_pg"), summary.get("margin_pg")
    if d_gross and d_net and d_margin and None not in (d_gross.effect, d_net.effect, d_margin.effect):
        gap = round(d_gross.effect - d_net.effect - d_margin.effect, 2)
        bridge = (f"Selling price for the group (gross) {d_gross.before} -> {d_gross.after} ({d_gross.effect:+g}): "
                  f"supplier costs {d_net.effect:+g} and our margin {d_margin.effect:+g}"
                  + (f"; {gap:+g} is not explained by these two (rounding or something MYT adds)." if abs(gap) >= 1 else "."))
    return summary, by_cat, bridge, markups


def compare(before: QuoteSnapshot, after: QuoteSnapshot) -> QuoteComparison:
    pax_b, pax_a = before.paying_pax + before.free_pax, after.paying_pax + after.free_pax
    lb = [(line, _total(line, pax_b)) for line in before.lines]
    la = [(line, _total(line, pax_a)) for line in after.lines]
    pairs, only_b, only_a = _match(lb, la)

    changes: list[LineChange] = []
    for (b, bt), (a, at) in pairs:
        what = _diff_fields(b, a, bt, at)
        if what or bt != at:
            changes.append(LineChange(kind="changed", category=_cat(a.category), supplier=a.supplier, product=a.product,
                                      what="; ".join(what) or "total changed", before_total=bt, after_total=at,
                                      effect=round(at - bt, 2), profit_before_pct=b.profit_pct, profit_after_pct=a.profit_pct,
                                      margin_before=_margin(b, bt, pax_b), margin_after=_margin(a, at, pax_a)))
    for b, bt in only_b:
        changes.append(LineChange(kind="removed", category=_cat(b.category), supplier=b.supplier, product=b.product,
                                  what=f"only in {before.label}", before_total=bt, effect=round(-bt, 2),
                                  profit_before_pct=b.profit_pct, margin_before=_margin(b, bt, pax_b)))
    for a, at in only_a:
        changes.append(LineChange(kind="added", category=_cat(a.category), supplier=a.supplier, product=a.product,
                                  what=f"only in {after.label}", after_total=at, effect=round(at, 2),
                                  profit_after_pct=a.profit_pct, margin_after=_margin(a, at, pax_a)))
    changes.sort(key=lambda c: abs(c.effect), reverse=True)

    cats: dict[str, list[float]] = {}
    for line, t in lb:
        cats.setdefault(_cat(line.category), [0.0, 0.0])[0] += t
    for line, t in la:
        cats.setdefault(_cat(line.category), [0.0, 0.0])[1] += t
    categories = [CategoryDiff(category=c, before=round(v[0], 2), after=round(v[1], 2), effect=round(v[1] - v[0], 2))
                  for c, v in cats.items() if round(v[1] - v[0], 2) != 0]
    categories.sort(key=lambda c: abs(c.effect), reverse=True)

    sb, sa = round(sum(t for _, t in lb), 2), round(sum(t for _, t in la), 2)
    margin_summary, margin_by_category, bridge, margin_markups = _margin_comparison(before, after)
    markup_changes: list[str] = list(margin_markups)
    if before.markup is not None and after.markup is not None:
        for k in sorted(set(before.markup) | set(after.markup)):
            if before.markup.get(k, 0) != after.markup.get(k, 0):
                markup_changes.append(f"{k} markup {before.markup.get(k, 0):g}% -> {after.markup.get(k, 0):g}%")

    notes = ["Line totals include the line profit. They are before MYT's conversion difference and fixed markups (see margin_summary when the Margin Prices tab was given)."]
    if pax_b != pax_a:
        notes.append(f"The number of travellers differs ({pax_b} vs {pax_a}): PP lines change with it.")
    if before.margin is None or after.margin is None:
        notes.append("The Margin Prices tab was not given for both versions, so changes in markups, margin and the selling price are NOT known: "
                     "read that tab of both versions and call compare_quotes again.")
    if any(line.profit_pct is None or line.unit_price_net is None for line in before.lines + after.lines):
        notes.append("Some lines have no supplier price or profit %, so their profit change cannot be shown (the API does not give it; read the COST tab).")
    if before.selling_price_group is None or after.selling_price_group is None:
        if before.margin is None or after.margin is None or before.margin.gross_pg is None or after.margin.gross_pg is None:
            notes.append("MYT shows no selling price for one or both versions (typical for a Draft): only the cost side is compared.")

    return QuoteComparison(
        before=before.label, after=after.label, currency_note="EUR, as in the lines you passed",
        lines_before=len(lb), lines_after=len(la), subtotal_before=sb, subtotal_after=sa,
        subtotal_effect=round(sa - sb, 2), subtotal_effect_pct=round((sa - sb) / sb * 100, 1) if sb else None,
        travellers_before=pax_b, travellers_after=pax_a,
        selling_price={
            "before_pp": before.selling_price_pp, "after_pp": after.selling_price_pp,
            "before_group": before.selling_price_group, "after_group": after.selling_price_group,
        },
        markup_changes=markup_changes, margin_summary=margin_summary, margin_by_category=margin_by_category, price_bridge=bridge,
        categories=categories, changes=changes, notes=notes,
    )

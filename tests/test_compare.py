import pytest

from myt_mcp.quote.compare import CompareLine, QuoteSnapshot, compare


def line(category, product, pricing="PS", unit=100.0, qty=1.0, nights=1.0, date="2026-10-15", total=None, supplier="S"):
    return CompareLine(category=category, supplier=supplier, product=product, pricing=pricing, date=date, qty=qty,
                       nights=nights, unit_price_with_profit=unit, total_with_profit=total)


def snap(label, lines, pax=2, **kw):
    return QuoteSnapshot(label=label, paying_pax=pax, lines=lines, **kw)


def test_added_removed_changed_and_effects():
    v1 = snap("352-1", [line("Lodging", "Hotel A", nights=2, unit=100), line("Food", "Dinner", "PP", unit=50),
                        line("Transportation", "Car", unit=300)])
    v2 = snap("352-2", [line("Lodging", "Hotel A", nights=3, unit=100), line("Food", "Dinner", "PP", unit=50),
                        line("Attraction", "Tour", unit=80)])
    r = compare(v1, v2)
    kinds = {(c.kind, c.product): c.effect for c in r.changes}
    assert kinds == {("changed", "Hotel A"): 100.0, ("removed", "Car"): -300.0, ("added", "Tour"): 80.0}
    assert r.subtotal_before == 200 + 100 + 300 and r.subtotal_after == 300 + 100 + 80
    assert r.subtotal_effect == -120.0 and r.subtotal_effect_pct == -20.0
    assert [c.category for c in r.categories][0] == "Transport"   # biggest effect first, Transportation alias


def test_pp_line_uses_travellers_and_given_total_wins():
    r = compare(snap("a", [line("Food", "X", "PP", unit=10)], pax=3), snap("b", [line("Food", "X", "PP", unit=10, total=99.0)], pax=3))
    assert r.subtotal_before == 30.0 and r.subtotal_after == 99.0
    assert r.changes[0].effect == 69.0


def test_date_change_is_one_changed_line_not_add_plus_remove():
    r = compare(snap("a", [line("Food", "Dinner", date="2026-10-18")]), snap("b", [line("Food", "Dinner", date="2026-10-19")]))
    assert len(r.changes) == 1 and r.changes[0].kind == "changed" and "date" in r.changes[0].what and r.changes[0].effect == 0


def test_identical_versions_have_no_changes():
    ls = [line("Lodging", "Hotel", nights=2)]
    r = compare(snap("a", ls), snap("b", ls))
    assert r.changes == [] and r.subtotal_effect == 0 and r.categories == []


def test_traveller_and_markup_notes():
    r = compare(snap("a", [line("Food", "X", "PP")], pax=2, markup={"Other": 10}), snap("b", [line("Food", "X", "PP")], pax=3, markup={"Other": 15}))
    assert r.markup_changes == ["Other markup 10% -> 15%"]
    assert any("travellers differs" in n for n in r.notes)
    assert r.subtotal_after == 300.0


def test_missing_markup_and_price_are_flagged():
    r = compare(snap("a", [line("Food", "X")]), snap("b", [line("Food", "X")]))
    assert any("Margin Prices tab was not given" in n for n in r.notes) and any("no selling price" in n for n in r.notes)


def test_line_profit_change_with_net_prices():
    b = line("Transportation", "Car", unit=113.0)
    b.unit_price_net, b.profit_pct = 100.0, 13.0
    a = line("Transportation", "Car", unit=115.0)
    a.unit_price_net, a.profit_pct = 100.0, 15.0
    r = compare(snap("v1", [b]), snap("v2", [a]))
    c = r.changes[0]
    assert "profit 13% -> 15%" in c.what and c.effect == 2.0
    assert (c.margin_before, c.margin_after) == (13.0, 15.0)
    assert (c.profit_before_pct, c.profit_after_pct) == (13.0, 15.0)


def test_pp_net_margin_uses_travellers():
    b = line("Food", "Dinner", "PP", unit=51.5)
    b.unit_price_net, b.profit_pct = 50.0, 3.0
    a = line("Food", "Dinner", "PP", unit=57.5)
    a.unit_price_net, a.profit_pct = 50.0, 15.0
    r = compare(snap("v1", [b]), snap("v2", [a]))
    assert (r.changes[0].margin_before, r.changes[0].margin_after) == (3.0, 15.0)      # 2 travellers: 103-100, 115-100


def test_margin_tab_bridge_and_markup_changes():
    from myt_mcp.quote.compare import MarginCategory, MarginTab

    m1 = MarginTab(categories={"Other": MarginCategory(markup_pct=10), "Food": MarginCategory(net_pp=200, margin_pp=16)},
                   conversion_pct=5, net_pp=500, margin_pp=100, gross_pp=600, net_pg=1000, margin_pg=200, gross_pg=1200, publish_pp=600, publish_pg=1200)
    m2 = MarginTab(categories={"Other": MarginCategory(markup_pct=15), "Food": MarginCategory(net_pp=200, margin_pp=16)},
                   conversion_pct=5, net_pp=550, margin_pp=130, gross_pp=680, net_pg=1100, margin_pg=260, gross_pg=1360, publish_pp=680, publish_pg=1360)
    r = compare(snap("v1", [line("Food", "X")], margin=m1), snap("v2", [line("Food", "X")], margin=m2))
    assert r.margin_summary["gross_pg"].effect == 160 and r.margin_summary["margin_pg"].effect == 60
    assert r.margin_summary["margin_pct"].before == 20.0 and r.margin_summary["margin_pct"].after == 23.64
    assert r.markup_changes == ["Other markup 10.0% -> 15.0%"] and list(r.margin_by_category) == ["Other"]
    assert "supplier costs +100" in r.price_bridge and "margin +60" in r.price_bridge and "not explained" not in r.price_bridge
    assert not any("Margin Prices tab was not given" in n for n in r.notes)



def test_line_prices_show_what_myt_should_display():
    from myt_mcp.quote.calc import CostLine, calculate

    lines = [CostLine(category="Food", supplier="ITCooking", product_name="Cooking workshop", pricing="PP", unit_price=150, profit_pct=3),
             CostLine(category="Lodging", supplier="H", product_name="Room", pricing="PS", unit_price=100, days=2)]
    r = calculate(lines, paying_pax=2)
    food, room = r.lines
    assert (food.myt_price_column, food.with_profit_group, food.net_group) == (154.5, 309.0, 300.0)   # PP: per person vs group
    assert (room.myt_price_column, room.with_profit_group) == (226.0, 226.0)


def test_percent_markup_formula_and_unknown_category():
    import pytest
    from myt_mcp.quote.calc import CostLine, calculate

    line = CostLine(category="Transport", supplier="T", product_name="Train", pricing="PS", unit_price=100, profit_pct=13)
    base = calculate([line], paying_pax=2, conversion_pct=0)
    marked = calculate([line], paying_pax=2, conversion_pct=0, percent_markups={"Transport": 10})
    assert base.gross_pg == 113.0 and marked.gross_pg == 124.3          # 10% on top of the net+profit 113 (MYT: 98.19 -> 108.01)
    assert any("Conversion difference" in n for n in marked.notes) and not base.notes
    assert calculate([line], 2, conversion_pct=0, percent_markups={"General": 10}).gross_pg == 124.3
    with pytest.raises(ValueError):
        calculate([line], 2, percent_markups={"Hotels": 5})


def test_conversion_note_when_conversion_is_applied():
    from myt_mcp.quote.calc import CostLine, calculate

    line = CostLine(category="Lodging", supplier="H", product_name="Room", pricing="PS", unit_price=100, profit_pct=0)
    assert calculate([line], 2, conversion_pct=5).gross_pg == 105.0
    assert any("Conversion difference" in n for n in calculate([line], 2).notes)


def test_percent_markup_matches_what_myt_showed_on_trip_906():
    from myt_mcp.quote.calc import CostLine, calculate

    lines = [CostLine(category="Transport", supplier="Trenitalia", product_name="Train", pricing="PS", unit_price=100, profit_pct=13),
             CostLine(category="Transport", supplier="Ofran", product_name="Car", pricing="PS", unit_price=73.79, profit_pct=13)]
    r = calculate(lines, paying_pax=2, conversion_pct=0, percent_markups={"Transport": 10})
    assert r.categories["Transport"].gross_pp == 108.01          # MYT Margin Prices tab: 98.19 -> 108.01
    assert calculate(lines, 2, conversion_pct=0).categories["Transport"].gross_pp == 98.19

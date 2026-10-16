"""Checks quote_math against the client's real quotation 352280 (2 pax, 0 free)."""

import pytest

from myt_mcp.quote.calc import CostLine, calculate

TRANSPORT = [
    CostLine(category="Transport", supplier="Azore Airlines", product_name="LIS-TER-PDL-OPO", pricing="PP", unit_price=425, line_type="Ride", transport_type="Flight"),
    CostLine(category="Transport", supplier="Ilha Verde", product_name="Terceira - NISSAN QASHQAI", pricing="PS", unit_price=330, transport_type="Car", seats=5),
    CostLine(category="Transport", supplier="Ilha Verde", product_name="PDL - NISSAN QASHQAI", pricing="PS", unit_price=650, transport_type="Car", seats=5),
    CostLine(category="Transport", supplier="RateHawk", product_name="1x Private Transfer : Airport - Hotel (porto)", pricing="PS", unit_price=30),
    CostLine(category="Transport", supplier="Sixt", product_name="Peugeot E-2008 (lisbon)", pricing="PS", unit_price=600, transport_type="Car", seats=5),
]


def test_transport_matches_myt():
    totals = calculate(TRANSPORT, paying_pax=2)
    t = totals.categories["Transport"]
    assert t.net_pp == 1230.00
    assert t.margin_pp == pytest.approx(229.40, abs=0.01)
    assert t.gross_pp == pytest.approx(1459.40, abs=0.01)


def test_full_quote_matches_myt():
    # Lodging and Attraction lines are not visible in the recording, so they are
    # entered as one line each with the group net shown on MARGING PRICES.
    # Staff lines use mixed profit %, so the Staff gross is taken as given.
    lines = TRANSPORT + [
        CostLine(category="Lodging", supplier="various", product_name="hotels", pricing="PS", unit_price=4101.00),
        CostLine(category="Attraction", supplier="various", product_name="attractions", pricing="PS", unit_price=924.00),
    ]
    totals = calculate(lines, paying_pax=2, fixed_markups_pp={"Other": 230})
    assert totals.categories["Lodging"].gross_pp == pytest.approx(2432.92, abs=0.01)
    assert totals.categories["Attraction"].gross_pp == pytest.approx(548.16, abs=0.01)
    assert totals.categories["Other"].gross_pp == 241.50
    staff_gross_pp = 353.61
    assert totals.gross_pp + staff_gross_pp == pytest.approx(5035.58, abs=0.02)


def test_mixed_currencies_rejected():
    lines = [TRANSPORT[0], TRANSPORT[1].model_copy(update={"currency": "USD"})]
    with pytest.raises(ValueError):
        calculate(lines, paying_pax=2)

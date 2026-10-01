from __future__ import annotations

import pytest

from komfort_cards.formatting import format_price, normalize_code, normalize_price


@pytest.mark.parametrize("value, expected", [
    ("00-00135412", "00-00135412"),
    (" 1509373 ", "1509373"),
    ("007", "007"),
    (828447.0, "828447"),
    (1509373, "1509373"),
    (None, ""),
])
def test_normalize_code_keeps_table_value(value, expected):
    assert normalize_code(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("4880", "4880"),
    ("4 880", "4880"),
    ("131 500 ₸", "131500"),
    (999, "999"),
    (1400.0, "1400"),
    ("1234,5", "1234,50"),
    ("1234.50", "1234,50"),
])
def test_normalize_price(value, expected):
    assert normalize_price(value) == expected


@pytest.mark.parametrize("value", ["", "  ", "договорная", "12-50", None, "1,234,567"])
def test_normalize_price_rejects_non_prices(value):
    with pytest.raises(ValueError):
        normalize_price(value)


@pytest.mark.parametrize("value, expected", [
    ("799", "799"),
    ("4880", "4 880"),
    ("131500", "131 500"),
    ("1234567", "1 234 567"),
    ("1234,5", "1 234,50"),
])
def test_format_price_groups_thousands(value, expected):
    assert format_price(value) == expected


def test_format_price_custom_space_for_html():
    assert format_price("131500", space=" ") == "131 500"

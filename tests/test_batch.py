from __future__ import annotations

import argparse
from datetime import datetime

import pytest

from komfort_cards import batch as B
from komfort_cards import paths
from komfort_cards.console import CardsError


def make_valid_batch(rows: int = 2) -> dict:
    batch = B.create_batch(rows, label="тест")
    for item in batch["items"]:
        n = item["n"]
        photo = f"_work/photos/{n:02d}.png"
        (paths.batch_dir(batch["batch_id"]) / photo).write_bytes(b"png")
        item.update({
            "code": f"00-0013541{n}", "name": f"Грунтовка концентрат {n}", "price": "11850",
            "category": "paint", "photo": photo, "photo_note": "белая канистра",
            "texts": {"title": "Грунтовка концентрат", "badge": ["«Dekoral» 10 л."],
                      "plate": {"value": "10 л", "label": "объём"}, "features": []},
            "sources": {"title": "table", "badge": "packaging", "plate": "packaging"},
        })
    B.save_batch(batch)
    return batch


def test_new_batch_id_is_dated_and_unique(isolated_output):
    now = datetime(2026, 10, 1, 15, 30)
    first = B.new_batch_id("посуда дымка", now)
    assert first == "2026-10-01_1530_посуда-дымка"
    B.create_batch(1, batch_id=first)
    assert B.new_batch_id("посуда дымка", now) == "2026-10-01_1530_посуда-дымка_2"


def test_create_batch_makes_work_dirs_and_skeleton(isolated_output):
    batch = B.create_batch(3)
    root = paths.batch_dir(batch["batch_id"])
    for sub in B.WORK_SUBDIRS:
        assert (root / "_work" / sub).is_dir()
    loaded = B.load_batch(batch["batch_id"])
    assert [i["n"] for i in loaded["items"]] == [1, 2, 3]
    assert loaded["confirmed"] is False


def test_resolve_batch_defaults_to_latest(isolated_output):
    B.create_batch(1, batch_id="2026-10-01_1000")
    B.create_batch(1, batch_id="2026-10-01_1200")
    assert B.resolve_batch_id(None) == "2026-10-01_1200"
    with pytest.raises(CardsError):
        B.resolve_batch_id("нет-такой")


def test_valid_batch_has_no_errors(isolated_output):
    batch = make_valid_batch()
    assert [i for i in B.validate_batch(batch) if i.severity == "error"] == []


@pytest.mark.parametrize("field, value, fragment", [
    ("code", "", "нет кода"),
    ("price", "", "нет цены"),
    ("price", "договорная", "цена не число"),
    ("name", "", "нет названия"),
    ("photo", "_work/photos/99.png", "файл не найден"),
])
def test_missing_or_bad_item_fields_are_errors(isolated_output, field, value, fragment):
    batch = make_valid_batch(1)
    batch["items"][0][field] = value
    errors = [i for i in B.validate_batch(batch) if i.severity == "error"]
    assert any(fragment in i.message for i in errors), errors


def test_numbers_from_knowledge_are_rejected(isolated_output):
    batch = make_valid_batch(1)
    batch["items"][0]["sources"]["plate"] = "knowledge"
    errors = [i for i in B.validate_batch(batch) if i.severity == "error"]
    assert any(i.field == "sources.plate" for i in errors)


def test_text_limits(isolated_output):
    batch = make_valid_batch(1)
    texts = batch["items"][0]["texts"]
    texts["title"] = "Х" * 41
    texts["features"] = [{"icon": "weight", "text": "a"}] * 4
    texts["title_accent"] = "чего нет"
    fields = {i.field for i in B.validate_batch(batch) if i.severity == "error"}
    assert {"texts.title", "texts.features", "texts.title_accent"} <= fields


def test_normalize_coerces_excel_numbers(isolated_output):
    batch = make_valid_batch(1)
    batch["items"][0]["code"] = 828447.0
    batch["items"][0]["price"] = 999.0
    batch["items"][0]["texts"]["badge"] = "одна строка"
    assert B.normalize_batch(batch)
    item = batch["items"][0]
    assert (item["code"], item["price"], item["texts"]["badge"]) == ("828447", "999", ["одна строка"])


def test_summary_lists_every_row_and_flags_errors(isolated_output):
    batch = make_valid_batch(3)
    batch["items"][2]["price"] = ""
    issues = B.validate_batch(batch)
    table = B.summary_markdown(batch, issues)
    assert table.count("\n") == 4  # header + separator + 3 rows
    assert "11 850 ₸" in table and "3 ⚠" in table and "белая канистра" in table


def test_confirm_requires_valid_data(isolated_output):
    batch = make_valid_batch(1)
    batch["items"][0]["price"] = ""
    B.save_batch(batch)
    args = argparse.Namespace(batch=batch["batch_id"])
    with pytest.raises(CardsError):
        B.cmd_confirm(args)
    batch["items"][0]["price"] = "799"
    B.save_batch(batch)
    assert B.cmd_confirm(args)["confirmed"] is True
    assert B.load_batch(batch["batch_id"])["confirmed"] is True


def test_require_confirmed_blocks_generation(isolated_output):
    batch = make_valid_batch(1)
    with pytest.raises(CardsError):
        B.require_confirmed(batch)

from __future__ import annotations

import argparse
import copy

import pytest
from PIL import Image

from komfort_cards import batch as B
from komfort_cards import paths, qa
from komfort_cards.console import CardsError


def box(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h, "right": x + w, "bottom": y + h}


GOOD_METRICS = {
    "overflow": {"title": False, "price": False}, "fonts_loaded": True, "warnings": [],
    "loaded": {"background": True, "product": True, "logo": True},
    "boxes": {"title": box(78, 84, 900, 100), "badge": box(78, 200, 400, 80), "code": box(700, 1086, 298, 55),
              "price": box(600, 1142, 333, 134), "tenge": box(957, 1188, 41, 56), "product": box(250, 340, 600, 640)},
    "product": {"area_ratio": 0.30},
}


@pytest.fixture()
def rendered_batch(isolated_output):
    batch = B.create_batch(2)
    for item in batch["items"]:
        card = f"{item['n']:02d}_x.png"
        Image.new("RGB", (1080, 1350), (30, 30, 30)).save(paths.batch_dir(batch["batch_id"]) / card)
        item.update({"code": f"10{item['n']}", "status": "rendered", "files": {"card": card},
                     "render": copy.deepcopy(GOOD_METRICS)})
    B.save_batch(batch)
    return batch


def test_good_card_passes(rendered_batch):
    assert qa.check_item(rendered_batch["batch_id"], rendered_batch["items"][0]) == []


@pytest.mark.parametrize("mutate, fragment", [
    (lambda m: m["overflow"].update(title=True), "не помещается"),
    (lambda m: m["boxes"].update(product=box(250, 150, 600, 640)), "под «title»"),
    (lambda m: m["boxes"].update(product=box(500, 700, 400, 500)), "под «price»"),
    (lambda m: m["product"].update(area_ratio=0.1), "товар занимает"),
    (lambda m: m["loaded"].update(logo=False), "нет логотипа"),
    (lambda m: m.update(fonts_loaded=False), "шрифты"),
])
def test_problems_are_detected(rendered_batch, mutate, fragment):
    item = rendered_batch["items"][0]
    mutate(item["render"])
    problems = qa.check_item(rendered_batch["batch_id"], item)
    assert any(fragment in p for p in problems), problems


def test_check_batch_marks_needs_review_and_writes_preview(rendered_batch):
    rendered_batch["items"][1]["render"]["overflow"]["price"] = True
    report = qa.check_batch(rendered_batch)
    statuses = {r["n"]: r["status"] for r in report["items"]}
    assert statuses == {1: "rendered", 2: "needs_review"}
    assert (paths.batch_dir(rendered_batch["batch_id"]) / "preview.jpg").is_file()


def test_review_ok_and_issue(rendered_batch):
    bid = rendered_batch["batch_id"]
    qa.cmd_review(argparse.Namespace(batch=bid, item=1, ok=True, issue=None))
    qa.cmd_review(argparse.Namespace(batch=bid, item=2, ok=False, issue="на фоне надпись"))
    items = B.load_batch(bid)["items"]
    assert items[0]["status"] == "approved"
    assert items[1]["status"] == "needs_review" and "осмотр: на фоне надпись" in items[1]["issues"]


def test_review_ok_refused_while_auto_checks_fail(rendered_batch):
    rendered_batch["items"][0]["render"]["overflow"]["title"] = True
    qa.check_batch(rendered_batch)
    with pytest.raises(CardsError):
        qa.cmd_review(argparse.Namespace(batch=rendered_batch["batch_id"], item=1, ok=True, issue=None))

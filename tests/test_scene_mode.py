from __future__ import annotations

import argparse

import pytest
from PIL import Image

from komfort_cards import batch as B
from komfort_cards import cutout, paths, render, selftest


def test_frame_transform_never_leaves_empty_strips():
    assert render.frame_transform({}) == (1.0, 0.0)
    zoom, shift = render.frame_transform({"bg_zoom": 1.1, "bg_shift_y": 500})
    assert zoom == 1.1 and shift == pytest.approx(1350 * 0.1 / 2)  # clamped to the overflow
    assert render.frame_transform({"bg_zoom": 3, "bg_shift_y": -10})[0] == 1.4


def test_displayed_box_follows_zoom_and_shift():
    assert render.displayed_box([440, 575, 640, 775], 1.0, 0.0) == [440, 575, 640, 775]
    assert render.displayed_box([440, 575, 640, 775], 1.2, 30) == [420, 585, 660, 825]


def test_reference_crops_and_pads_on_white(isolated_output):
    batch = B.create_batch(1)
    photo = paths.batch_dir(batch["batch_id"]) / "_work" / "photos" / "01.png"
    img = Image.new("RGB", (1000, 500), "white")
    img.paste((200, 30, 30), (600, 100, 900, 400))
    img.save(photo)
    batch["items"][0].update(photo="_work/photos/01.png", photo_crop=[0.5, 0, 1, 1])
    B.save_batch(batch)
    result = cutout.cmd_reference(argparse.Namespace(batch=batch["batch_id"], item=1))
    with Image.open(result["reference"]) as ref:
        assert ref.size == (580, 580)  # 500x500 crop + 8% white padding on each side
        assert ref.getpixel((5, 5)) == (255, 255, 255)
    assert B.load_batch(batch["batch_id"])["items"][0]["files"]["reference"] == "_work/refs/01.png"


def test_scene_mode_card_data_has_no_product_layer(isolated_output):
    batch = {"batch_id": "s1", "items": []}
    paths.batch_dir("s1").mkdir(parents=True)
    item = {"n": 1, "code": "1", "price": "100", "texts": {"title": "Т"}, "files": {"cutout": "x.png"},
            "scene": {"box": [300, 400, 780, 1000], "area_ratio": 0.21}, "layout": {"bg_zoom": 1.1}}
    data = render.card_data(batch, item)
    assert data["product"] is None and data["scene_box"] == render.displayed_box([300, 400, 780, 1000], 1.1, 0.0)


@pytest.mark.browser
def test_scene_mode_render_reports_the_scene_box(isolated_output):
    batch = selftest.selftest_batch()
    item = batch["items"][0]
    item["layout"] = {"mode": "scene"}
    item["scene"] = {"box": [330, 380, 750, 990], "area_ratio": 0.19}
    html = paths.work_dir(batch["batch_id"]) / "html" / "scene.html"
    html.write_text(render.build_html("stroyka", render.card_data(batch, item)), encoding="utf-8")
    with render.browser_page() as page:
        metrics = render.render_html_file(page, html, paths.batch_dir(batch["batch_id"]) / "scene.png")
    assert metrics["loaded"].get("product") is False
    assert metrics["product"]["source"] == "scene"
    assert metrics["boxes"]["product"] == {"x": 330, "y": 380, "w": 420, "h": 610, "right": 750, "bottom": 990}


model_present = pytest.mark.skipif(cutout.model_file() is None, reason="модель вырезки не скачана")


@model_present
def test_main_object_box_finds_the_product_on_a_scene():
    with Image.open(paths.SELFTEST_DIR / "background.jpg") as bg, Image.open(paths.SELFTEST_DIR / "product.png") as product:
        scene = bg.convert("RGB").resize((1080, 1350))
        scene.paste(product, (283, 330), mask=product.getchannel("A"))
    box, area = cutout.main_object_box(scene)
    assert box is not None
    x0, y0, x1, y1 = box
    assert abs(x0 - 283) < 40 and abs(y0 - 330) < 40 and abs(x1 - (283 + 514)) < 40 and abs(y1 - (330 + 633)) < 40
    assert 0.15 < area < 0.35

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from komfort_cards import cutout, paths
from komfort_cards.console import CardsError


def test_decontaminate_removes_white_fringe():
    # an edge pixel that is 50% red product + 50% white background should become pure red
    rgb = np.array([[[255, 128, 128]]], dtype=np.uint8)
    alpha = np.array([[128]], dtype=np.uint8)
    out = cutout.decontaminate(rgb, alpha)
    assert out[0, 0, 0] >= 250 and out[0, 0, 1] <= 8 and out[0, 0, 2] <= 8


def test_decontaminate_keeps_opaque_pixels():
    rgb = np.array([[[10, 200, 30]]], dtype=np.uint8)
    assert (cutout.decontaminate(rgb, np.array([[255]], dtype=np.uint8)) == rgb).all()


def test_remove_islands_drops_specks_and_counts_parts():
    alpha = np.zeros((200, 200), dtype=np.uint8)
    alpha[20:120, 20:120] = 255      # the product
    alpha[150:190, 150:190] = 255    # a second real part (4% of the image)
    alpha[5:7, 190:192] = 255        # dust speck
    cleaned, parts = cutout.remove_islands(alpha)
    assert parts == 2
    assert cleaned[6, 191] == 0 and cleaned[50, 50] == 255


def test_trim_adds_padding_and_reports_bbox():
    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([100, 50, 199, 149], fill=(255, 0, 0, 255))
    trimmed, bbox = cutout.trim(img, padding=0.02)
    assert bbox == (100, 50, 200, 150)
    assert trimmed.size == (100 + 16, 100 + 16)  # 2% of 400 = 8 px each side


def test_review_reasons():
    ok = {"coverage": 0.3, "islands": 1, "bbox": [1, 1, 5, 5], "touches_edge": False}
    assert cutout.review_reasons(ok) == []
    bad = {"coverage": 0.01, "islands": 5, "bbox": [0, 0, 5, 5], "touches_edge": True}
    assert len(cutout.review_reasons(bad)) == 3
    assert cutout.review_reasons({**ok, "bbox": None})


def test_crop_relative_validates_and_crops():
    photo = Image.new("RGB", (1000, 500), "white")
    assert cutout.crop_relative(photo, [0.5, 0.0, 1.0, 1.0]).size == (500, 500)
    assert cutout.crop_relative(photo, None) is photo
    with pytest.raises(CardsError):
        cutout.crop_relative(photo, [0.6, 0.0, 0.5, 1.0])


model_present = pytest.mark.skipif(cutout.model_file() is None, reason="модель вырезки не скачана (cards setup-models)")


@model_present
def test_white_product_on_white_background_is_cut_cleanly():
    with Image.open(paths.SELFTEST_DIR / "product.png") as product:
        photo = Image.new("RGB", (product.width + 120, product.height + 120), "white")
        photo.paste(product, (60, 60), mask=product.getchannel("A"))
        expected = (np.asarray(product.getchannel("A")) > 127).sum() / (photo.width * photo.height)
    cut, metrics = cutout.postprocess(photo, __import__("rembg").remove(photo, session=cutout._session(), only_mask=True))
    assert cutout.review_reasons(metrics) == []
    assert abs(metrics["coverage"] - expected) < 0.06
    # no white rim: average colour of the outermost opaque ring is not near-white
    a = np.asarray(cut.getchannel("A"))
    ring = (a > 30) & (a < 200)
    assert np.asarray(cut.convert("RGB"))[ring].mean() < 245

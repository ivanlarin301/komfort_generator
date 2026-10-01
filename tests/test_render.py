from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from komfort_cards import paths, render, selftest

GOLDEN = Path(__file__).parent / "golden" / "selftest.png"


def test_build_html_injects_base_and_escapes_data():
    html = render.build_html("stroyka", {"title": "</script><b>x", "badge": []})
    assert '<base href="file:///' in html
    assert "<\\/script>" in html and "</script><b>" not in html


def test_output_name_is_filesystem_safe():
    assert render.output_name({"n": 3, "code": "00-00135412"}) == "03_00-00135412"
    assert render.output_name({"n": 12, "code": 'a/b:c *d'}) == "12_a-b-c-d"


def test_next_free_never_overwrites(tmp_path):
    first = tmp_path / "01_123.png"
    assert render.next_free(first) == first
    first.write_bytes(b"x")
    assert render.next_free(first).name == "01_123_v2.png"
    (tmp_path / "01_123_v2.png").write_bytes(b"x")
    assert render.next_free(first).name == "01_123_v3.png"


def test_card_data_formats_price_and_skips_missing_images(isolated_output):
    batch = {"batch_id": "b1", "items": []}
    (paths.batch_dir("b1")).mkdir(parents=True)
    item = {"n": 1, "code": "888735", "price": "131500",
            "texts": {"title": "Т", "plate": {"value": "250 мл"}}, "files": {"cutout": "_work/cutouts/01.png"}}
    data = render.card_data(batch, item)
    assert data["price"] == "131 500"
    assert data["product"] is None  # file does not exist
    assert data["plate"] == {"value": "250 мл", "label": "", "style": "green", "plus": True}


@pytest.mark.browser
def test_selftest_layout_matches_canva_anchors_and_golden(isolated_output):
    out_png, metrics, problems = selftest.run_selftest()
    assert problems == []
    assert metrics["fonts"]["price"] == 110
    with Image.open(out_png) as got, Image.open(GOLDEN) as want:
        assert got.size == want.size == (1080, 1350)
        diff = np.abs(np.asarray(got.convert("RGB"), dtype=np.int16) - np.asarray(want.convert("RGB"), dtype=np.int16))
    assert diff.mean() < 2.0, f"render drifted from the golden image (mean diff {diff.mean():.2f})"


@pytest.mark.browser
def test_long_title_shrinks_then_wraps_without_overflow(isolated_output):
    batch = selftest.selftest_batch()
    item = batch["items"][0]
    item["texts"]["title"] = "Герметик силиконовый санитарный универсальный"
    item["texts"]["badge"] = ["грузоподъемность **250 кг**"]
    html = paths.work_dir(batch["batch_id"]) / "html" / "long.html"
    html.write_text(render.build_html("stroyka", render.card_data(batch, item)), encoding="utf-8")
    with render.browser_page() as page:
        metrics = render.render_html_file(page, html, paths.batch_dir(batch["batch_id"]) / "long.png")
    assert metrics["fonts"]["title_lines"] == 2
    assert not any(metrics["overflow"].values()), metrics["overflow"]
    product, badge = metrics["boxes"]["product"], metrics["boxes"]["badge"]
    assert product["y"] >= badge["bottom"] + 55  # air above the product (owner request)

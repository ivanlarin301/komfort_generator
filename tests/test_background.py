from __future__ import annotations

import argparse
import os
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from komfort_cards import background, batch as B, codex, paths, prompts
from komfort_cards.console import CardsError

THREAD = "01a0f3ac-475b-7ca3-b43d-90d36e3fd77d"


def framed_image(w=1122, h=1402) -> Image.Image:
    img = Image.new("RGB", (w, h), (90, 80, 70))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(0, 0, 0))  # the 1px frame earlier generations had
    d.ellipse([200, 300, 900, 1100], fill=(140, 120, 100))
    return img


def test_trim_uniform_border_removes_frame():
    trimmed = background.trim_uniform_border(framed_image())
    assert trimmed.size == (1120, 1400)
    assert np.asarray(trimmed)[0, :, :].mean() > 60  # the black line is gone


def test_trim_keeps_images_without_frame():
    img = Image.new("RGB", (800, 1000), (90, 80, 70))
    assert background.trim_uniform_border(img).size == (800, 1000)


def test_cover_resize_to_canvas():
    out = background.cover_resize(Image.new("RGB", (1024, 1536)))
    assert out.size == (1080, 1350)


@pytest.mark.parametrize("category", ["dry_mix", "paint", "boards", "sealants", "garden", "default"])
def test_composite_prompt_has_surface_and_bans(category):
    scenes = prompts.load_scenes()
    text = prompts.build_prompt(category, scenes)
    assert scenes["categories"][category]["surfaces"][0] in text
    for ban in ("no text", "no logos", "no people", "No products"):
        assert ban in text
    assert "{" not in text


def scene_batch(categories):
    items = [{"n": i, "category": c, "name": f"Антисептик {i}", "photo_note": "бутылка 1 л", "layout": {}}
             for i, c in enumerate(categories, start=1)]
    return {"batch_id": "x", "items": items}


def test_scene_prompt_describes_product_and_bans_extra_text():
    batch = scene_batch(["paint"])
    text, variant = prompts.build_scene_prompt(batch, batch["items"][0])
    assert "Антисептик 1, бутылка 1 л" in text and variant == 0
    assert "three-dimensional" in text and "contact shadow" in text
    assert "Do not add any other text" in text and "{" not in text


def test_scene_prompts_rotate_surfaces_within_a_batch():
    batch = scene_batch(["paint", "paint", "paint", "dry_mix"])
    surfaces = prompts.load_scenes()["categories"]["paint"]["surfaces"]
    used = [next(s for s in surfaces if s in prompts.build_scene_prompt(batch, item)[0]) for item in batch["items"][:3]]
    assert len(set(used)) == 3  # three paint items -> three different surfaces
    assert prompts.build_scene_prompt(batch, batch["items"][3])[1] == 0  # first dry_mix item starts its own rotation


def test_variant_override_and_product_desc():
    batch = scene_batch(["paint"])
    item = batch["items"][0]
    item["layout"] = {"variant": 2}
    item["product_desc"] = "a 1 L black Tikkurila bottle"
    text, variant = prompts.build_scene_prompt(batch, item)
    assert variant == 2 and "a 1 L black Tikkurila bottle" in text


def test_unknown_category_is_an_error():
    with pytest.raises(CardsError):
        prompts.build_prompt("нет-такой")


@pytest.fixture()
def fake_codex(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    rollout = home / "sessions" / "2026" / "10" / "02" / f"rollout-2026-10-02T10-00-00-{THREAD}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    gen = home / "generated_images" / THREAD
    gen.mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    return gen


def test_generated_images_newest_first_from_current_thread(fake_codex):
    older, newer = fake_codex / "exec-a.png", fake_codex / "exec-b.png"
    framed_image(300, 375).save(older)
    framed_image(300, 375).save(newer)
    os.utime(older, (time.time() - 100, time.time() - 100))
    assert codex.generated_images()[0] == newer
    assert codex.thread_id(codex.latest_rollout()) == THREAD


def make_confirmed_batch() -> dict:
    batch = B.create_batch(2)
    batch["confirmed"] = True
    B.save_batch(batch)
    return batch


def test_background_command_takes_newest_and_refuses_reuse(isolated_output, fake_codex):
    framed_image().save(fake_codex / "exec-1.png")
    batch = make_confirmed_batch()
    args = argparse.Namespace(batch=batch["batch_id"], item=1, file=None)
    result = background.cmd_background(args)
    saved = paths.batch_dir(batch["batch_id"]) / result["background"]
    with Image.open(saved) as img:
        assert img.size == (1080, 1350)
    with pytest.raises(CardsError):  # the same generation must not silently go to item 2
        background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=2, file=None))


def test_pick_takes_an_earlier_generation_by_number(isolated_output, fake_codex):
    first, second = fake_codex / "exec-first.png", fake_codex / "exec-second.png"
    framed_image().save(first)
    framed_image().save(second)
    os.utime(first, (time.time() - 60, time.time() - 60))
    assert codex.chat_generations() == [first, second]  # No.1 = the first generated in this chat
    batch = make_confirmed_batch()
    result = background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=2, file=None, pick=1))
    assert result["source"] == str(first)
    listing = background.cmd_generations(argparse.Namespace(batch=batch["batch_id"]))
    assert [g["used_by"] for g in listing["generations"]] == [2, None]
    with pytest.raises(CardsError):
        background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=1, file=None, pick=5))


def test_background_keeps_previous_attempts(isolated_output, fake_codex, tmp_path):
    batch = make_confirmed_batch()
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    framed_image().save(first)
    framed_image().save(second)
    background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=1, file=str(first)))
    background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=1, file=str(second)))
    folder = paths.work_dir(batch["batch_id"]) / "backgrounds"
    assert (folder / "01.png").is_file() and (folder / "01_try1.png").is_file()
    assert B.load_batch(batch["batch_id"])["items"][0]["status"] == "bg_ready"


def test_background_requires_confirmation(isolated_output, tmp_path):
    batch = B.create_batch(1)
    src = tmp_path / "bg.png"
    framed_image().save(src)
    with pytest.raises(CardsError):
        background.cmd_background(argparse.Namespace(batch=batch["batch_id"], item=1, file=str(src)))

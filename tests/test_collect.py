from __future__ import annotations

import argparse
import base64
import io
import json

import pytest
from PIL import Image

from komfort_cards import batch as B
from komfort_cards import collect, paths, table
from komfort_cards.console import CardsError

THREAD = "01a0f5c7-506a-7781-aa40-3ba7ecf79761"
COLORS = [(200, 30, 30), (30, 200, 30), (30, 30, 200)]


def png(color, path=None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    if path:
        path.write_bytes(buf.getvalue())
    return buf.getvalue()


def user_message(paths_list):
    content = [{"type": "text", "text": "сделай карточки", "text_elements": []}]
    content += [{"type": "local_image", "path": str(p)} for p in paths_list]
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": content}}}


def response_message(colors):
    content = [{"type": "input_text", "text": "сделай карточки"}]
    content += [{"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(png(c)).decode()} for c in colors]
    return {"type": "response_item", "payload": {"type": "message", "role": "user", "content": content}}


@pytest.fixture()
def codex_session(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    rollout = home / "sessions" / "2026" / "10" / "02" / f"rollout-2026-10-02T11-00-00-{THREAD}.jsonl"
    rollout.parent.mkdir(parents=True)
    temp = tmp_path / "temp"
    temp.mkdir()
    old = temp / "old.png"
    png((9, 9, 9), old)
    files = [temp / f"codex-clipboard-{i}.png" for i in range(3)]
    for f, c in zip(files, COLORS):
        png(c, f)
    records = [user_message([old]), response_message([(9, 9, 9)]), user_message(files), response_message(COLORS)]
    rollout.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return files


def args(**kw):
    base = dict(batch=None, label=None, count=None, table_index=None, from_input=False)
    base.update(kw)
    return argparse.Namespace(**base)


def photo_colors(batch_id):
    loaded = B.load_batch(batch_id)
    out = []
    for item in loaded["items"]:
        with Image.open(paths.batch_dir(batch_id) / item["photo"]) as img:
            out.append(img.convert("RGB").getpixel((5, 5)))
    return out


def test_collects_latest_message_in_attachment_order(isolated_output, codex_session):
    result = collect.cmd_collect(args(count=3))
    assert result["source"] == "codex"
    assert photo_colors(result["batch"]) == COLORS


def test_falls_back_to_base64_when_temp_files_are_gone(isolated_output, codex_session):
    for f in codex_session:
        f.unlink()
    result = collect.cmd_collect(args())
    assert [p["from"] for p in result["photos"]] == ["base64"] * 3
    assert photo_colors(result["batch"]) == COLORS


def test_table_index_separates_the_table_image(isolated_output, codex_session):
    result = collect.cmd_collect(args(table_index=3))
    assert len(result["photos"]) == 2 and result["table"].startswith("_work/table")
    assert B.load_batch(result["batch"])["table_source"] == "screenshot"


def test_count_mismatch_stops_before_creating_a_batch(isolated_output, codex_session):
    with pytest.raises(CardsError):
        collect.cmd_collect(args(count=5))
    assert B.list_batch_ids() == []


def test_input_folder_fallback_uses_natural_order_and_moves_files(isolated_output, monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    for name, color in (("10.png", COLORS[2]), ("2.png", COLORS[1]), ("1.png", COLORS[0])):
        png(color, paths.INPUT_DIR / name)
    result = collect.cmd_collect(args())
    assert result["source"] == "input"
    assert photo_colors(result["batch"]) == COLORS
    assert not (paths.INPUT_DIR / "1.png").exists()
    assert (paths.INPUT_DIR / "_collected" / result["batch"] / "10.png").exists()


def test_no_photos_anywhere_is_a_clear_error(isolated_output, monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex"))
    with pytest.raises(CardsError):
        collect.cmd_collect(args())


def test_read_table_keeps_codes_and_lists_price_columns(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Код АХ", "Наименование", "Текущая цена", "Цена для акции"])
    ws.append([828447.0, "Бульонница LUMINARC ЭКЛИПС 560мл", 1400, 999])
    ws.append(["00-00159654", "Салатник АМБЬЯНТЕ ЭКЛИПС 24см L5175", 2500, 1799])
    path = tmp_path / "t.xlsx"
    wb.save(path)
    data = table.read_table(path)
    assert data["code_column"] == "Код АХ" and data["name_column"] == "Наименование"
    assert data["price_columns"] == ["Текущая цена", "Цена для акции"]
    assert [r["Код АХ"] for r in data["rows"]] == ["828447", "00-00159654"]

"""Self-test: render a known card from assets/selftest and verify fonts, layout anchors and size (FR-10)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from komfort_cards import paths
from komfort_cards.batch import WORK_SUBDIRS, empty_item, save_batch
from komfort_cards.console import CardsError, say
from komfort_cards.render import CANVAS, browser_page, build_html, card_data, render_html_file

# Layout anchors measured from the owner's Canva projects (design.md), tolerance in px.
ANCHORS = {
    ("title", "x"): 78, ("title", "y"): 84,
    ("code", "right"): 998, ("price", "right"): 933, ("tenge", "right"): 998,
    ("logo", "x"): 101, ("logo", "y"): 1206,
    ("plate", "x"): 89, ("plate", "y"): 1028,
}
TOLERANCE = 3


def selftest_batch() -> dict[str, Any]:
    batch_id = paths.SELFTEST_BATCH
    root = paths.batch_dir(batch_id)
    for sub in WORK_SUBDIRS:
        (paths.work_dir(batch_id) / sub).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.SELFTEST_DIR / "background.jpg", paths.work_dir(batch_id) / "backgrounds" / "01.jpg")
    shutil.copyfile(paths.SELFTEST_DIR / "product.png", paths.work_dir(batch_id) / "cutouts" / "01.png")
    item = empty_item(1)
    item.update({
        "code": "00-00135412", "name": "Грунтовка концентрат «Dekoral» 10 л", "price": "11850", "category": "paint",
        "texts": {"title": "Грунтовка концентрат", "badge": ["«Dekoral» 10 л."],
                  "plate": {"value": "10 л", "label": "объём", "style": "green"}},
        "files": {"background": "_work/backgrounds/01.jpg", "cutout": "_work/cutouts/01.png"},
    })
    batch = {"batch_id": batch_id, "template": "stroyka", "created_at": datetime.now().isoformat(timespec="seconds"),
             "table_source": "xlsx", "confirmed": True, "items": [item]}
    root.mkdir(parents=True, exist_ok=True)
    save_batch(batch)
    return batch


def check_metrics(metrics: dict[str, Any]) -> list[str]:
    problems = []
    if not metrics.get("fonts_loaded"):
        problems.append("шрифты шаблона не загрузились")
    for key, flag in (metrics.get("overflow") or {}).items():
        if flag:
            problems.append(f"текст не помещается: {key}")
    boxes = metrics.get("boxes") or {}
    for (element, attr), expected in ANCHORS.items():
        value = (boxes.get(element) or {}).get(attr)
        if value is None:
            problems.append(f"нет элемента {element}")
        elif abs(value - expected) > TOLERANCE:
            problems.append(f"{element}.{attr} = {value}, ожидалось {expected}±{TOLERANCE}")
    if not (metrics.get("loaded") or {}).get("logo"):
        problems.append("логотип не загрузился")
    product = metrics.get("product") or {}
    if product.get("area_ratio", 0) < 0.12:
        problems.append("товар не отрисован или слишком мелкий")
    return problems


def run_selftest() -> tuple[Path, dict[str, Any], list[str]]:
    for name in ("background.jpg", "product.png"):
        if not (paths.SELFTEST_DIR / name).is_file():
            raise CardsError(f"Нет файла самопроверки assets/selftest/{name}.", hint="обновите систему (ОБНОВЛЕНИЕ.bat)")
    batch = selftest_batch()
    item = batch["items"][0]
    html_path = paths.work_dir(batch["batch_id"]) / "html" / "01.html"
    html_path.write_text(build_html("stroyka", card_data(batch, item)), encoding="utf-8")
    out_png = paths.batch_dir(batch["batch_id"]) / "card.png"
    with browser_page() as page:
        metrics = render_html_file(page, html_path, out_png)
    problems = check_metrics(metrics)
    with Image.open(out_png) as img:
        if img.size != CANVAS:
            problems.append(f"размер {img.size}, ожидался {CANVAS}")
    return out_png, metrics, problems


def cmd_selftest(args) -> dict[str, Any]:
    out_png, metrics, problems = run_selftest()
    if problems:
        for p in problems:
            say(f" - {p}")
        raise CardsError("Самопроверка не прошла.", hint="пришлите setup.log разработчику",
                         data={"card": str(out_png), "problems": problems})
    say(f"Самопроверка пройдена: {out_png}")
    return {"card": str(out_png), "fonts": metrics.get("fonts"), "problems": []}

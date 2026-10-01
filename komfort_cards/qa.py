"""Quality control (FR-8, FR-9): automatic checks from the template metrics, contact sheet, status report.

The agent's visual check is recorded with `review`: approved, or needs_review with a reason.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from komfort_cards import paths
from komfort_cards.batch import load_batch, resolve_batch_id, save_batch
from komfort_cards.console import CardsError, say

CANVAS = (1080, 1350)
MIN_PRODUCT_AREA = 0.25      # FR-15: the product stays the main element
OVERLAP_TOLERANCE = 8        # px of allowed contact between the product and a text element
TOP_TEXT = ("title", "subtitle", "badge")
FOOTER_TEXT = ("code", "price", "tenge")
STATUS_RU = {"planned": "в плане", "cut": "вырезано", "bg_ready": "фон готов", "rendered": "собрано",
             "approved": "одобрено", "needs_review": "на проверку", "blocked": "заблокировано"}


def _intersects(a: dict[str, int], b: dict[str, int], tolerance: int = 0) -> bool:
    return (a["x"] + tolerance < b["right"] and b["x"] + tolerance < a["right"]
            and a["y"] + tolerance < b["bottom"] and b["y"] + tolerance < a["bottom"])


def check_item(batch_id: str, item: dict[str, Any]) -> list[str]:
    """Automatic checks of one rendered card; returns problems in Russian (empty list = passed)."""
    problems: list[str] = []
    card = (item.get("files") or {}).get("card")
    metrics = item.get("render") or {}
    if not card or not (paths.batch_dir(batch_id) / card).is_file():
        return ["карточка не собрана"]
    with Image.open(paths.batch_dir(batch_id) / card) as img:
        if img.size != CANVAS:
            problems.append(f"размер {img.size[0]}×{img.size[1]} вместо 1080×1350")
    for key, flag in (metrics.get("overflow") or {}).items():
        if flag:
            problems.append(f"текст «{key}» не помещается даже минимальным кеглем — сократите")
    if not metrics.get("fonts_loaded", False):
        problems.append("шрифты шаблона не загрузились")
    loaded = metrics.get("loaded") or {}
    if not loaded.get("background"):
        problems.append("нет фона")
    if not loaded.get("logo"):
        problems.append("нет логотипа")
    boxes = metrics.get("boxes") or {}
    product = boxes.get("product")
    if not product:
        problems.append("нет товара на карточке")
    else:
        area = (metrics.get("product") or {}).get("area_ratio", 0)
        if area < MIN_PRODUCT_AREA:
            problems.append(f"товар занимает {area:.0%} кадра (нужно ≥ {MIN_PRODUCT_AREA:.0%}) — проверьте вырезку и фото")
        for key in TOP_TEXT:
            if boxes.get(key) and _intersects(product, boxes[key], OVERLAP_TOLERANCE):
                problems.append(f"товар заходит под «{key}»")
        for key in FOOTER_TEXT:
            if boxes.get(key) and _intersects(product, boxes[key]):
                problems.append(f"товар заходит под «{key}» (код и цена должны быть на чистом фоне)")
    problems.extend(f"шаблон: {w}" for w in metrics.get("warnings") or [])
    return problems


def contact_sheet(batch: dict[str, Any], columns: int = 4, thumb: tuple[int, int] = (270, 338)) -> Path | None:
    batch_id = batch["batch_id"]
    cards = [(i, paths.batch_dir(batch_id) / i["files"]["card"]) for i in batch["items"]
             if (i.get("files") or {}).get("card") and (paths.batch_dir(batch_id) / i["files"]["card"]).is_file()]
    if not cards:
        return None
    rows = (len(cards) + columns - 1) // columns
    pad, label_h = 12, 30
    sheet = Image.new("RGB", (columns * (thumb[0] + pad) + pad, rows * (thumb[1] + label_h + pad) + pad), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(str(paths.FONTS_DIR / "Montserrat-Variable.ttf"), 18)
    except OSError:
        font = ImageFont.load_default()
    for k, (item, path) in enumerate(cards):
        r, c = divmod(k, columns)
        x, y = pad + c * (thumb[0] + pad), pad + r * (thumb[1] + label_h + pad)
        with Image.open(path) as img:
            sheet.paste(img.convert("RGB").resize(thumb, Image.LANCZOS), (x, y))
        status = item.get("status", "")
        color = (140, 210, 120) if status == "approved" else (255, 120, 100) if status in ("needs_review", "blocked") else (230, 230, 230)
        draw.text((x, y + thumb[1] + 5), f"{item['n']}. {item.get('code', '')} — {STATUS_RU.get(status, status)}", font=font, fill=color)
    out = paths.batch_dir(batch_id) / "preview.jpg"
    sheet.save(out, quality=88)
    return out


def check_batch(batch: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run automatic checks after rendering; failed items become needs_review. Saves the batch and the preview."""
    report = []
    for item in items or batch["items"]:
        if item.get("status") == "blocked":
            continue
        problems = check_item(batch["batch_id"], item)
        item["issues"] = [i for i in item.get("issues", []) if not i.startswith("проверка:")] + [f"проверка: {p}" for p in problems]
        if problems:
            item["status"] = "needs_review"
        elif item.get("status") == "needs_review" and not item["issues"]:
            item["status"] = "rendered"
        report.append({"n": item["n"], "status": item["status"], "problems": problems})
        for p in problems:
            say(f"  [{item['n']}] ПРОВЕРКА: {p}")
    save_batch(batch)
    preview = contact_sheet(batch)
    if preview:
        say(f"Лист-превью партии: {preview}")
    return {"items": report, "preview": str(preview) if preview else None}


def cmd_status(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    counts: dict[str, int] = {}
    rows = []
    for item in batch["items"]:
        status = item.get("status", "planned")
        counts[status] = counts.get(status, 0) + 1
        card = (item.get("files") or {}).get("card") or "—"
        say(f"{item['n']:>2}. {item.get('code') or '—':<14} {STATUS_RU.get(status, status):<14} {card}")
        for issue in item.get("issues") or []:
            say(f"      • {issue}")
        rows.append({"n": item["n"], "code": item.get("code"), "status": status, "card": card, "issues": item.get("issues") or []})
    say("Итого: " + ", ".join(f"{STATUS_RU.get(k, k)} — {v}" for k, v in counts.items()))
    say(f"Папка партии: {paths.batch_dir(batch_id)}")
    return {"batch": batch_id, "counts": counts, "items": rows}


def cmd_review(args) -> dict[str, Any]:
    """Record the agent's visual check of one card (FR-9)."""
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    item = next((i for i in batch["items"] if i["n"] == args.item), None)
    if item is None:
        raise CardsError(f"В партии нет позиции {args.item}.")
    if args.ok == bool(args.issue):
        raise CardsError("Укажите либо --ok, либо --issue «причина».")
    if args.ok:
        if any(i.startswith("проверка:") for i in item.get("issues") or []):
            raise CardsError("У карточки есть невыполненные автопроверки — сначала исправьте и пересоберите.",
                             data={"issues": item["issues"]})
        if item.get("status") not in ("rendered", "needs_review", "approved"):
            raise CardsError(f"Карточка в статусе «{STATUS_RU.get(item.get('status'), item.get('status'))}» — сначала соберите её (render).")
        item["status"] = "approved"
        item["issues"] = [i for i in item.get("issues") or [] if not i.startswith("осмотр:")]
    else:
        item["status"] = "needs_review"
        item.setdefault("issues", []).append(f"осмотр: {args.issue}")
    item["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    save_batch(batch)
    contact_sheet(batch)
    say(f"[{item['n']}] {STATUS_RU[item['status']]}" + (f": {args.issue}" if args.issue else ""))
    return {"batch": batch_id, "item": item["n"], "status": item["status"]}

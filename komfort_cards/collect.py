"""Collect the product photos the operator attached in the Codex chat into a new batch (FR-1).

Sources, in order of preference:
1. the latest user message with images in the current Codex session: the original files referenced as
   `local_image` (Codex keeps pasted images in %TEMP%\\codex-clipboard-*.png),
2. the base64 copies of the same images in that message (`input_image`) if the files are gone,
3. the project folder `input/` (manual fallback; files are sorted naturally: 1, 2, ..., 10).
"""

from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from komfort_cards import codex, paths
from komfort_cards.batch import create_batch, save_batch
from komfort_cards.console import CardsError, say

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_DATA_URL = re.compile(r"^data:image/(\w+);base64,(.+)$", re.DOTALL)


class Attachment:
    """One attached image: either a file path or decoded bytes with an extension."""

    def __init__(self, path: Path | None = None, data: bytes | None = None, ext: str = ".png"):
        self.path, self.data, self.ext = path, data, ext.lower()

    def save(self, target_stem: Path) -> Path:
        target = target_stem.with_suffix(self.path.suffix.lower() if self.path else self.ext)
        if self.path:
            shutil.copyfile(self.path, target)
        else:
            target.write_bytes(self.data or b"")
        return target


def _decode_data_url(url: str) -> Attachment | None:
    match = _DATA_URL.match(url or "")
    if not match:
        return None
    kind, payload = match.groups()
    ext = ".jpg" if kind in ("jpeg", "jpg") else f".{kind}"
    return Attachment(data=base64.b64decode(payload), ext=ext)


def attachments_from_rollout(rollout: Path) -> list[Attachment]:
    """Images of the latest user message that has images, in attachment order."""
    last_paths: list[str] = []
    last_urls: list[str] = []
    with rollout.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if '"local_image"' not in line and '"input_image"' not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = rec.get("payload") or {}
            if rec.get("type") == "event_msg" and payload.get("type") == "item_completed":
                item = payload.get("item") or {}
                if item.get("type") == "UserMessage":
                    found = [c.get("path") for c in item.get("content") or [] if c.get("type") == "local_image"]
                    if found:
                        last_paths = [p for p in found if p]
            elif rec.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
                found = [c.get("image_url") for c in payload.get("content") or [] if c.get("type") == "input_image"]
                if found:
                    last_urls = [u for u in found if u]

    files = [Path(p) for p in last_paths]
    if files and all(f.is_file() for f in files):
        return [Attachment(path=f) for f in files]
    if last_urls and (not files or len(last_urls) == len(files)):
        decoded = [_decode_data_url(u) for u in last_urls]
        if all(decoded):
            return decoded  # type: ignore[return-value]
    if files:
        missing = [str(f) for f in files if not f.is_file()]
        raise CardsError("Codex удалил временные файлы вложений, а копий в журнале не нашлось.",
                         hint="положите фото в папку input/ и выполните collect --from-input",
                         data={"missing": missing})
    return []


def _natural_key(path: Path) -> list[Any]:
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", path.name)]


def attachments_from_input() -> list[Attachment]:
    if not paths.INPUT_DIR.is_dir():
        return []
    files = sorted((p for p in paths.INPUT_DIR.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES), key=_natural_key)
    return [Attachment(path=p) for p in files]


def _check_image(path: Path) -> list[int]:
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            return list(img.size)
    except Exception as exc:
        raise CardsError(f"Файл {path.name} не открывается как картинка: {exc}") from exc


def cmd_collect(args) -> dict[str, Any]:
    source = "input"
    attachments: list[Attachment] = []
    if not args.from_input:
        rollout = codex.latest_rollout()
        if rollout:
            attachments = attachments_from_rollout(rollout)
            source = "codex"
    if not attachments:
        attachments = attachments_from_input()
        source = "input"
    if not attachments:
        raise CardsError("Не вижу фото товаров.",
                         hint="прикрепите фото в этот чат ещё раз или положите их в папку input/ и повторите")

    table = None
    if args.table_index:
        if not 1 <= args.table_index <= len(attachments):
            raise CardsError(f"--table-index {args.table_index} вне диапазона 1..{len(attachments)}.")
        table = attachments.pop(args.table_index - 1)
    if args.count and args.count != len(attachments):
        raise CardsError(f"Фото товаров: {len(attachments)}, а ожидалось {args.count} (по числу строк таблицы).",
                         hint="проверьте, все ли фото прикреплены, и нет ли лишних",
                         data={"photos": len(attachments), "expected": args.count})

    batch = create_batch(len(attachments), batch_id=args.batch, label=args.label,
                         table_source="screenshot" if table else "xlsx")
    batch_id = batch["batch_id"]
    work = paths.work_dir(batch_id)
    photos = []
    for item, attachment in zip(batch["items"], attachments):
        saved = attachment.save(work / "photos" / f"{item['n']:02d}")
        size = _check_image(saved)
        item["photo"] = saved.relative_to(paths.batch_dir(batch_id)).as_posix()
        photos.append({"n": item["n"], "photo": item["photo"], "size": size,
                       "from": str(attachment.path) if attachment.path else "base64"})
        say(f"[{item['n']}] {item['photo']}  {size[0]}×{size[1]}")
    if table:
        saved = table.save(work / "table")
        batch["table_file"] = saved.relative_to(paths.batch_dir(batch_id)).as_posix()
        say(f"Таблица: {batch['table_file']}")
    if source == "input":
        done = paths.INPUT_DIR / "_collected" / batch_id
        done.mkdir(parents=True, exist_ok=True)
        for attachment in attachments + ([table] if table else []):
            if attachment.path and attachment.path.parent == paths.INPUT_DIR:
                shutil.move(str(attachment.path), done / attachment.path.name)
    save_batch(batch)
    say(f"Партия {batch_id}: фото {len(photos)} (источник: {'чат Codex' if source == 'codex' else 'папка input'}).")
    return {"batch": batch_id, "source": source, "photos": photos, "table": batch.get("table_file")}

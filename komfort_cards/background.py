"""Take a Codex-generated background for an item, trim service borders and normalise it to 1080x1350 (FR-5)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from komfort_cards import codex, paths
from komfort_cards.batch import load_batch, require_confirmed, resolve_batch_id, save_batch
from komfort_cards.console import CardsError, say
from komfort_cards.prompts import item_mode
from komfort_cards.render import CANVAS

BORDER_MAX_PX = 4     # earlier generations came out 1122x1402 with a 1px frame
BORDER_TOLERANCE = 6.0


def trim_uniform_border(img: Image.Image, max_px: int = BORDER_MAX_PX, tol: float = BORDER_TOLERANCE) -> Image.Image:
    """Strip up to `max_px` uniform lines per side that differ from the picture next to them (a drawn frame)."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    top, bottom, left, right = 0, arr.shape[0], 0, arr.shape[1]

    def is_frame(line: np.ndarray, inner: np.ndarray) -> bool:
        return line.std(axis=0).max() < tol and np.abs(line.mean(axis=0) - inner.mean(axis=0)).max() > tol

    for _ in range(max_px):
        if bottom - top > 2 and is_frame(arr[top], arr[top + 1]):
            top += 1
        if bottom - top > 2 and is_frame(arr[bottom - 1], arr[bottom - 2]):
            bottom -= 1
        if right - left > 2 and is_frame(arr[top:bottom, left], arr[top:bottom, left + 1]):
            left += 1
        if right - left > 2 and is_frame(arr[top:bottom, right - 1], arr[top:bottom, right - 2]):
            right -= 1
    return img.crop((left, top, right, bottom))


def cover_resize(img: Image.Image, size: tuple[int, int] = CANVAS) -> Image.Image:
    """Scale to cover `size` and crop the centre (same as CSS object-fit: cover)."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(tw, round(img.width * scale)), max(th, round(img.height * scale))), Image.LANCZOS)
    x0, y0 = (resized.width - tw) // 2, (resized.height - th) // 2
    return resized.crop((x0, y0, x0 + tw, y0 + th))


def normalize_background(src: Path) -> Image.Image:
    with Image.open(src) as img:
        return cover_resize(trim_uniform_border(img.convert("RGB")))


def detect_product(scene: Image.Image) -> dict[str, Any] | None:
    """Where the generated product sits on the 1080x1350 scene (for overlap/size QA). None if not measurable."""
    from komfort_cards import cutout

    if cutout.model_file() is None:
        say("  внимание: модель вырезки не установлена — положение товара на кадре не проверено")
        return None
    box, area = cutout.main_object_box(scene)
    if not box:
        say("  внимание: товар на кадре не найден — проверьте сцену глазами")
        return None
    return {"box": box, "area_ratio": area}


def pick_source(batch: dict[str, Any], explicit: str | None, pick: int | None = None) -> Path:
    if explicit and pick:
        raise CardsError("Укажите либо --file, либо --pick, не оба.")
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise CardsError(f"Файл фона не найден: {explicit}")
        return path
    if pick:
        generations = codex.chat_generations()
        if not 1 <= pick <= len(generations):
            raise CardsError(f"В этом чате нет генерации №{pick} (всего {len(generations)}).",
                             hint="посмотрите номера: cards generations")
        return generations[pick - 1]  # an explicit operator choice may reuse an image on purpose
    candidates = codex.generated_images()
    if not candidates:
        raise CardsError("Не нашёл сгенерированных Codex картинок.",
                         hint="сгенерируйте фон по промпту (cards prompt N) или укажите файл: --file <путь>")
    newest = candidates[0]
    used = {i.get("background", {}).get("source") for i in batch["items"] if isinstance(i.get("background"), dict)}
    if str(newest) in used:
        raise CardsError("Самая новая генерация уже использована для другой позиции.",
                         hint="сначала сгенерируйте фон для этой позиции, затем повторите команду")
    return newest


def cmd_generations(args) -> dict[str, Any]:
    """Number this chat's generated images (No.1 = first) so the operator can say "take the first background"."""
    generations = codex.chat_generations()
    if not generations:
        say("В этом чате ещё нет сгенерированных картинок.")
    used: dict[str, int] = {}
    if args.batch or paths.OUTPUT_DIR.is_dir():
        try:
            batch = load_batch(resolve_batch_id(args.batch))
            used = {i["background"]["source"]: i["n"] for i in batch["items"] if isinstance(i.get("background"), dict)}
        except CardsError:
            pass
    rows = []
    for k, path in enumerate(generations, start=1):
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M:%S")
        note = f"  ← фон позиции {used[str(path)]}" if str(path) in used else ""
        say(f"№{k}  {stamp}  {path.name}{note}")
        rows.append({"k": k, "time": stamp, "path": str(path), "used_by": used.get(str(path))})
    return {"generations": rows}


def cmd_background(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    require_confirmed(batch)
    item = next((i for i in batch["items"] if i["n"] == args.item), None)
    if item is None:
        raise CardsError(f"В партии нет позиции {args.item}.")
    src = pick_source(batch, args.file, getattr(args, "pick", None))
    out_dir = paths.work_dir(batch_id) / "backgrounds"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{int(item['n']):02d}"
    target = out_dir / f"{name}.png"
    if target.exists():  # keep previous attempts: NN_try1.png, NN_try2.png ...
        k = 1
        while (out_dir / f"{name}_try{k}.png").exists():
            k += 1
        target.rename(out_dir / f"{name}_try{k}.png")
    with Image.open(src) as original:
        original_size = list(original.size)
    scene_img = normalize_background(src)
    scene_img.save(target, optimize=True)
    item.setdefault("files", {})["background"] = f"_work/backgrounds/{name}.png"
    item["background"] = {"source": str(src), "original_size": original_size,
                          "taken_at": datetime.now().isoformat(timespec="seconds")}
    item["scene"] = detect_product(scene_img) if item_mode(item) == "scene" else None
    if item.get("status") in ("planned", "cut"):
        item["status"] = "bg_ready"
    save_batch(batch)
    scene = item.get("scene") or {}
    where = f", товар занимает {scene['area_ratio']:.0%} кадра" if scene.get("area_ratio") else ""
    say(f"[{item['n']}] кадр взят из {src.name} ({original_size[0]}×{original_size[1]}) → {item['files']['background']}{where}")
    return {"batch": batch_id, "item": item["n"], "background": item["files"]["background"], "source": str(src),
            "scene": item.get("scene")}

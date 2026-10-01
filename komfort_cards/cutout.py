"""Cut products out of white-background photos (FR-4): rembg `isnet-general-use` + edge clean-up.

The product pixels are never redrawn: only an alpha mask is computed, the white fringe on semi-transparent
edges is un-blended, tiny islands are dropped and the result is trimmed to the product.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from komfort_cards import paths
from komfort_cards.batch import load_batch, require_confirmed, resolve_batch_id, save_batch
from komfort_cards.console import CardsError, say

MODEL = "isnet-general-use"
MODELS_DIR = paths.PROJECT_ROOT / ".models"
MIN_ISLAND_SHARE = 0.002     # drop components smaller than 0.2% of the image
MAX_ISLANDS = 3              # more separate pieces than this -> needs review
COVERAGE_RANGE = (0.03, 0.95)
TRIM_PADDING = 0.02


def model_file() -> Path | None:
    """The downloaded model; rembg's layout under U2NET_HOME differs between versions, so search for it."""
    return next(MODELS_DIR.rglob(f"{MODEL}.onnx"), None) if MODELS_DIR.is_dir() else None


def _session():
    os.environ.setdefault("U2NET_HOME", str(MODELS_DIR))  # keep the model inside the project folder
    try:
        from rembg import new_session
    except ImportError as exc:  # pragma: no cover - environment problem
        raise CardsError("Не установлен модуль вырезки (rembg).", hint="запустите УСТАНОВКА.bat") from exc
    try:
        return new_session(MODEL)
    except Exception as exc:  # download / onnxruntime problems
        raise CardsError(f"Не удалось загрузить модель вырезки {MODEL}: {exc}",
                         hint="проверьте интернет и запустите УСТАНОВКА.bat ещё раз") from exc


# --------------------------------------------------------------------------- pure post-processing

def remove_islands(alpha: np.ndarray) -> tuple[np.ndarray, int]:
    """Zero out connected components below MIN_ISLAND_SHARE; returns (alpha, number of kept components)."""
    from scipy import ndimage

    mask = alpha > 127
    labels, count = ndimage.label(mask)
    if count == 0:
        return alpha, 0
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    keep = np.flatnonzero(sizes >= MIN_ISLAND_SHARE * alpha.size) + 1
    if keep.size == 0:
        keep = np.array([int(np.argmax(sizes)) + 1])
    # keep soft edges around kept components: grow the kept mask a little before applying it
    kept = ndimage.binary_dilation(np.isin(labels, keep), iterations=3)
    return np.where(kept, alpha, 0).astype(np.uint8), int(keep.size)


def solidify(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Make the product body opaque where the model is unsure.

    On flat, untextured white products the model returns a half-transparent mask, so the product would let
    the background show through. Inside the (slightly grown) silhouette every pixel that is darker than the
    pure-white photo background becomes opaque; true see-through holes stay transparent because the photo
    shows pure white there.
    """
    from scipy import ndimage

    silhouette = ndimage.binary_dilation(alpha > 24, iterations=2)
    darkness = 250.0 - rgb.min(axis=2).astype(np.float32)   # <= 0 on the white photo background
    color_alpha = np.clip(darkness * 25.5, 0, 255)           # 10 levels below white -> fully opaque
    return np.where(silhouette, np.maximum(alpha, color_alpha), alpha).astype(np.uint8)


def decontaminate(rgb: np.ndarray, alpha: np.ndarray, background: float = 255.0) -> np.ndarray:
    """Un-blend the white photo background from semi-transparent edge pixels: fg = (obs - (1-a)*bg) / a."""
    a = alpha.astype(np.float32)[..., None] / 255.0
    edge = (a > 0.04) & (a < 0.98)
    fg = (rgb.astype(np.float32) - (1.0 - a) * background) / np.maximum(a, 1e-3)
    out = np.where(edge, np.clip(fg, 0, 255), rgb.astype(np.float32))
    return out.astype(np.uint8)


def trim(rgba: Image.Image, padding: float = TRIM_PADDING) -> tuple[Image.Image, tuple[int, int, int, int] | None]:
    bbox = rgba.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bbox:
        return rgba, None
    pad = int(round(max(rgba.size) * padding))
    x0, y0, x1, y1 = bbox
    box = (max(0, x0 - pad), max(0, y0 - pad), min(rgba.width, x1 + pad), min(rgba.height, y1 + pad))
    return rgba.crop(box), bbox


def postprocess(photo: Image.Image, mask: Image.Image) -> tuple[Image.Image, dict[str, Any]]:
    rgb = np.asarray(photo.convert("RGB"))
    alpha = np.asarray(mask.convert("L").resize(photo.size, Image.LANCZOS))
    alpha = solidify(rgb, alpha)
    # erode 1px: removes the thin white rim rembg masks tend to keep on white backgrounds
    alpha = np.asarray(Image.fromarray(alpha).filter(ImageFilter.MinFilter(3)))
    alpha, islands = remove_islands(alpha)
    rgb = decontaminate(rgb, alpha)
    rgba = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    trimmed, bbox = trim(rgba)
    coverage = float((alpha > 127).mean())
    w, h = photo.size
    touches = bool(bbox) and (bbox[0] <= 2 or bbox[1] <= 2 or bbox[2] >= w - 2 or bbox[3] >= h - 2)
    metrics = {"coverage": round(coverage, 4), "islands": islands, "bbox": list(bbox) if bbox else None,
               "touches_edge": touches, "size": list(trimmed.size)}
    return trimmed, metrics


def review_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons = []
    lo, hi = COVERAGE_RANGE
    if metrics["bbox"] is None:
        reasons.append("вырезка пустая — товар не найден на фото")
    elif not lo <= metrics["coverage"] <= hi:
        reasons.append(f"подозрительная площадь вырезки ({metrics['coverage']:.0%}) — проверьте NN_check.jpg")
    if metrics["islands"] > MAX_ISLANDS:
        reasons.append(f"вырезка распалась на {metrics['islands']} частей")
    if metrics["touches_edge"]:
        reasons.append("товар касается края исходного фото — возможно, он обрезан на исходнике")
    return reasons


def checker_preview(rgba: Image.Image) -> Image.Image:
    """Cut-out on a dark checkerboard: white fringes and holes are easy to see."""
    w, h = rgba.size
    tile = 24
    yy, xx = np.mgrid[0:h, 0:w]
    board = np.where(((xx // tile) + (yy // tile)) % 2 == 0, 38, 58).astype(np.uint8)
    bg = Image.fromarray(np.dstack([board, board, board]), "RGB").convert("RGBA")
    bg.alpha_composite(rgba)
    return bg.convert("RGB")


# --------------------------------------------------------------------------- commands

def crop_relative(photo: Image.Image, crop: list[float] | None) -> Image.Image:
    """Optional `photo_crop` [x0, y0, x1, y1] in fractions of the photo: isolates the product when the photo
    also shows a box, a second item or an infographic block."""
    if not crop:
        return photo
    x0, y0, x1, y1 = (float(v) for v in crop)
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise CardsError(f"photo_crop {crop} должен быть [x0, y0, x1, y1] в долях 0..1 с x0<x1, y0<y1.")
    w, h = photo.size
    return photo.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))


def cut_photo(session, photo_path: Path, crop: list[float] | None = None) -> tuple[Image.Image, dict[str, Any]]:
    from rembg import remove

    with Image.open(photo_path) as src:
        photo = crop_relative(src.convert("RGB"), crop)
    mask = remove(photo, session=session, only_mask=True, post_process_mask=True)
    return postprocess(photo, mask)


def cmd_cutout(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    require_confirmed(batch)
    wanted = set(args.items or [])
    items = [i for i in batch["items"] if not wanted or i["n"] in wanted]
    root = paths.batch_dir(batch_id)
    out_dir = paths.work_dir(batch_id) / "cutouts"
    out_dir.mkdir(parents=True, exist_ok=True)
    session = _session()
    results = []
    for item in items:
        photo = root / item["photo"]
        cut, metrics = cut_photo(session, photo, item.get("photo_crop"))
        name = f"{int(item['n']):02d}"
        cut.save(out_dir / f"{name}.png", optimize=True)
        checker_preview(cut).save(out_dir / f"{name}_check.jpg", quality=88)
        item.setdefault("files", {})["cutout"] = f"_work/cutouts/{name}.png"
        item["cutout"] = metrics
        reasons = review_reasons(metrics)
        item["issues"] = [i for i in item.get("issues", []) if not i.startswith("вырезка:")] + [f"вырезка: {r}" for r in reasons]
        if item.get("status") != "blocked":
            item["status"] = "needs_review" if reasons else "cut"
        say(f"[{item['n']}] вырезка {cut.size[0]}×{cut.size[1]}, площадь {metrics['coverage']:.0%}"
            + (f"  ВНИМАНИЕ: {'; '.join(reasons)}" if reasons else ""))
        results.append({"n": item["n"], "cutout": item["files"]["cutout"], "check": f"_work/cutouts/{name}_check.jpg",
                        "review": reasons})
    save_batch(batch)
    return {"batch": batch_id, "items": results}


def cmd_setup_models(args) -> dict[str, Any]:
    """Download the model (first run) and prove onnxruntime works on the selftest product pasted on white."""
    from rembg import remove

    session = _session()
    with Image.open(paths.SELFTEST_DIR / "product.png") as img:
        photo = Image.new("RGB", (img.width + 80, img.height + 80), "white")
        photo.paste(img, (40, 40), mask=img.getchannel("A"))
    _, metrics = postprocess(photo, remove(photo, session=session, only_mask=True, post_process_mask=True))
    if review_reasons(metrics):
        raise CardsError("Модель вырезки работает неправильно на тестовом изображении.",
                         hint="пришлите setup.log разработчику", data={"metrics": metrics})
    say(f"Модель вырезки готова ({MODEL}), проверка пройдена: площадь {metrics['coverage']:.0%}")
    return {"model": MODEL, "dir": str(MODELS_DIR), "metrics": metrics}

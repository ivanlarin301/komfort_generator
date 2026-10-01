"""Render cards: batch item -> HTML page from templates/<template>/card.html -> 1080x1350 PNG (FR-6, FR-7, FR-8).

The page is opened by Playwright through the system Microsoft Edge (no browser download), falling back to
Chrome and then to Playwright's own Chromium. The template reports element boxes and fitted font sizes in
`window.__metrics`; they are stored in batch.json for QA.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from komfort_cards import paths
from komfort_cards.batch import load_batch, require_confirmed, resolve_batch_id, save_batch
from komfort_cards.console import CardsError, say
from komfort_cards.formatting import format_price

CANVAS = (1080, 1350)
READY_TIMEOUT_MS = 30_000
BROWSER_ARGS = ["--allow-file-access-from-files", "--disable-gpu", "--hide-scrollbars"]
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\s]+')


def file_url(path: Path) -> str:
    return path.resolve().as_uri()


def template_dir(template: str) -> Path:
    path = paths.TEMPLATES_DIR / template
    if not (path / "card.html").is_file():
        raise CardsError(f"Шаблон «{template}» не найден в {paths.TEMPLATES_DIR}.")
    return path


LIGHT_BACKGROUND = 0.40  # mean luminance above which the legibility gradients are strengthened
TITLE_ZONE = (0, 60, 1080, 330)
FOOTER_ZONE = (440, 1060, 1080, 1290)


def background_shade(path: Path | None) -> dict[str, bool]:
    """Which legibility gradients to strengthen: light generated backgrounds must not wash out white text."""
    if not path or not path.is_file():
        return {"top": False, "bottom": False}
    from PIL import Image, ImageStat

    with Image.open(path) as img:
        gray = img.convert("L").resize(CANVAS)
    lum = lambda box: ImageStat.Stat(gray.crop(box)).mean[0] / 255  # noqa: E731
    return {"top": lum(TITLE_ZONE) > LIGHT_BACKGROUND, "bottom": lum(FOOTER_ZONE) > LIGHT_BACKGROUND}


def load_icons() -> dict[str, Path]:
    """Icon key -> SVG file from config/icons.yaml (FR-15)."""
    path = paths.CONFIG_DIR / "icons.yaml"
    if not path.is_file():
        return {}
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {key: paths.ICONS_DIR / spec["file"] for key, spec in (data.get("icons") or {}).items()}


def frame_transform(layout: dict[str, Any]) -> tuple[float, float]:
    """Clamp bg_zoom (1..1.4) and bg_shift_y so the scaled scene still covers the whole canvas (no empty strips)."""
    zoom = min(1.4, max(1.0, float(layout.get("bg_zoom") or 1.0)))
    overflow = CANVAS[1] * (zoom - 1) / 2
    shift = min(overflow, max(-overflow, float(layout.get("bg_shift_y") or 0)))
    return zoom, shift


def displayed_box(box: list[int], zoom: float, shift: float) -> list[int]:
    """Where a scene-space box lands after the centre zoom and vertical shift."""
    cx, cy = CANVAS[0] / 2, CANVAS[1] / 2
    x0, y0, x1, y1 = box
    return [round((x0 - cx) * zoom + cx), round((y0 - cy) * zoom + cy + shift),
            round((x1 - cx) * zoom + cx), round((y1 - cy) * zoom + cy + shift)]


def card_data(batch: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Template input for one item; image paths become file:// URLs."""
    root = paths.batch_dir(batch["batch_id"])
    files = item.get("files") or {}
    texts = item.get("texts") or {}

    def url(rel: str | None) -> str | None:
        return file_url(root / rel) if rel and (root / rel).is_file() else None

    background = root / files["background"] if files.get("background") else None
    plate = texts.get("plate")
    if isinstance(plate, dict) and plate.get("value"):
        plate = {"value": plate["value"], "label": plate.get("label") or "",
                 "style": plate.get("style") or "green", "plus": plate.get("plus", True)}
    else:
        plate = None
    layout = dict(item.get("layout") or {})
    composite = layout.get("mode") == "composite"
    zoom, shift = frame_transform(layout)
    scene_box = None
    if not composite and isinstance(item.get("scene"), dict) and item["scene"].get("box"):
        scene_box = displayed_box(item["scene"]["box"], zoom, shift)
    icons = load_icons()
    features = []
    for feature in texts.get("features") or []:
        if isinstance(feature, dict) and feature.get("text"):
            icon = icons.get(feature.get("icon") or "")
            features.append({"text": feature["text"], "icon_url": file_url(icon) if icon and icon.is_file() else None})
    return {
        "title": texts.get("title") or "",
        "title_accent": texts.get("title_accent") or None,
        "subtitle": texts.get("subtitle") or "",
        "badge": list(texts.get("badge") or []),
        "plate": plate,
        "features": features,
        "features_layout": texts.get("features_layout") or "row",
        "code": item.get("code") or "",
        "price": format_price(item.get("price"), space=" "),
        "background": url(files.get("background")),
        "product": url(files.get("cutout")) if composite else None,  # scene mode: the product is in the photo
        "scene_box": scene_box,
        "bg_zoom": zoom,
        "bg_shift_y": shift,
        "logo": file_url(paths.LOGO_FILE) if paths.LOGO_FILE.is_file() else None,
        "layout": layout,
        "shade": background_shade(background),
    }


def build_html(template: str, data: dict[str, Any]) -> str:
    tdir = template_dir(template)
    html = (tdir / "card.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("<!--BASE-->", f'<base href="{file_url(tdir)}/">')
    return html.replace("<!--DATA-->", f'<script id="card-data" type="application/json">{payload}</script>')


def output_name(item: dict[str, Any]) -> str:
    code = _UNSAFE_NAME.sub("-", str(item.get("code") or "без-кода")).strip("-")
    return f"{int(item['n']):02d}_{code}"


def next_free(path: Path) -> Path:
    """Never overwrite a card (FR-8): 01_code.png -> 01_code_v2.png -> ..."""
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem}_v{n}{path.suffix}")).exists():
        n += 1
    return candidate


@contextmanager
def browser_page() -> Iterator[Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment problem
        raise CardsError("Не установлен Playwright.", hint="запустите УСТАНОВКА.bat") from exc
    with sync_playwright() as pw:
        browser, last_error = None, None
        for options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = pw.chromium.launch(args=BROWSER_ARGS, **options)
                break
            except PlaywrightError as exc:
                last_error = exc
        if browser is None:
            raise CardsError("Не найден браузерный движок для рендера (Edge/Chrome).",
                              hint="запустите УСТАНОВКА.bat — он поставит движок") from last_error
        try:
            page = browser.new_page(viewport={"width": CANVAS[0], "height": CANVAS[1]}, device_scale_factor=1)
            yield page
        finally:
            browser.close()


def render_html_file(page: Any, html_path: Path, out_png: Path) -> dict[str, Any]:
    page.goto(file_url(html_path))
    page.wait_for_function("window.__ready === true", timeout=READY_TIMEOUT_MS)
    metrics = page.evaluate("window.__metrics")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    page.locator("#card").screenshot(path=str(out_png))
    return metrics


def render_item(page: Any, batch: dict[str, Any], item: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    batch_id = batch["batch_id"]
    data = card_data(batch, item)
    html_path = paths.work_dir(batch_id) / "html" / f"{int(item['n']):02d}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(build_html(batch.get("template") or "stroyka", data), encoding="utf-8")
    out_png = next_free(paths.batch_dir(batch_id) / f"{output_name(item)}.png")
    metrics = render_html_file(page, html_path, out_png)
    return out_png, metrics


def cmd_render(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    require_confirmed(batch)
    wanted = set(args.items or [])
    items = [i for i in batch["items"] if not wanted or i["n"] in wanted]
    if not items:
        raise CardsError("Нет позиций с такими номерами.", data={"items": sorted(wanted)})

    rendered = []
    with browser_page() as page:
        for item in items:
            out_png, metrics = render_item(page, batch, item)
            rel = out_png.relative_to(paths.batch_dir(batch_id)).as_posix()
            item.setdefault("files", {})["card"] = rel
            item["render"] = metrics
            if item.get("status") not in ("blocked",):
                item["status"] = "rendered"
            warn = "; ".join(metrics.get("warnings") or [])
            say(f"[{item['n']}] {rel}" + (f"  (внимание: {warn})" if warn else ""))
            rendered.append({"n": item["n"], "card": rel, "warnings": metrics.get("warnings") or []})
    save_batch(batch)
    try:
        from komfort_cards import qa  # QA is optional until TSK-008 lands
    except ImportError:
        qa = None
    report = qa.check_batch(batch, items) if qa else None
    say(f"Готово карточек: {len(rendered)}. Папка: {paths.batch_dir(batch_id)}")
    return {"batch": batch_id, "rendered": rendered, "qa": report}

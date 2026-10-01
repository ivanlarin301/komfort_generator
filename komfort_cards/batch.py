"""Batch data (`output/<batch>/batch.json`): model, normalisation, validation and the operator summary.

Codex fills the items (codes, prices, texts with sources); `check` validates and prints the summary the
operator confirms (FR-2), `confirm` unlocks the generation steps.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from komfort_cards import paths
from komfort_cards.console import CardsError, say
from komfort_cards.formatting import format_price, normalize_code, normalize_price

BATCH_FILE = "batch.json"
TEMPLATE = "stroyka"
STATUSES = ("planned", "cut", "bg_ready", "rendered", "approved", "needs_review", "blocked")
SOURCES = ("table", "packaging", "komfort.kz", "knowledge")
TABLE_SOURCES = ("screenshot", "xlsx")
SUBTITLE_STYLES = ("badge", "line")
FEATURE_LAYOUTS = ("row", "column")
WORK_SUBDIRS = ("photos", "cutouts", "backgrounds", "html")

LIMITS = {"title": 40, "subtitle": 40, "badge_line": 60, "plate_value": 12, "plate_label": 20, "feature": 24, "features": 3}
_DIGIT = re.compile(r"\d")
_LABEL_CLEAN = re.compile(r"[^\w\-]+", re.UNICODE)


@dataclass(frozen=True)
class Issue:
    item: int | None
    field: str
    message: str
    severity: str = "error"  # error blocks confirm/render; warning is informational

    def text(self) -> str:
        where = f"позиция {self.item}" if self.item else "партия"
        return f"[{'ОШИБКА' if self.severity == 'error' else 'внимание'}] {where}, {self.field}: {self.message}"


# --------------------------------------------------------------------------- ids and files

def new_batch_id(label: str | None = None, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M")
    slug = _LABEL_CLEAN.sub("-", (label or "").strip()).strip("-_")[:32]
    base = f"{stamp}_{slug}" if slug else stamp
    candidate, n = base, 2
    while paths.batch_dir(candidate).exists():
        candidate, n = f"{base}_{n}", n + 1
    return candidate


def list_batch_ids() -> list[str]:
    if not paths.OUTPUT_DIR.is_dir():
        return []
    return sorted(
        d.name for d in paths.OUTPUT_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / BATCH_FILE).is_file()
    )


def resolve_batch_id(batch_id: str | None) -> str:
    if batch_id:
        if not (paths.batch_dir(batch_id) / BATCH_FILE).is_file():
            raise CardsError(f"Партия «{batch_id}» не найдена.", hint="посмотрите список партий: cards.cmd list")
        return batch_id
    ids = list_batch_ids()
    if not ids:
        raise CardsError("Ещё нет ни одной партии.", hint="начните с команды collect (фото из чата)")
    return ids[-1]


def batch_path(batch_id: str) -> Path:
    return paths.batch_dir(batch_id) / BATCH_FILE


def load_batch(batch_id: str) -> dict[str, Any]:
    path = batch_path(batch_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CardsError(f"batch.json повреждён: {exc}", hint=f"исправьте JSON (строка {exc.lineno})") from exc
    data["batch_id"] = batch_id
    return data


def save_batch(batch: dict[str, Any]) -> Path:
    path = batch_path(batch["batch_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)  # atomic: an interrupted write never leaves a half-written batch.json
    return path


def empty_item(n: int) -> dict[str, Any]:
    return {
        "n": n, "code": "", "name": "", "price": "", "category": "", "photo": "", "photo_note": "",
        "texts": {"title": "", "badge": [], "plate": None, "features": []},
        "sources": {}, "layout": {}, "status": "planned", "issues": [], "files": {},
    }


def create_batch(rows: int, *, batch_id: str | None = None, label: str | None = None,
                 table_source: str = "screenshot") -> dict[str, Any]:
    if rows < 1:
        raise CardsError("В партии должна быть хотя бы одна позиция.")
    batch_id = batch_id or new_batch_id(label)
    root = paths.batch_dir(batch_id)
    if (root / BATCH_FILE).exists():
        raise CardsError(f"Партия «{batch_id}» уже существует.", hint="выберите другое имя или не указывайте --batch")
    for sub in WORK_SUBDIRS:
        (paths.work_dir(batch_id) / sub).mkdir(parents=True, exist_ok=True)
    batch = {
        "batch_id": batch_id,
        "template": TEMPLATE,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "table_source": table_source,
        "confirmed": False,
        "items": [empty_item(n) for n in range(1, rows + 1)],
    }
    save_batch(batch)
    return batch


# --------------------------------------------------------------------------- normalisation

def normalize_batch(batch: dict[str, Any]) -> bool:
    """Coerce values Codex may write loosely (numbers for codes/prices, a string badge). Returns True if changed."""
    before = json.dumps(batch, ensure_ascii=False, sort_keys=True)
    for item in batch.get("items", []):
        item["code"] = normalize_code(item.get("code"))
        price = item.get("price")
        if price not in (None, ""):
            try:
                item["price"] = normalize_price(price)
            except ValueError:
                item["price"] = str(price)  # keep as is; validation reports it
        texts = item.setdefault("texts", {})
        if isinstance(texts.get("badge"), str):
            texts["badge"] = [texts["badge"]] if texts["badge"].strip() else []
        for key in ("title", "subtitle", "title_accent"):
            if isinstance(texts.get(key), str):
                texts[key] = texts[key].strip()
        item.setdefault("sources", {})
        item.setdefault("layout", {})
        item.setdefault("issues", [])
        item.setdefault("files", {})
        item.setdefault("status", "planned")
    return json.dumps(batch, ensure_ascii=False, sort_keys=True) != before


# --------------------------------------------------------------------------- validation

def _known_keys(config_name: str) -> set[str] | None:
    """Category / icon keys from config/*.yaml; None if the config is not present yet."""
    path = paths.CONFIG_DIR / config_name
    if not path.is_file():
        return None
    import yaml  # local import: only needed when the config exists

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get("categories") or data.get("icons") or {}
    return set(section)


def validate_batch(batch: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    items = batch.get("items") or []
    if not items:
        return [Issue(None, "items", "в партии нет позиций")]
    if batch.get("table_source") not in TABLE_SOURCES:
        issues.append(Issue(None, "table_source", f"ожидается одно из {TABLE_SOURCES}", "warning"))
    categories = _known_keys("scenes.yaml")
    icons = _known_keys("icons.yaml")
    root = paths.batch_dir(batch["batch_id"])

    for index, item in enumerate(items, start=1):
        n = item.get("n")
        if n != index:
            issues.append(Issue(index, "n", f"номер {n!r}, ожидается {index} (порядок = порядок фото)"))
        issues.extend(_validate_item(index, item, root, categories, icons))
    return issues


def _validate_item(n: int, item: dict[str, Any], root: Path, categories: set[str] | None,
                   icons: set[str] | None) -> list[Issue]:
    out: list[Issue] = []

    def err(field: str, message: str, severity: str = "error") -> None:
        out.append(Issue(n, field, message, severity))

    if not item.get("code"):
        err("code", "нет кода товара — спросите оператора, не придумывайте")
    if item.get("price") in (None, ""):
        err("price", "нет цены — спросите оператора, не придумывайте")
    else:
        try:
            normalize_price(item["price"])
        except ValueError as exc:
            err("price", str(exc))
    if not str(item.get("name") or "").strip():
        err("name", "нет названия из таблицы")
    category = item.get("category")
    if not category:
        err("category", "не выбрана категория фона")
    elif categories is not None and category not in categories:
        err("category", f"неизвестная категория «{category}», есть: {', '.join(sorted(categories))}")
    photo = item.get("photo")
    if not photo:
        err("photo", "не указано фото")
    elif not (root / photo).is_file():
        err("photo", f"файл не найден: {photo}")
    if item.get("status") not in STATUSES:
        err("status", f"неизвестный статус {item.get('status')!r}")

    texts = item.get("texts") or {}
    title = texts.get("title") or ""
    if not title:
        err("texts.title", "нет заголовка")
    elif len(title) > LIMITS["title"]:
        err("texts.title", f"длиннее {LIMITS['title']} символов ({len(title)}) — сократите")
    accent = texts.get("title_accent")
    if accent and accent.casefold() not in title.casefold():
        err("texts.title_accent", "акцент должен быть частью заголовка")
    style = texts.get("subtitle_style", "badge")
    if style not in SUBTITLE_STYLES:
        err("texts.subtitle_style", f"ожидается одно из {SUBTITLE_STYLES}")
    subtitle = texts.get("subtitle") or ""
    if len(subtitle) > LIMITS["subtitle"]:
        err("texts.subtitle", f"длиннее {LIMITS['subtitle']} символов")
    badge = texts.get("badge") or []
    if not isinstance(badge, list) or len(badge) > 2:
        err("texts.badge", "белая плашка — список из 1–2 строк")
    else:
        for line in badge:
            if len(str(line)) > LIMITS["badge_line"]:
                err("texts.badge", f"строка длиннее {LIMITS['badge_line']} символов")
    if style == "line" and not subtitle:
        err("texts.subtitle", "выбран подзаголовок-строка, но текст пустой")
    plate = texts.get("plate")
    if plate:
        if not isinstance(plate, dict) or not plate.get("value"):
            err("texts.plate", "плашка — объект {value, label} с непустым value")
        else:
            if len(str(plate["value"])) > LIMITS["plate_value"]:
                err("texts.plate", f"значение длиннее {LIMITS['plate_value']} символов")
            if len(str(plate.get("label") or "")) > LIMITS["plate_label"]:
                err("texts.plate", f"подпись длиннее {LIMITS['plate_label']} символов")
    features = texts.get("features") or []
    if len(features) > LIMITS["features"]:
        err("texts.features", f"не больше {LIMITS['features']} иконок-свойств")
    for feature in features:
        if not isinstance(feature, dict) or not feature.get("text"):
            err("texts.features", "элемент — объект {icon, text}")
            continue
        if len(feature["text"]) > LIMITS["feature"]:
            err("texts.features", f"«{feature['text']}» длиннее {LIMITS['feature']} символов")
        if icons is not None and feature.get("icon") not in icons:
            err("texts.features", f"неизвестная иконка {feature.get('icon')!r}")
    if texts.get("features_layout", "row") not in FEATURE_LAYOUTS:
        err("texts.features_layout", f"ожидается одно из {FEATURE_LAYOUTS}")

    out.extend(_validate_sources(n, texts, item.get("sources") or {}))
    return out


def _filled_text_groups(texts: dict[str, Any]) -> dict[str, str]:
    """Text group -> concatenated content, for groups that are present on the card."""
    groups: dict[str, str] = {}
    if texts.get("title"):
        groups["title"] = texts["title"]
    if texts.get("subtitle"):
        groups["subtitle"] = texts["subtitle"]
    if texts.get("badge"):
        groups["badge"] = " ".join(map(str, texts["badge"]))
    plate = texts.get("plate")
    if isinstance(plate, dict) and plate.get("value"):
        groups["plate"] = f"{plate['value']} {plate.get('label') or ''}"
    if texts.get("features"):
        groups["features"] = " ".join(str(f.get("text", "")) for f in texts["features"] if isinstance(f, dict))
    return groups


def _validate_sources(n: int, texts: dict[str, Any], sources: dict[str, Any]) -> list[Issue]:
    out: list[Issue] = []
    for group, content in _filled_text_groups(texts).items():
        source = sources.get(group)
        if source is None:
            out.append(Issue(n, f"sources.{group}", "не указан источник данных", "warning" if group == "title" else "error"))
            continue
        if source not in SOURCES:
            out.append(Issue(n, f"sources.{group}", f"источник {source!r}, ожидается одно из {SOURCES}"))
        elif source == "knowledge" and _DIGIT.search(content):
            out.append(Issue(n, f"sources.{group}", "числа нельзя брать «из знаний» — только таблица, упаковка или komfort.kz (FR-3)"))
    return out


# --------------------------------------------------------------------------- operator summary

def summary_markdown(batch: dict[str, Any], issues: list[Issue]) -> str:
    by_item: dict[int | None, list[Issue]] = {}
    for issue in issues:
        by_item.setdefault(issue.item, []).append(issue)
    lines = [
        "| № | Что на фото | Код | Название | Цена | Заголовок | Подзаголовок | Плашка |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in batch["items"]:
        texts = item.get("texts") or {}
        try:
            price = f"{format_price(item.get('price'))} ₸"
        except ValueError:
            price = f"⚠ {item.get('price') or 'нет'}"
        plate = texts.get("plate") or {}
        plate_text = f"{plate.get('value', '')} {plate.get('label', '')}".strip() if isinstance(plate, dict) else ""
        subtitle = texts.get("subtitle") if texts.get("subtitle_style") == "line" else " / ".join(texts.get("badge") or [])
        flag = " ⚠" if any(i.severity == "error" for i in by_item.get(item.get("n"), [])) else ""
        cells = [f"{item.get('n')}{flag}", item.get("photo_note") or "—", item.get("code") or "⚠ нет",
                 item.get("name") or "⚠ нет", price, texts.get("title") or "—", subtitle or "—", plate_text or "—"]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


def require_confirmed(batch: dict[str, Any]) -> None:
    if not batch.get("confirmed"):
        raise CardsError(
            "Сводка ещё не подтверждена оператором — генерацию начинать нельзя (FR-2).",
            hint="покажите оператору сводку (check), после его «да» выполните confirm",
        )


# --------------------------------------------------------------------------- commands

def cmd_init(args) -> dict[str, Any]:
    batch = create_batch(args.rows, batch_id=args.batch, label=args.label)
    say(f"Создана партия {batch['batch_id']} на {args.rows} поз.: {paths.batch_dir(batch['batch_id'])}")
    return {"batch": batch["batch_id"], "dir": str(paths.batch_dir(batch["batch_id"])), "rows": args.rows}


def cmd_check(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    if normalize_batch(batch):
        save_batch(batch)
    issues = validate_batch(batch)
    errors = [i for i in issues if i.severity == "error"]
    say(f"Партия {batch_id}: позиций {len(batch['items'])}, подтверждена: {'да' if batch.get('confirmed') else 'нет'}")
    say()
    say(summary_markdown(batch, issues))
    if issues:
        say()
        for issue in issues:
            say(issue.text())
    payload = {
        "batch": batch_id, "items": len(batch["items"]), "confirmed": bool(batch.get("confirmed")),
        "errors": [i.text() for i in errors], "warnings": [i.text() for i in issues if i.severity != "error"],
    }
    if errors:
        raise CardsError(f"В данных партии {len(errors)} ошибок — исправьте batch.json и повторите check.", data=payload)
    return payload


def cmd_confirm(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    normalize_batch(batch)
    errors = [i for i in validate_batch(batch) if i.severity == "error"]
    if errors:
        for issue in errors:
            say(issue.text())
        raise CardsError("Нельзя подтвердить партию с ошибками.", hint="исправьте ошибки и снова выполните check")
    batch["confirmed"] = True
    batch["confirmed_at"] = datetime.now().isoformat(timespec="seconds")
    save_batch(batch)
    say(f"Партия {batch_id} подтверждена оператором. Можно вырезать товары и генерировать фоны.")
    return {"batch": batch_id, "confirmed": True}


def cmd_list(args) -> dict[str, Any]:
    ids = list_batch_ids()
    if not ids:
        say("Партий пока нет.")
    rows = []
    for batch_id in ids:
        batch = load_batch(batch_id)
        statuses: dict[str, int] = {}
        for item in batch.get("items", []):
            statuses[item.get("status", "?")] = statuses.get(item.get("status", "?"), 0) + 1
        summary = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
        say(f"{batch_id}  — позиций {len(batch.get('items', []))} ({summary})")
        rows.append({"batch": batch_id, "items": len(batch.get("items", [])), "statuses": statuses})
    return {"batches": rows}

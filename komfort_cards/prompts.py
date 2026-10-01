"""Background prompts from config/scenes.yaml (FR-5): one fixed recipe per product category."""

from __future__ import annotations

from typing import Any

import yaml

from komfort_cards import paths
from komfort_cards.batch import load_batch, resolve_batch_id
from komfort_cards.console import CardsError, say

SCENES_FILE = "scenes.yaml"


def load_scenes() -> dict[str, Any]:
    path = paths.CONFIG_DIR / SCENES_FILE
    if not path.is_file():
        raise CardsError(f"Нет файла сцен {path}.", hint="обновите систему (ОБНОВЛЕНИЕ.bat)")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not data.get("categories") or not data.get("style") or not data.get("bans"):
        raise CardsError(f"В {path} должны быть style, bans и categories.")
    return data


def build_prompt(category: str, scenes: dict[str, Any] | None = None) -> str:
    scenes = scenes or load_scenes()
    recipe = scenes["categories"].get(category)
    if recipe is None:
        known = ", ".join(sorted(scenes["categories"]))
        raise CardsError(f"Неизвестная категория «{category}».", hint=f"выберите одну из: {known}")
    style = " ".join(scenes["style"].split()).format(scene=recipe["scene"].rstrip("."), surface=recipe["surface"])
    return f"{style} {' '.join(scenes['bans'].split())}"


def cmd_prompt(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    item = next((i for i in batch["items"] if i["n"] == args.item), None)
    if item is None:
        raise CardsError(f"В партии нет позиции {args.item}.")
    category = item.get("category") or "default"
    prompt = build_prompt(category)
    say(f"Промпт фона для позиции {args.item} (категория {category}). Передайте его генерации без изменений смысла:")
    say()
    say(prompt)
    return {"batch": batch_id, "item": args.item, "category": category, "prompt": prompt}

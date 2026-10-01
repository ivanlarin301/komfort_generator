"""Image prompts from config/scenes.yaml (FR-4, FR-5).

Main mode "scene" (design D1-v2): the product is generated inside the scene from the operator's photo used as
a reference. Fallback "composite": an empty background; the template places the cut-out product on it.
"""

from __future__ import annotations

from typing import Any

import yaml

from komfort_cards import paths
from komfort_cards.batch import load_batch, resolve_batch_id
from komfort_cards.console import CardsError, say

SCENES_FILE = "scenes.yaml"
MODES = ("scene", "composite")


def load_scenes() -> dict[str, Any]:
    path = paths.CONFIG_DIR / SCENES_FILE
    if not path.is_file():
        raise CardsError(f"Нет файла сцен {path}.", hint="обновите систему (ОБНОВЛЕНИЕ.bat)")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("categories", "style", "bans", "scene_style", "scene_bans"):
        if not data.get(key):
            raise CardsError(f"В {path} нет раздела «{key}».")
    return data


def _options(recipe: dict[str, Any], plural: str, singular: str) -> list[str]:
    values = recipe.get(plural) or recipe.get(singular) or []
    return [values] if isinstance(values, str) else list(values)


def _recipe(category: str, scenes: dict[str, Any]) -> dict[str, Any]:
    recipe = scenes["categories"].get(category)
    if recipe is None:
        known = ", ".join(sorted(scenes["categories"]))
        raise CardsError(f"Неизвестная категория «{category}».", hint=f"выберите одну из: {known}")
    return recipe


def _clean(text: str) -> str:
    return " ".join(text.split())


def build_prompt(category: str, scenes: dict[str, Any] | None = None) -> str:
    """Fallback "composite" mode: an empty background with a free surface in the centre."""
    scenes = scenes or load_scenes()
    recipe = _recipe(category, scenes)
    scene = _options(recipe, "scenes", "scene")[0]
    surface = _options(recipe, "surfaces", "surface")[0]
    style = _clean(scenes["style"]).format(scene=scene[:1].upper() + scene[1:].rstrip("."), surface=surface)
    return f"{style} {_clean(scenes['bans'])}"


def item_mode(item: dict[str, Any]) -> str:
    mode = (item.get("layout") or {}).get("mode") or "scene"
    if mode not in MODES:
        raise CardsError(f"layout.mode «{mode}» неизвестен, ожидается одно из {MODES}.")
    return mode


def variant_index(batch: dict[str, Any], item: dict[str, Any]) -> int:
    """Items of one category rotate through the category's surfaces/scenes; layout.variant overrides."""
    forced = (item.get("layout") or {}).get("variant")
    if forced is not None:
        return int(forced)
    same = [i["n"] for i in batch["items"] if (i.get("category") or "default") == (item.get("category") or "default")]
    return same.index(item["n"]) if item["n"] in same else 0


def product_description(item: dict[str, Any]) -> str:
    return (item.get("product_desc") or "").strip() or ", ".join(
        p for p in ((item.get("name") or "").strip(), (item.get("photo_note") or "").strip()) if p)


def build_scene_prompt(batch: dict[str, Any], item: dict[str, Any], scenes: dict[str, Any] | None = None) -> tuple[str, int]:
    scenes = scenes or load_scenes()
    recipe = _recipe(item.get("category") or "default", scenes)
    surfaces = _options(recipe, "surfaces", "surface")
    scene_list = _options(recipe, "scenes", "scene")
    v = variant_index(batch, item)
    surface = surfaces[v % len(surfaces)]
    scene = scene_list[(v + v // len(surfaces)) % len(scene_list)]
    style = _clean(scenes["scene_style"]).format(product=product_description(item), surface=surface, scene=scene)
    return f"{style} {_clean(scenes['scene_bans'])}", v


def reference_image(batch_id: str, item: dict[str, Any]) -> str | None:
    """The image Codex must attach as the product reference: the cleaned reference if prepared, else the photo."""
    ref = (item.get("files") or {}).get("reference")
    if ref and (paths.batch_dir(batch_id) / ref).is_file():
        return ref
    return item.get("photo") or None


def cmd_prompt(args) -> dict[str, Any]:
    batch_id = resolve_batch_id(args.batch)
    batch = load_batch(batch_id)
    item = next((i for i in batch["items"] if i["n"] == args.item), None)
    if item is None:
        raise CardsError(f"В партии нет позиции {args.item}.")
    category = item.get("category") or "default"
    mode = item_mode(item)
    if mode == "composite":
        prompt, variant, reference = build_prompt(category), 0, None
        say(f"Позиция {args.item} в режиме «вклейка»: сгенерируйте ПУСТОЙ фон без товара по промпту:")
    else:
        prompt, variant = build_scene_prompt(batch, item)
        rel = reference_image(batch_id, item)
        reference = str(paths.batch_dir(batch_id) / rel) if rel else None
        say(f"Позиция {args.item} (категория {category}, вариант сцены {variant}).")
        say(f"Сгенерируйте ОДНУ картинку 4:5, приложив как референс товара файл:\n{reference}")
        say("Промпт (передайте без изменений смысла):")
    say()
    say(prompt)
    return {"batch": batch_id, "item": args.item, "mode": mode, "category": category, "variant": variant,
            "reference": reference, "prompt": prompt}

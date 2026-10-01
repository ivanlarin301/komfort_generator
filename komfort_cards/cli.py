"""Command line entry point: `cards.cmd <command>` (python -m komfort_cards <command>).

Every command prints a human-readable report in Russian and ends with `RESULT: {json}` for the agent.
Exit codes: 0 - ok, 2 - expected problem the operator/agent must resolve, 1 - unexpected error.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from typing import Any, Callable

from komfort_cards import __version__
from komfort_cards.console import CardsError, result, say, setup_utf8

# command name -> (module, function, help). Modules are imported lazily so that a broken optional
# dependency (e.g. the cutout model) never prevents the other commands from working.
COMMANDS: dict[str, tuple[str, str, str]] = {
    "collect": ("collect", "cmd_collect", "забрать фото из чата Codex (или из папки input) в новую партию"),
    "table": ("table", "cmd_table", "прочитать таблицу Excel (.xlsx) точно, без распознавания"),
    "init": ("batch", "cmd_init", "создать пустую партию на N позиций"),
    "check": ("batch", "cmd_check", "проверить batch.json и показать сводку для сверки с оператором"),
    "confirm": ("batch", "cmd_confirm", "отметить, что оператор подтвердил сводку"),
    "cutout": ("cutout", "cmd_cutout", "вырезать товары с белого фона"),
    "prompt": ("prompts", "cmd_prompt", "показать промпт генерации (товар в сцене) и путь к референсу"),
    "reference": ("cutout", "cmd_reference", "подготовить чистый референс товара (с учётом photo_crop)"),
    "background": ("background", "cmd_background", "забрать сгенерированный фон для позиции"),
    "generations": ("background", "cmd_generations", "список фонов, сгенерированных в этом чате, по номерам"),
    "render": ("render", "cmd_render", "собрать карточки (фон + товар + дизайн)"),
    "status": ("qa", "cmd_status", "показать статусы позиций партии"),
    "review": ("qa", "cmd_review", "отметить итог визуальной проверки карточки: --ok или --issue «причина»"),
    "list": ("batch", "cmd_list", "список партий"),
    "selftest": ("selftest", "cmd_selftest", "самопроверка: собрать тестовую карточку"),
    "setup-models": ("cutout", "cmd_setup_models", "скачать модель вырезки (для установщика)"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cards",
        description="Карточки товаров «Комфорт»: сборка карточек в дизайне Canva.",
    )
    parser.add_argument("--version", action="version", version=f"komfort-cards {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<команда>")

    def add(name: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=COMMANDS[name][2], description=COMMANDS[name][2])

    p = add("collect")
    p.add_argument("--batch", help="id партии; по умолчанию создаётся новая по дате и времени")
    p.add_argument("--label", help="короткая метка в имени партии, например «посуда»")
    p.add_argument("--count", type=int, help="ожидаемое число фото товаров")
    p.add_argument("--table-index", type=int, help="номер картинки-таблицы среди вложений (1..N), она не считается фото товара")
    p.add_argument("--from-input", action="store_true", help="брать фото только из папки input/")

    p = add("table")
    p.add_argument("path", help="путь к файлу .xlsx")

    p = add("init")
    p.add_argument("--batch", help="id партии; по умолчанию по дате и времени")
    p.add_argument("--label", help="короткая метка в имени партии")
    p.add_argument("--rows", type=int, required=True, help="число позиций")

    for name in ("check", "confirm", "status"):
        p = add(name)
        p.add_argument("--batch", help="id партии; по умолчанию последняя")

    p = add("cutout")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("items", nargs="*", type=int, help="номера позиций; по умолчанию все")

    p = add("prompt")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("item", type=int, help="номер позиции")

    p = add("reference")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("item", type=int, help="номер позиции")

    p = add("background")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("item", type=int, help="номер позиции")
    p.add_argument("--file", help="путь к картинке фона; по умолчанию самая новая генерация Codex")
    p.add_argument("--pick", type=int, help="номер генерации в этом чате (см. generations), например 1 — первая")

    p = add("generations")
    p.add_argument("--batch", help="id партии (чтобы отметить, какие фоны уже взяты); по умолчанию последняя")

    p = add("review")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("item", type=int, help="номер позиции")
    p.add_argument("--ok", action="store_true", help="карточка проверена и одобрена")
    p.add_argument("--issue", help="что не так (позиция уйдёт на ручную проверку)")

    p = add("render")
    p.add_argument("--batch", help="id партии; по умолчанию последняя")
    p.add_argument("items", nargs="*", type=int, help="номера позиций; по умолчанию все")

    add("list")
    add("selftest")
    add("setup-models")
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    module_name, func_name, _ = COMMANDS[args.command]
    try:
        module = importlib.import_module(f"komfort_cards.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"komfort_cards.{module_name}":
            raise CardsError(f"Команда «{args.command}» ещё не реализована в этой версии.") from exc
        raise
    handler: Callable[[argparse.Namespace], dict[str, Any]] = getattr(module, func_name)
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    setup_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        payload = dispatch(args)
    except CardsError as exc:
        say(f"ОШИБКА: {exc.message}")
        if exc.hint:
            say(f"Что сделать: {exc.hint}")
        result({"ok": False, "command": args.command, "error": exc.message, **exc.data})
        return 2
    except Exception as exc:  # unexpected: short message for the operator, details for the developer
        say(f"НЕОЖИДАННАЯ ОШИБКА: {exc}")
        traceback.print_exc(file=sys.stderr)
        result({"ok": False, "command": args.command, "error": f"unexpected: {exc!r}"})
        return 1
    result({"ok": True, "command": args.command, **(payload or {})})
    return 0

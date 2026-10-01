# -*- coding: utf-8 -*-
"""
download_images.py
Для каждого товара из Excel создаёт папку с именем товара
и скачивает все фото с его страницы на komfort.kz.

Запуск: python download_images.py
"""
import argparse
import sys, io, re, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from playwright.sync_api import sync_playwright

CODE_COLUMN_ALIASES = ("Код АХ", "КодАХ", "Код", "Артикул")
NAME_COLUMN_ALIASES = ("Наименование", "Наименование продукта", "Название", "Товар")

# Символы, запрещённые в именах папок Windows
INVALID_CHARS = r'[\\/:*?"<>|]'

def safe_folder_name(name: str) -> str:
    """Заменяет запрещённые символы и обрезает до 120 символов."""
    name = re.sub(INVALID_CHARS, "_", name).strip()
    return name[:120]

# Пропускаем иконки городов и логотипы — они из CMax/
SKIP_URL_PARTS = ["/CMax/", "/favicon", "/logo"]

parser = argparse.ArgumentParser(description="Скачать фотографии товаров со страниц komfort.kz")
parser.add_argument("--input", default="посуда дымка акция.xlsx", help="Путь к Excel-каталогу")
parser.add_argument("--output-dir", default="images", help="Корневая папка для фотографий")
parser.add_argument("--only-missing", action="store_true", help="Не трогать товары, у которых уже есть фото")
parser.add_argument("--headed", action="store_true", help="Показывать окно браузера; по умолчанию браузер работает в фоне")
args = parser.parse_args()

INPUT_FILE = args.input
OUTPUT_DIR = args.output_dir

df = pd.read_excel(INPUT_FILE)
df.columns = df.columns.str.strip()
print("Колонки:", df.columns.tolist())
print(f"Товаров: {len(df)}\n")

def resolve_column(aliases: tuple[str, ...], kind: str) -> str:
    for label in aliases:
        if label in df.columns:
            return label
    raise ValueError(f"Не найдена колонка {kind}; ожидается один из: {', '.join(aliases)}")

CODE_COLUMN = resolve_column(CODE_COLUMN_ALIASES, "кода товара")
NAME_COLUMN = resolve_column(NAME_COLUMN_ALIASES, "наименования товара")

os.makedirs(OUTPUT_DIR, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=not args.headed)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()

    total = len(df)
    for idx, row in df.iterrows():
        raw_code = row[CODE_COLUMN]
        code = str(int(raw_code)) if isinstance(raw_code, float) and raw_code.is_integer() else str(raw_code).strip()
        name = str(row[NAME_COLUMN]).strip()
        folder_name = safe_folder_name(name)
        folder_path = os.path.join(OUTPUT_DIR, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        if args.only_missing:
            existing = [
                filename for filename in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, filename))
            ]
            if existing:
                print(f"  Уже есть файлов: {len(existing)} — пропуск")
                continue

        search_url = (
            "https://komfort.kz/catalog/"
            "?q=" + code +
            "&s=%D0%9D%D0%B0%D0%B9%D1%82%D0%B8&type=catalog"
        )
        print(f"[{idx+1}/{total}] {name}")
        print(f"  Код: {code}  |  Папка: {folder_name}")

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)

            # Собираем ВСЕ img на странице из галереи товара
            all_imgs = page.query_selector_all(
                ".section-gallery-wrapper__item img, "
                "[class*='gallery'] img, "
                "[class*='detail'] img"
            )

            # Дедупликация по URL
            seen_urls = set()
            photo_urls = []
            for img_el in all_imgs:
                alt = (img_el.get_attribute("alt") or "").strip().lower()
                img_src = (
                    img_el.get_attribute("data-src")
                    or img_el.get_attribute("src")
                    or ""
                ).strip()
                if not img_src or img_src in ("/", ""):
                    continue
                # Пропускаем лого/иконки городов
                if any(skip in img_src for skip in SKIP_URL_PARTS):
                    continue
                # Строим абсолютный URL
                if img_src.startswith("//"):
                    img_src = "https:" + img_src
                elif img_src.startswith("/"):
                    img_src = "https://komfort.kz" + img_src
                # Пропускаем кешированные превью, если есть оригинал
                if "resize_cache" in img_src and img_src.replace(
                    next((p for p in img_src.split("/") if "resize_cache" in p), ""),
                    ""
                ) in seen_urls:
                    continue
                if img_src not in seen_urls:
                    seen_urls.add(img_src)
                    photo_urls.append(img_src)

            # Если галерея не нашлась — пробуем запасной вариант
            if not photo_urls:
                fallback_imgs = page.query_selector_all("img[src*='/upload/iblock/']")
                for img_el in fallback_imgs:
                    img_src = (img_el.get_attribute("src") or "").strip()
                    if not img_src or img_src in seen_urls:
                        continue
                    if img_src.startswith("/"):
                        img_src = "https://komfort.kz" + img_src
                    seen_urls.add(img_src)
                    photo_urls.append(img_src)

            print(f"  Найдено фото: {len(photo_urls)}")

            # Скачиваем каждое фото
            for i, url in enumerate(photo_urls, 1):
                try:
                    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
                    if ext not in ("jpg", "jpeg", "png", "webp", "gif", "svg"):
                        ext = "jpg"
                    filename = os.path.join(folder_path, f"photo_{i:02d}.{ext}")
                    response = page.request.get(url, timeout=15000)
                    if response.status == 200:
                        with open(filename, "wb") as f:
                            f.write(response.body())
                        size_kb = os.path.getsize(filename) // 1024
                        print(f"    [{i}] {os.path.basename(filename)}  ({size_kb} КБ)  ← {url}")
                    else:
                        print(f"    [{i}] HTTP {response.status} — пропущено: {url}")
                except Exception as e:
                    print(f"    [{i}] Ошибка скачивания: {e}")

            if not photo_urls:
                print("  ✗ Фото не найдено — папка осталась пустой")

        except Exception as exc:
            print(f"  ! Ошибка страницы: {exc}")

        time.sleep(1)
        print()

    browser.close()

# Итог
print("=" * 60)
total_downloaded = 0
for root, dirs, files in os.walk(OUTPUT_DIR):
    total_downloaded += len(files)
print(f"Готово! Скачано файлов: {total_downloaded}")
print(f"Папка: {os.path.abspath(OUTPUT_DIR)}")

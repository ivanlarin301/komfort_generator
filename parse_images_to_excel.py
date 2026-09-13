# -*- coding: utf-8 -*-
"""
parse_images_to_excel.py  v2
Ищет фото товаров на komfort.kz по коду и сохраняет URL в Excel.
Запуск: python parse_images_to_excel.py
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd
from playwright.sync_api import sync_playwright

INPUT_FILE  = "посуда дымка акция.xlsx"
OUTPUT_FILE = "посуда_дымка_с_ссылками_на_фото.xlsx"
CODE_COLUMN = "Код АХ"

df = pd.read_excel(INPUT_FILE)
df.columns = df.columns.str.strip()
print("Колонки:", df.columns.tolist())
print(f"Товаров: {len(df)}")

# Селекторы изображений — от более точного к более общему
# Поиск komfort.kz перекидывает сразу на карточку товара.
# Фото находится в .section-gallery-wrapper__item img (первое с alt != город)
IMG_SELECTORS = [
    ".section-gallery-wrapper__item img",   # карточка товара (прямой переход)
    ".detail-gallery-item img",
    ".product-detail-gallery img",
    "[class*='gallery'] img",
    "[class*='detail'] img",
    # запасные — если поиск даёт список
    "[class*='catalog'] img",
    "img[alt][src*='/upload/']",            # любое изображение из загрузок сайта
]

SKIP_ALTS = {"алматы", "астана", "шымкент", "город", "logo", ""}   # лого-картинки

photo_urls = []
page_urls  = []
total = len(df)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    for idx, raw_code in enumerate(df[CODE_COLUMN], 1):
        code = str(raw_code).strip()
        search_url = (
            "https://komfort.kz/catalog/"
            "?q=" + code +
            "&s=%D0%9D%D0%B0%D0%B9%D1%82%D0%B8&type=catalog"
        )
        print(f"\n[{idx}/{total}] Код: {code}")
        found_url = ""
        current_page_url = ""
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2500)
            current_page_url = page.url
            print(f"  URL после редиректа: {current_page_url}")

            # Перебираем селекторы
            for sel in IMG_SELECTORS:
                all_imgs = page.query_selector_all(sel)
                for img_el in all_imgs:
                    alt = (img_el.get_attribute("alt") or "").strip().lower()
                    if alt in SKIP_ALTS:
                        continue
                    img_src = (
                        img_el.get_attribute("data-src")
                        or img_el.get_attribute("src")
                        or ""
                    ).strip()
                    if not img_src or img_src in ("/", ""):
                        continue
                    # Убираем кешированные превью, берём оригинал если есть
                    if "resize_cache" in img_src:
                        # попробуем получить оригинал из alt-img
                        continue
                    if img_src.startswith("//"):
                        found_url = "https:" + img_src
                    elif img_src.startswith("/"):
                        found_url = "https://komfort.kz" + img_src
                    else:
                        found_url = img_src
                    print(f"  ✓ Фото ({sel}): {found_url}")
                    break
                if found_url:
                    break

            # Если нашли только resize_cache — берём первый подходящий
            if not found_url:
                for sel in IMG_SELECTORS:
                    all_imgs = page.query_selector_all(sel)
                    for img_el in all_imgs:
                        alt = (img_el.get_attribute("alt") or "").strip().lower()
                        if alt in SKIP_ALTS:
                            continue
                        img_src = (
                            img_el.get_attribute("data-src")
                            or img_el.get_attribute("src")
                            or ""
                        ).strip()
                        if not img_src or img_src in ("/", ""):
                            continue
                        if img_src.startswith("//"):
                            found_url = "https:" + img_src
                        elif img_src.startswith("/"):
                            found_url = "https://komfort.kz" + img_src
                        else:
                            found_url = img_src
                        print(f"  ~ Резервное фото ({sel}): {found_url}")
                        break
                    if found_url:
                        break

            if not found_url:
                print("  ✗ Фото не найдено")

        except Exception as exc:
            print(f"  ! Ошибка: {exc}")

        photo_urls.append(found_url)
        page_urls.append(current_page_url)
        time.sleep(1)

    browser.close()

df["Ссылка на фото"] = photo_urls
df["Ссылка на товар"] = page_urls
df.to_excel(OUTPUT_FILE, index=False)

found_count = sum(1 for u in photo_urls if u)
print(f"\n=== ГОТОВО: найдено {found_count}/{total} фото ===")
print(f"Файл сохранён: {OUTPUT_FILE}")

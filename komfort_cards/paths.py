"""Project-relative locations. Nothing here may depend on an absolute install path (NFR-6)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
INPUT_DIR = PROJECT_ROOT / "input"
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
ICONS_DIR = ASSETS_DIR / "icons"
LOGO_FILE = ASSETS_DIR / "logo.png"
SELFTEST_DIR = ASSETS_DIR / "selftest"
CONFIG_DIR = PROJECT_ROOT / "config"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

SELFTEST_BATCH = "_selftest"
WORK_SUBDIR = "_work"


def batch_dir(batch_id: str) -> Path:
    return OUTPUT_DIR / batch_id


def work_dir(batch_id: str) -> Path:
    return batch_dir(batch_id) / WORK_SUBDIR

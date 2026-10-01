from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from komfort_cards import paths  # noqa: E402


@pytest.fixture()
def isolated_output(tmp_path, monkeypatch):
    """Redirect output/ and input/ to a temp folder so tests never touch real batches."""
    out = tmp_path / "output"
    inp = tmp_path / "input"
    out.mkdir()
    inp.mkdir()
    monkeypatch.setattr(paths, "OUTPUT_DIR", out)
    monkeypatch.setattr(paths, "INPUT_DIR", inp)
    return tmp_path

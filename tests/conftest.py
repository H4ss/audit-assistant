from __future__ import annotations

from pathlib import Path

import pytest

from paladin.config import init_home, load_settings
from paladin.db import open_database


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "paladin home é"  # espace et accent volontaires
    monkeypatch.setenv("PALADIN_HOME", str(h))
    return h


@pytest.fixture()
def settings(home: Path):
    init_home(home)
    return load_settings(home)


@pytest.fixture()
def conn(settings):
    c = open_database(settings.db_path)
    yield c
    c.close()

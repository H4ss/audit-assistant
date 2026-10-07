from __future__ import annotations

import os
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


@pytest.fixture()
def demo(settings, conn):
    """Campagne de démo semée et importée (Fortify + ToolB ; ToolC bloqué en attente de profil)."""
    from paladin import store
    from paladin.demo import seed_demo
    from paladin.importers.pipeline import import_tool

    seed_demo(settings, conn)
    reports = {t["label"]: import_tool(settings, conn, "demo", t["label"]) for t in store.list_tools(conn, "demo")}
    return {"settings": settings, "conn": conn, "reports": reports}


def finding_by_source(conn, source_id):
    return conn.execute("SELECT * FROM finding WHERE source_id = ?", (source_id,)).fetchone()


def pytest_runtest_logreport(report):
    """En CI GitHub : chaque échec devient une annotation (lisible sans accès aux journaux)."""
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        lines = [ln for ln in str(report.longreprtext).splitlines() if ln.strip()]
        detail = " | ".join(ln.strip() for ln in lines if ln.lstrip().startswith("E "))[:900] or (
            lines[-1] if lines else ""
        )
        print(f"\n::error title={report.nodeid}::{detail}", flush=True)

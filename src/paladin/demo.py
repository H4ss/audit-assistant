"""Peuplement de l'espace de démonstration.

La démo vit dans un espace distinct de l'espace de travail réel et n'utilise
que des données fictives. Elle ne démontre pas la connexion GLM : les
propositions qu'elle contient sont marquées comme simulées.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from paladin import store
from paladin.config import Settings, ensure_campaign_dirs
from paladin.fixtures.workbook import build_demo_workbook

DEMO_CAMPAIGN_ID = "demo"


@dataclass
class DemoResult:
    campaign_id: str
    campaign_dir: Path
    workbook: Path
    created: bool


def fixtures_root() -> Path:
    return Path(str(resources.files("paladin.fixtures") / "demo"))


def load_demo_descriptor() -> dict[str, Any]:
    return json.loads((fixtures_root() / "campaign.json").read_text(encoding="utf-8"))


DEMO_MARKER = ".paladin-demo"


def mark_demo_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / DEMO_MARKER).write_text("Espace de démonstration Paladin (données fictives).\n", encoding="utf-8")


def reset_demo_home(home: Path) -> None:
    """Supprime l'espace de démo. Refuse tout dossier non marqué comme démo."""
    if not home.exists():
        return
    if not (home / DEMO_MARKER).is_file():
        raise RuntimeError(f"{home} n'est pas un espace de démo Paladin : suppression refusée.")
    shutil.rmtree(home)


def add_simulated_proposals(conn: sqlite3.Connection, campaign_id: str = DEMO_CAMPAIGN_ID) -> int:
    """Ajoute les propositions simulées (marquées comme telles) aux findings importés."""
    from paladin.analysis import store_proposal
    from paladin.contracts import AgentProposal

    data = json.loads((fixtures_root() / "simulated_proposals.json").read_text(encoding="utf-8"))["proposals"]
    added = 0
    for source_id, body in data.items():
        row = conn.execute(
            "SELECT id, revision FROM finding WHERE campaign_id = ? AND source_id = ?", (campaign_id, source_id)
        ).fetchone()
        if row is None or conn.execute("SELECT 1 FROM analysis WHERE finding_id = ?", (row["id"],)).fetchone():
            continue
        proposal = AgentProposal.model_validate({"finding_id": row["id"], "input_revision": row["revision"], **body})
        store_proposal(conn, row["id"], proposal, model_requested="simulation-demo", model_provider="aucun",
                       model_resolved="simulation", is_simulated=True)
        added += 1
    return added


def seed_demo(settings: Settings, conn: sqlite3.Connection) -> DemoResult:
    """Crée la campagne de démo. Idempotent : ne touche pas une démo existante."""
    descriptor = load_demo_descriptor()
    cid = descriptor["id"]
    campaign_dir = settings.campaign_dir(cid)
    exists = conn.execute("SELECT 1 FROM campaign WHERE id = ?", (cid,)).fetchone() is not None
    if exists:
        return DemoResult(cid, campaign_dir, campaign_dir / "inputs" / descriptor["target_workbook"], created=False)

    ensure_campaign_dirs(settings, cid)
    inputs = campaign_dir / "inputs"
    src = fixtures_root()
    for name in ("fortify", "toolb", "toolc", "repos"):
        shutil.copytree(
            src / name, inputs / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    workbook = build_demo_workbook(inputs / descriptor["target_workbook"])

    with store.transaction(conn):
        store.create_campaign(conn, cid, descriptor["name"], descriptor, is_demo=True)
        for tool in descriptor["tools"]:
            store.add_tool(conn, cid, tool["label"], tool["kind"], tool.get("sheet_name"))
        for repo in descriptor["repos"]:
            store.add_repo(
                conn, cid, repo["name"], str(inputs / repo["path"]), repo.get("commit"), repo.get("scanner_roots", [])
            )
    return DemoResult(cid, campaign_dir, workbook, created=True)

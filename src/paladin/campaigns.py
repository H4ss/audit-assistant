"""Création d'une campagne réelle depuis un fichier JSON (voir examples/campaign.example.json).

Les chemins relatifs sont résolus par rapport au dossier du fichier. Chaque
erreur indique le champ à corriger.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from paladin import store
from paladin.config import Settings, ensure_campaign_dirs
from paladin.importers.markdown import PROFILES

TOOL_KINDS = {"fortify", "excel_md", "excel", "csv", "md", "sarif"}
SOURCE_KINDS = {"excel", "csv", "md", "sarif", "fortify_fixture", "fortify_ssc"}
ROLES = {"findings", "inventory", "details"}


class CampaignError(ValueError):
    pass


def _abs(base: Path, raw: str) -> str:
    p = Path(raw).expanduser()
    return str(p if p.is_absolute() else (base / p).resolve())


def validate_descriptor(desc: dict[str, Any], base: Path) -> dict[str, Any]:
    """Valide et résout les chemins. Retourne le descripteur normalisé."""
    desc = {k: v for k, v in desc.items() if not k.startswith("_")}
    cid = desc.get("id", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,40}", cid):
        raise CampaignError("`id` : minuscules, chiffres, - ou _ (ex. « shopapp-2026 »).")
    if not desc.get("name"):
        raise CampaignError("`name` : nom lisible de la campagne requis.")
    if not desc.get("target_workbook"):
        raise CampaignError("`target_workbook` : chemin du classeur Excel cible requis.")
    desc["target_workbook"] = _abs(base, desc["target_workbook"])
    if not Path(desc["target_workbook"]).is_file():
        raise CampaignError(f"`target_workbook` introuvable : {desc['target_workbook']}")
    repos = []
    for i, r in enumerate(desc.get("repos", [])):
        r = {k: v for k, v in r.items() if not k.startswith("_")}
        if not r.get("name") or not r.get("path"):
            raise CampaignError(f"`repos[{i}]` : `name` et `path` requis.")
        r["path"] = _abs(base, r["path"])
        if not Path(r["path"]).is_dir():
            raise CampaignError(f"`repos[{i}].path` introuvable : {r['path']}")
        r.setdefault("scanner_roots", [])
        repos.append(r)
    desc["repos"] = repos
    labels: set[str] = set()
    tools = []
    for i, t in enumerate(desc.get("tools", [])):
        t = {k: v for k, v in t.items() if not k.startswith("_")}
        if not t.get("label") or t["label"] in labels:
            raise CampaignError(f"`tools[{i}].label` manquant ou en double.")
        labels.add(t["label"])
        if t.get("kind") not in TOOL_KINDS:
            raise CampaignError(f"`tools[{i}].kind` : une valeur parmi {sorted(TOOL_KINDS)}.")
        sources = []
        for j, s in enumerate(t.get("sources", [])):
            s = {k: v for k, v in s.items() if not k.startswith("_")}
            where = f"`tools[{i}].sources[{j}]`"
            if s.get("role") not in ROLES:
                raise CampaignError(f"{where}.role : une valeur parmi {sorted(ROLES)}.")
            if s.get("kind") not in SOURCE_KINDS:
                raise CampaignError(f"{where}.kind : une valeur parmi {sorted(SOURCE_KINDS)}.")
            if s["kind"] == "md" and s.get("profile") not in PROFILES:
                raise CampaignError(f"{where}.profile : une valeur parmi {list(PROFILES)}.")
            if s.get("path") and s["path"] != "@target":
                s["path"] = _abs(base, s["path"])
                if not Path(s["path"]).exists():
                    raise CampaignError(f"{where}.path introuvable : {s['path']}")
            sources.append(s)
        if not sources:
            raise CampaignError(f"`tools[{i}].sources` : au moins une source.")
        t["sources"] = sources
        tools.append(t)
    if not tools:
        raise CampaignError("`tools` : au moins un outil.")
    desc["tools"] = tools
    return desc


def create_from_file(settings: Settings, conn: sqlite3.Connection, path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise CampaignError(f"Fichier introuvable : {path}") from None
    except json.JSONDecodeError as exc:
        raise CampaignError(f"JSON invalide ({path.name}, ligne {exc.lineno}) : {exc.msg}") from None
    desc = validate_descriptor(raw, path.resolve().parent)
    if conn.execute("SELECT 1 FROM campaign WHERE id = ?", (desc["id"],)).fetchone():
        raise CampaignError(f"Une campagne « {desc['id']} » existe déjà.")
    ensure_campaign_dirs(settings, desc["id"])
    with store.transaction(conn):
        store.create_campaign(conn, desc["id"], desc["name"], desc)
        for t in desc["tools"]:
            store.add_tool(conn, desc["id"], t["label"], t["kind"], t.get("sheet_name"))
        for r in desc["repos"]:
            store.add_repo(conn, desc["id"], r["name"], r["path"], r.get("commit"), r["scanner_roots"])
    return desc["id"]

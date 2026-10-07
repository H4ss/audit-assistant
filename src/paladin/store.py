"""Accès aux entités de campagne (campagne, outils, dépôts).

Les écritures plus riches (findings, décisions, exports) vivent dans leurs
modules dédiés ; ce module ne contient que le socle.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from paladin.util import dumps, loads, new_id, utcnow


class ConflictError(RuntimeError):
    """Écriture refusée : révision attendue différente (double clic, réponse périmée)."""


class NotFoundError(LookupError):
    pass


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction immédiate (verrou d'écriture pris au début)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def create_campaign(
    conn: sqlite3.Connection, campaign_id: str, name: str, config: dict[str, Any], is_demo: bool = False
) -> str:
    now = utcnow()
    conn.execute(
        "INSERT INTO campaign (id, name, config_json, is_demo, revision, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 1, ?, ?)",
        (campaign_id, name, dumps(config), int(is_demo), now, now),
    )
    return campaign_id


def update_campaign_config(conn: sqlite3.Connection, campaign_id: str, config: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE campaign SET config_json = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
        (dumps(config), utcnow(), campaign_id),
    )


def get_campaign(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM campaign WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Campagne inconnue : {campaign_id}")
    out = dict(row)
    out["config"] = loads(out.pop("config_json"), {})
    return out


def list_campaigns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r) for r in conn.execute("SELECT id, name, is_demo, updated_at FROM campaign ORDER BY updated_at DESC")
    ]


def add_tool(conn: sqlite3.Connection, campaign_id: str, label: str, kind: str, sheet_name: str | None) -> str:
    tool_id = new_id()
    conn.execute(
        "INSERT INTO tool (id, campaign_id, label, kind, sheet_name, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tool_id, campaign_id, label, kind, sheet_name, utcnow()),
    )
    return tool_id


def get_tool(conn: sqlite3.Connection, campaign_id: str, label: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM tool WHERE campaign_id = ? AND label = ?", (campaign_id, label)).fetchone()
    if row is None:
        raise NotFoundError(f"Outil inconnu : {label}")
    return dict(row)


def list_tools(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    return [
        dict(r) for r in conn.execute("SELECT * FROM tool WHERE campaign_id = ? ORDER BY created_at", (campaign_id,))
    ]


def add_repo(
    conn: sqlite3.Connection,
    campaign_id: str,
    name: str,
    path: str,
    commit_sha: str | None,
    scanner_roots: list[str],
) -> str:
    repo_id = new_id()
    conn.execute(
        "INSERT INTO repo (id, campaign_id, name, path, commit_sha, scanner_roots_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (repo_id, campaign_id, name, path, commit_sha, dumps(scanner_roots), utcnow()),
    )
    return repo_id


def list_repos(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM repo WHERE campaign_id = ? ORDER BY name", (campaign_id,))
    out = []
    for r in rows:
        d = dict(r)
        d["scanner_roots"] = loads(d.pop("scanner_roots_json"), [])
        out.append(d)
    return out


def set_ui_state(conn: sqlite3.Connection, campaign_id: str, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO ui_state (campaign_id, key, value_json, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (campaign_id, key) DO UPDATE SET value_json = excluded.value_json, updated_at ="
        " excluded.updated_at",
        (campaign_id, key, dumps(value), utcnow()),
    )


def get_ui_state(conn: sqlite3.Connection, campaign_id: str, key: str, default: Any = None) -> Any:
    row = conn.execute(
        "SELECT value_json FROM ui_state WHERE campaign_id = ? AND key = ?", (campaign_id, key)
    ).fetchone()
    return default if row is None else loads(row["value_json"])

"""Profils d'entrée : mappings proposés puis validés une fois, réutilisés ensuite."""

from __future__ import annotations

import sqlite3
from typing import Any

from paladin.contracts import SchemaStatus
from paladin.importers.mapping import validate_mapping
from paladin.util import dumps, loads, new_id, utcnow


def find_validated(conn: sqlite3.Connection, campaign_id: str, sig: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM input_profile WHERE signature = ? AND status = 'validated'"
        " AND (campaign_id = ? OR campaign_id IS NULL) ORDER BY version DESC LIMIT 1",
        (sig, campaign_id),
    ).fetchone()
    return _row(row)


def save_proposal(
    conn: sqlite3.Connection,
    campaign_id: str,
    name: str,
    kind: str,
    sig: str,
    mapping: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    """Enregistre une proposition (idempotent pour une même signature en attente)."""
    existing = conn.execute(
        "SELECT * FROM input_profile WHERE campaign_id = ? AND signature = ? AND status = 'proposed'",
        (campaign_id, sig),
    ).fetchone()
    if existing:
        return _row(existing)  # type: ignore[return-value]
    version = (
        (
            conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM input_profile WHERE campaign_id = ? AND name = ?",
                (campaign_id, name),
            ).fetchone()[0]
        )
        + 1
    )
    pid = new_id()
    conn.execute(
        "INSERT INTO input_profile (id, campaign_id, name, source_kind, signature, version, mapping_json, status,"
        " proposed_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            pid,
            campaign_id,
            name,
            kind,
            sig,
            version,
            dumps(mapping),
            SchemaStatus.PROPOSED.value,
            proposed_by,
            utcnow(),
        ),
    )
    return get(conn, pid)


def validate(conn: sqlite3.Connection, profile_id: str, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    """Valide un profil, éventuellement corrigé. Les versions validées précédentes sont remplacées."""
    prof = get(conn, profile_id)
    final = mapping if mapping is not None else prof["mapping"]
    validate_mapping(final)
    conn.execute(
        "UPDATE input_profile SET status = 'superseded' WHERE campaign_id IS ? AND signature = ? AND status ="
        " 'validated'",
        (prof["campaign_id"], prof["signature"]),
    )
    conn.execute(
        "UPDATE input_profile SET status = 'validated', mapping_json = ?, validated_at = ? WHERE id = ?",
        (dumps(final), utcnow(), profile_id),
    )
    return get(conn, profile_id)


def get(conn: sqlite3.Connection, profile_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM input_profile WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise LookupError(f"Profil inconnu : {profile_id}")
    return _row(row)  # type: ignore[return-value]


def list_profiles(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM input_profile WHERE campaign_id = ? ORDER BY created_at DESC", (campaign_id,)
    ).fetchall()
    return [_row(r) for r in rows]  # type: ignore[misc]


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    d["mapping"] = loads(d.pop("mapping_json"), {})
    return d

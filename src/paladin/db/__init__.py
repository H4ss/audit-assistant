"""Accès SQLite et migrations.

Les migrations sont des fichiers `NNNN_nom.sql` appliqués dans l'ordre. Avant
d'appliquer une migration sur une base existante, une copie de sauvegarde est
créée à côté de la base (`<base>.bak-<version>-<horodatage>`).
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from paladin.util import sha256_bytes, utcnow

_MIGRATIONS_PACKAGE = "paladin.db.migrations"


class MigrationError(RuntimeError):
    pass


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def available_migrations() -> list[tuple[int, str, str]]:
    """Retourne [(version, nom, sql)] triés."""
    out: list[tuple[int, str, str]] = []
    for entry in resources.files(_MIGRATIONS_PACKAGE).iterdir():
        name = entry.name
        if not name.endswith(".sql"):
            continue
        version = int(name.split("_", 1)[0])
        out.append((version, name, entry.read_text(encoding="utf-8")))
    out.sort()
    return out


def applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)"
    )
    return {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migration")}


def _backup(conn: sqlite3.Connection, db_path: Path, version: int) -> Path:
    stamp = utcnow().replace(":", "").replace("-", "").replace(".", "")[:15]
    target = db_path.with_name(f"{db_path.name}.bak-{version:04d}-{stamp}")
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def migrate(conn: sqlite3.Connection, db_path: Path) -> list[str]:
    """Applique les migrations manquantes. Retourne les noms appliqués."""
    done = applied_versions(conn)
    pending = []
    for version, name, sql in available_migrations():
        checksum = sha256_bytes(sql.encode("utf-8"))
        if version in done:
            if done[version] != checksum:
                raise MigrationError(
                    f"La migration {name} a changé depuis son application. "
                    "Ne jamais modifier une migration publiée : en ajouter une nouvelle."
                )
            continue
        pending.append((version, name, sql, checksum))
    if not pending:
        return []
    if done:  # base existante : sauvegarde avant mise à jour
        _backup(conn, db_path, pending[0][0])
    applied = []
    for version, name, sql, checksum in pending:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migration (version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                (version, name, checksum, utcnow()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(name)
    return applied


def _split_sql(sql: str) -> list[str]:
    """Découpe un script en instructions.

    Contrainte de nos migrations : ni ';' ni '--' dans les littéraux SQL.
    """
    lines = [ln.split("--", 1)[0] for ln in sql.splitlines()]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_database(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn, db_path)
    return conn

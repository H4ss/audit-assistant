import sqlite3

import pytest

from paladin import db


def test_migrations_apply_once(settings):
    conn = db.open_database(settings.db_path)
    assert db.migrate(conn, settings.db_path) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("campaign", "finding", "decision_event", "analysis", "job", "finding_relation", "export_run", "sheet_schema"):
        assert t in tables
    conn.close()


def test_changed_migration_is_refused(settings, monkeypatch):
    conn = db.open_database(settings.db_path)
    original = db.available_migrations()
    monkeypatch.setattr(db, "available_migrations", lambda: [(v, n, s + "\n-- edit") for v, n, s in original])
    with pytest.raises(db.MigrationError):
        db.migrate(conn, settings.db_path)
    conn.close()


def test_backup_before_upgrade(settings, monkeypatch):
    conn = db.open_database(settings.db_path)
    original = db.available_migrations()
    extra = (9999, "9999_test.sql", "CREATE TABLE extra_test (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr(db, "available_migrations", lambda: original + [extra])
    assert db.migrate(conn, settings.db_path) == ["9999_test.sql"]
    backups = list(settings.db_path.parent.glob("paladin.sqlite.bak-9999-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as b:
        assert b.execute("SELECT count(*) FROM sqlite_master WHERE name='extra_test'").fetchone()[0] == 0
    conn.close()


def test_single_active_job_per_finding(conn):
    from paladin import store
    from paladin.util import new_id, utcnow

    store.create_campaign(conn, "c1", "c", {})
    tid = store.add_tool(conn, "c1", "Fortify", "fortify", "Fortify")
    fid = new_id()
    now = utcnow()
    conn.execute(
        "INSERT INTO finding (id, campaign_id, tool_id, scope_key, source_id, source_id_kind, fingerprint, created_at, updated_at)"
        " VALUES (?, 'c1', ?, 's', 'x', 'native', 'fp', ?, ?)", (fid, tid, now, now))
    ins = "INSERT INTO job (id, campaign_id, finding_id, kind, status, created_at, updated_at) VALUES (?, 'c1', ?, 'analysis', ?, ?, ?)"
    conn.execute(ins, (new_id(), fid, "pending", now, now))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (new_id(), fid, "claimed", now, now))
    conn.execute(ins, (new_id(), fid, "done", now, now))  # historique autorisé

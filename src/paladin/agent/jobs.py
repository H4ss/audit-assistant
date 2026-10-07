"""File de jobs d'analyse avec bail temporaire.

* Un job « réclamé » porte un bail (expiration + jeton). Après un crash, le bail
  expire et le job redevient réclamable ; l'ancien détenteur ne peut plus
  soumettre (jeton différent) : jamais deux propositions pour un même bail.
* Au plus un job actif par finding (index unique partiel).
* Après MAX_ATTEMPTS échecs, le job passe en erreur avec son motif.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from paladin import store
from paladin.contracts import JobKind, JobStatus, ProcessingState, ReviewState
from paladin.util import dumps, loads, new_id, utcnow

MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 900
PRESENCE_WINDOW_SECONDS = 120


class JobError(RuntimeError):
    """Erreur de job, avec code HTTP suggéré pour l'API agent."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="microseconds")


def enqueue_analysis(conn: sqlite3.Connection, campaign_id: str, finding_ids: list[str] | None = None) -> int:
    """Crée un job d'analyse pour chaque finding à revoir sans job actif ni proposition courante.

    Les analyses à l'aveugle du jeu de référence passent par `calibration.enqueue_blind`.
    """
    sql = (
        "SELECT f.id, f.revision FROM finding f WHERE f.campaign_id = ?"
        f" AND f.review_state IN ('{ReviewState.TO_REVIEW}', '{ReviewState.REEXAM_REQUIRED}')"
        " AND NOT EXISTS (SELECT 1 FROM job j WHERE j.finding_id = f.id AND j.kind = 'analysis'"
        "   AND j.status IN ('pending', 'claimed'))"
        " AND NOT EXISTS (SELECT 1 FROM analysis a WHERE a.finding_id = f.id AND a.input_revision = f.revision"
        "   AND a.is_blind = 0)"
    )
    params: list[Any] = [campaign_id]
    if finding_ids is not None:
        if not finding_ids:
            return 0
        sql += f" AND f.id IN ({', '.join('?' * len(finding_ids))})"
        params += finding_ids
    created = 0
    with store.transaction(conn):
        for row in conn.execute(sql, params).fetchall():
            now = utcnow()
            conn.execute(
                "INSERT INTO job (id, campaign_id, finding_id, kind, status, input_revision, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id(),
                    campaign_id,
                    row["id"],
                    JobKind.ANALYSIS.value,
                    JobStatus.PENDING.value,
                    row["revision"],
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE finding SET processing_state = ?, updated_at = ? WHERE id = ?",
                (ProcessingState.PENDING.value, now, row["id"]),
            )
            created += 1
    return created


def touch_presence(conn: sqlite3.Connection, worker: str, campaign_id: str | None, action: str) -> None:
    conn.execute(
        "INSERT INTO agent_presence (worker, campaign_id, last_seen_at, last_action) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (worker) DO UPDATE SET campaign_id = excluded.campaign_id,"
        " last_seen_at = excluded.last_seen_at, last_action = excluded.last_action",
        (worker, campaign_id, utcnow(), action),
    )


def claim(
    conn: sqlite3.Connection,
    worker: str,
    campaign_id: str | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    model_requested: str | None = None,
) -> dict[str, Any] | None:
    """Réclame le plus ancien job en attente, ou un job dont le bail a expiré."""
    now = _now()
    with store.transaction(conn):
        touch_presence(conn, worker, campaign_id, "claim")
        sql = (
            "SELECT * FROM job WHERE kind = 'analysis' AND ("
            " status = 'pending' OR (status = 'claimed' AND lease_expires_at < ?))"
        )
        params: list[Any] = [_iso(now)]
        if campaign_id:
            sql += " AND campaign_id = ?"
            params.append(campaign_id)
        row = conn.execute(sql + " ORDER BY created_at LIMIT 1", params).fetchone()
        if row is None:
            return None
        finding = conn.execute("SELECT revision FROM finding WHERE id = ?", (row["finding_id"],)).fetchone()
        if finding["revision"] != row["input_revision"]:
            # Le finding a changé depuis la mise en file : on réaligne la révision attendue.
            conn.execute("UPDATE job SET input_revision = ? WHERE id = ?", (finding["revision"], row["id"]))
        token = secrets.token_urlsafe(24)
        expires = now + timedelta(seconds=lease_seconds)
        conn.execute(
            "UPDATE job SET status = 'claimed', lease_owner = ?, lease_token = ?, lease_expires_at = ?,"
            " attempt = attempt + 1, model_requested = COALESCE(?, model_requested), updated_at = ?,"
            " started_at = COALESCE(started_at, ?) WHERE id = ?",
            (worker, token, _iso(expires), model_requested, utcnow(), utcnow(), row["id"]),
        )
        if not row["blind"]:  # une analyse à l'aveugle ne change pas l'état d'un finding déjà décidé
            conn.execute(
                "UPDATE finding SET processing_state = ?, updated_at = ? WHERE id = ?",
                (ProcessingState.ANALYZING.value, utcnow(), row["finding_id"]),
            )
        job = dict(conn.execute("SELECT * FROM job WHERE id = ?", (row["id"],)).fetchone())
    return job


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise JobError(f"Job inconnu : {job_id}", 404)
    return dict(row)


def check_lease(conn: sqlite3.Connection, job_id: str, lease_token: str) -> dict[str, Any]:
    """Vérifie que l'appelant détient le bail courant du job."""
    job = get_job(conn, job_id)
    if job["status"] != JobStatus.CLAIMED:
        raise JobError(f"Job {job_id} non réclamé (état : {job['status']}).")
    if not lease_token or not secrets.compare_digest(job["lease_token"] or "", lease_token):
        raise JobError("Bail invalide : ce job a été repris par un autre agent ou a expiré.", 403)
    if job["lease_expires_at"] < _iso(_now()):
        raise JobError("Bail expiré : réclamer à nouveau un job.", 409)
    return job


def heartbeat(
    conn: sqlite3.Connection, job_id: str, lease_token: str, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> str:
    with store.transaction(conn):
        job = check_lease(conn, job_id, lease_token)
        touch_presence(conn, job["lease_owner"], job["campaign_id"], "heartbeat")
        expires = _iso(_now() + timedelta(seconds=lease_seconds))
        conn.execute("UPDATE job SET lease_expires_at = ?, updated_at = ? WHERE id = ?", (expires, utcnow(), job_id))
    return expires


def complete(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE job SET status = 'done', lease_token = NULL, lease_expires_at = NULL, error = NULL, updated_at = ?,"
        " finished_at = ? WHERE id = ?",
        (utcnow(), utcnow(), job_id),
    )


def record_validation_error(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("UPDATE job SET validation_errors = validation_errors + 1 WHERE id = ?", (job_id,))


def fail(conn: sqlite3.Connection, job_id: str, lease_token: str, reason: str) -> dict[str, Any]:
    """Abandon par l'agent : remise en file, ou erreur définitive après MAX_ATTEMPTS."""
    with store.transaction(conn):
        job = check_lease(conn, job_id, lease_token)
        final = job["attempt"] >= MAX_ATTEMPTS
        status = JobStatus.ERROR if final else JobStatus.PENDING
        conn.execute(
            "UPDATE job SET status = ?, error = ?, lease_token = NULL, lease_owner = NULL, lease_expires_at = NULL,"
            " updated_at = ? WHERE id = ?",
            (status.value, reason[:2000], utcnow(), job_id),
        )
        state = ProcessingState.ERROR if final else ProcessingState.PENDING
        if not job["blind"]:
            conn.execute("UPDATE finding SET processing_state = ? WHERE id = ?", (state.value, job["finding_id"]))
    return get_job(conn, job_id)


def record_usage(
    conn: sqlite3.Connection, job_id: str, usage: dict[str, Any], cost_usd: float | None, model_resolved: str | None
) -> None:
    """Consommation mesurée côté client (OpenCode) ; additionnée si plusieurs exécutions."""
    job = get_job(conn, job_id)
    previous = loads(job["usage_json"], {})
    merged = dict(previous)
    for k, v in usage.items():
        if isinstance(v, int | float):
            merged[k] = (merged.get(k) or 0) + v
    total = (job["cost_usd"] or 0) + (cost_usd or 0) if cost_usd is not None else job["cost_usd"]
    conn.execute(
        "UPDATE job SET usage_json = ?, cost_usd = ?, model_resolved = COALESCE(?, model_resolved) WHERE id = ?",
        (dumps(merged), total, model_resolved, job_id),
    )
    if model_resolved:
        conn.execute(
            "UPDATE analysis SET model_resolved = ? WHERE job_id = ? AND model_resolved = 'unknown'",
            (model_resolved, job_id),
        )


def status(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    """État visible dans l'interface : agent connecté, attente d'agent, analyse en cours."""
    counts = {
        r["status"]: r["n"]
        for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM job WHERE campaign_id = ? AND kind = 'analysis' GROUP BY status",
            (campaign_id,),
        )
    }
    since = _iso(_now() - timedelta(seconds=PRESENCE_WINDOW_SECONDS))
    present = conn.execute(
        "SELECT worker, last_seen_at, last_action FROM agent_presence WHERE last_seen_at >= ?"
        " AND (campaign_id = ? OR campaign_id IS NULL) ORDER BY last_seen_at DESC LIMIT 1",
        (since, campaign_id),
    ).fetchone()
    active = conn.execute(
        "SELECT COUNT(*) FROM job WHERE campaign_id = ? AND status = 'claimed' AND lease_expires_at >= ?",
        (campaign_id, _iso(_now())),
    ).fetchone()[0]
    if active:
        label = "analyse en cours"
    elif present:
        label = "agent connecté"
    elif counts.get("pending"):
        label = "attente d'agent"
    else:
        label = "aucun agent"
    cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM job WHERE campaign_id = ?", (campaign_id,)).fetchone()[
        0
    ]
    return {
        "label": label,
        "pending": counts.get("pending", 0),
        "claimed": counts.get("claimed", 0),
        "done": counts.get("done", 0),
        "error": counts.get("error", 0),
        "worker": dict(present) if present else None,
        "cost_usd": round(cost, 4),
    }


def total_cost(conn: sqlite3.Connection, since_iso: str | None = None) -> float:
    sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM job"
    params: list[Any] = []
    if since_iso:
        sql += " WHERE updated_at >= ?"
        params.append(since_iso)
    return float(conn.execute(sql, params).fetchone()[0])

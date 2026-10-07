"""Calibration de l'agent sur les analyses manuelles de l'analyste.

Boucle : l'analyste analyse à la main les premières applications → ces décisions
sont réparties entre **exemples** (montrés à l'agent comme précédents, base des
conventions) et **jeu de référence** (jamais montré à l'agent) → l'agent analyse
le jeu de référence **à l'aveugle**, sans que les décisions humaines bougent →
le rapport compare, cas par cas, verdicts, commentaires, références et coût →
l'analyste ajuste les **conventions d'équipe** (texte versionné injecté dans le
contexte de l'agent) et relance. Chaque version des conventions a ses mesures.

Garde-fous :
  * une analyse à l'aveugle ne crée jamais de décision et ne modifie pas l'export ;
  * un finding déjà montré à l'agent comme précédent ne peut plus entrer dans la
    référence (la mesure serait biaisée) ;
  * une décision prise en voyant une proposition est signalée « non indépendante ».

Mesures avec effectifs, jamais un pourcentage seul. Le temps manuel de référence
est comparé au temps de revue assistée réellement mesuré.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from typing import Any

from paladin import store
from paladin.contracts import JobKind, JobStatus, Verdict
from paladin.review.memory import _active_hours
from paladin.util import loads, new_id, sha256_bytes, utcnow

REFERENCE_SHARE = 1 / 3
MIN_ASSISTED_DECISIONS = 5
STATUS_ORDER = ("TP manqué", "sur-signalé", "abstention", "en cours", "pas encore analysé", "accord")


class CalibrationError(ValueError):
    pass


# ----------------------------------------------------------------- exemples et référence


def is_exposed(conn: sqlite3.Connection, finding_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM agent_exposure WHERE finding_id = ? LIMIT 1", (finding_id,)).fetchone() is not None
    )


def _decided(conn: sqlite3.Connection, finding_ids: list[str]) -> list[sqlite3.Row]:
    if not finding_ids:
        return []
    return conn.execute(
        "SELECT f.id, f.source_id, e.verdict FROM finding f JOIN decision_event e ON e.id = f.current_decision_id"
        f" WHERE e.verdict IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE') AND f.id IN ({', '.join('?' * len(finding_ids))})",
        finding_ids,
    ).fetchall()


def assign_roles(
    conn: sqlite3.Connection, campaign_id: str, finding_ids: list[str], role: str = "auto"
) -> dict[str, int]:
    """Répartit des findings décidés entre exemples et référence.

    « auto » : environ un tiers en référence, par verdict (au moins un de chaque verdict présent deux fois ou
    plus), choix stable (empreinte de l'identifiant). Les findings déjà exposés à l'agent restent des exemples.
    """
    rows = _decided(conn, finding_ids)
    exposed = {r["id"] for r in rows if is_exposed(conn, r["id"])}
    reference: set[str] = set()
    if role == "reference":
        reference = {r["id"] for r in rows} - exposed
    elif role == "auto":
        by_verdict: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in rows:
            if r["id"] not in exposed:
                by_verdict[r["verdict"]].append(r)
        for group in by_verdict.values():
            group.sort(key=lambda r: sha256_bytes(r["source_id"].encode()))
            k = round(len(group) * REFERENCE_SHARE)
            if len(group) >= 2:
                k = max(1, k)
            reference.update(r["id"] for r in group[:k])
    with store.transaction(conn):
        for r in rows:
            conn.execute("UPDATE finding SET is_reference = ? WHERE id = ?", (int(r["id"] in reference), r["id"]))
    return {
        "référence": len(reference),
        "exemples": len(rows) - len(reference),
        "gardés en exemples (déjà montrés à l'agent)": len(exposed) if role != "example" else 0,
    }


def set_role(conn: sqlite3.Connection, finding_id: str, reference: bool) -> None:
    if reference:
        if not _decided(conn, [finding_id]):
            raise CalibrationError(
                "Seul un finding décidé (True Positive / Not an issue) peut entrer dans la référence."
            )
        if is_exposed(conn, finding_id):
            raise CalibrationError(
                "Ce finding a déjà été montré à l'agent comme précédent : en référence, la mesure serait biaisée."
            )
    conn.execute("UPDATE finding SET is_reference = ? WHERE id = ?", (int(reference), finding_id))


def resplit(conn: sqlite3.Connection, campaign_id: str) -> dict[str, int]:
    """Nouvelle répartition automatique de toutes les décisions finales de la campagne."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT f.id FROM finding f JOIN decision_event e ON e.id = f.current_decision_id WHERE f.campaign_id = ?",
            (campaign_id,),
        )
    ]
    return assign_roles(conn, campaign_id, ids, "auto")


# ----------------------------------------------------------------- conventions d'équipe


def current_conventions(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM team_conventions ORDER BY version DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def conventions_history(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM team_conventions ORDER BY version DESC")]


def save_conventions(conn: sqlite3.Connection, text: str, author: str, note: str = "") -> int:
    """Nouvelle version des conventions (jamais de modification en place). Retourne le numéro de version."""
    text = text.replace("\r\n", "\n").strip()
    cur = current_conventions(conn)
    if cur and cur["text"] == text:
        raise CalibrationError(f"Texte identique à la version {cur['version']} : rien à enregistrer.")
    if not cur and not text:
        raise CalibrationError("Conventions vides : rien à enregistrer.")
    version = (cur["version"] if cur else 0) + 1
    conn.execute(
        "INSERT INTO team_conventions (version, text, note, author, created_at) VALUES (?, ?, ?, ?, ?)",
        (version, text, note.strip(), author, utcnow()),
    )
    return version


def conventions_for_agent(conn: sqlite3.Connection) -> tuple[int | None, dict[str, Any] | None]:
    cur = current_conventions(conn)
    if not cur or not cur["text"]:
        return (cur["version"] if cur else None), None
    return cur["version"], {
        "version": cur["version"],
        "text": cur["text"],
        "note": "Conventions de l'équipe, validées par l'analyste : les appliquer pour le verdict et la rédaction du"
        " commentaire. Elles ne remplacent jamais les preuves du code : un cas qui ne remplit pas leurs conditions"
        " s'analyse normalement.",
    }


def examples_summary(conn: sqlite3.Connection, per_category: int = 3) -> list[dict[str, Any]]:
    """Exemples (hors référence, toutes applications) par catégorie : matière pour rédiger les conventions."""
    rows = conn.execute(
        "SELECT f.category, f.source_id, f.application_name, f.normalized_path, f.line_number, e.verdict, e.comment"
        " FROM finding f JOIN decision_event e ON e.id = f.current_decision_id"
        " WHERE f.is_reference = 0 AND e.verdict IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE')"
        " ORDER BY f.category, e.created_at DESC"
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        cat = out.setdefault(
            r["category"] or "(sans catégorie)", {"category": r["category"], "tp": 0, "nai": 0, "items": []}
        )
        cat["tp" if r["verdict"] == Verdict.TRUE_POSITIVE else "nai"] += 1
        if r["comment"] and len(cat["items"]) < per_category:
            cat["items"].append(dict(r))
    return sorted(out.values(), key=lambda c: -(c["tp"] + c["nai"]))


# ----------------------------------------------------------------- analyse à l'aveugle


def _current_version(conn: sqlite3.Connection) -> int:
    cur = current_conventions(conn)
    return cur["version"] if cur else 0


def blind_candidates(conn: sqlite3.Connection, campaign_id: str) -> list[sqlite3.Row]:
    """Findings de référence sans analyse à l'aveugle pour leur révision et la version courante des conventions."""
    return conn.execute(
        "SELECT f.id, f.revision, f.source_id FROM finding f JOIN decision_event e ON e.id = f.current_decision_id"
        " WHERE f.campaign_id = ? AND f.is_reference = 1 AND e.verdict IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE')"
        " AND NOT EXISTS (SELECT 1 FROM job j WHERE j.finding_id = f.id AND j.kind = 'analysis'"
        "   AND j.status IN ('pending', 'claimed'))"
        " AND NOT EXISTS (SELECT 1 FROM analysis a WHERE a.finding_id = f.id AND a.is_blind = 1"
        "   AND a.input_revision = f.revision AND COALESCE(a.conventions_version, 0) = ?)",
        (campaign_id, _current_version(conn)),
    ).fetchall()


def average_cost(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT AVG(cost_usd), COUNT(*) FROM job WHERE status = 'done' AND cost_usd IS NOT NULL AND cost_usd > 0"
    ).fetchone()
    return round(row[0], 4) if row[1] else None


def enqueue_blind(conn: sqlite3.Connection, campaign_id: str) -> int:
    """Met en file l'analyse à l'aveugle du jeu de référence. Les décisions humaines ne sont jamais touchées."""
    created = 0
    with store.transaction(conn):
        for row in blind_candidates(conn, campaign_id):
            now = utcnow()
            conn.execute(
                "INSERT INTO job (id, campaign_id, finding_id, kind, status, input_revision, blind, created_at,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
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
            created += 1
    return created


# ----------------------------------------------------------------- rapport


def _seconds(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 1)


def _status(human: str, agent: str | None) -> str:
    if agent is None:
        return "pas encore analysé"
    if agent == Verdict.NEEDS_REVIEW:
        return "abstention"
    if agent == human:
        return "accord"
    return "TP manqué" if human == Verdict.TRUE_POSITIVE else "sur-signalé"


def report(conn: sqlite3.Connection, campaign_id: str, version: int | None = None) -> dict[str, Any]:
    """Comparaison humaine / agent sur le jeu de référence, pour une version des conventions (courante par défaut)."""
    version = _current_version(conn) if version is None else version
    refs = conn.execute(
        "SELECT f.id, f.source_id, f.category, f.normalized_path, f.line_number, e.verdict AS h_verdict,"
        " e.comment AS h_comment, e.created_at AS h_at, e.authority AS h_authority,"
        " (SELECT MIN(a.created_at) FROM analysis a WHERE a.finding_id = f.id AND a.is_blind = 0) AS first_proposal,"
        " EXISTS (SELECT 1 FROM job j WHERE j.finding_id = f.id AND j.blind = 1 AND j.status IN ('pending', 'claimed'))"
        "   AS running"
        " FROM finding f JOIN decision_event e ON e.id = f.current_decision_id"
        " WHERE f.campaign_id = ? AND f.is_reference = 1 AND e.verdict IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE')"
        " ORDER BY f.source_id",
        (campaign_id,),
    ).fetchall()
    blind = conn.execute(
        "SELECT a.*, j.cost_usd, j.started_at, j.finished_at FROM analysis a LEFT JOIN job j ON j.id = a.job_id"
        " JOIN finding f ON f.id = a.finding_id WHERE f.campaign_id = ? AND a.is_blind = 1 ORDER BY a.seq",
        (campaign_id,),
    ).fetchall()
    by_version: dict[int, dict[str, sqlite3.Row]] = defaultdict(dict)
    for a in blind:
        by_version[a["conventions_version"] or 0][a["finding_id"]] = a  # la plus récente l'emporte
    ref_ids = {r["id"] for r in refs}
    rows = []
    for r in refs:
        a = by_version.get(version, {}).get(r["id"])
        checks = _checks(a)
        status = _status(r["h_verdict"], a["proposed_verdict"] if a else None)
        if a is None and r["running"]:
            status = "en cours"
        rows.append(
            {
                "finding_id": r["id"],
                "source_id": r["source_id"],
                "category": r["category"],
                "location": f"{r['normalized_path'] or '?'}:{r['line_number'] or '?'}",
                "human_verdict": r["h_verdict"],
                "human_comment": r["h_comment"],
                "independent": not (r["first_proposal"] and r["first_proposal"] < r["h_at"]),
                "agent_verdict": a["proposed_verdict"] if a else None,
                "agent_comment": a["suggested_comment"] if a else None,
                "agent_summary": a["summary"] if a else None,
                "refs_ok": sum(1 for c in checks if c["status"] == "verified"),
                "refs_total": len(checks),
                "cost_usd": a["cost_usd"] if a else None,
                "seconds": _seconds(a["started_at"], a["finished_at"]) if a else None,
                "model": a["model_resolved"]
                if a and a["model_resolved"] != "unknown"
                else (a["model_requested"] if a else None),
                "simulated": bool(a["is_simulated"]) if a else False,
                "status": status,
            }
        )
    rows.sort(key=lambda x: (STATUS_ORDER.index(x["status"]), x["source_id"]))
    summaries = []
    for v in sorted(set(by_version) | {version}):
        analysed = {fid: a for fid, a in by_version.get(v, {}).items() if fid in ref_ids}
        human = {r["id"]: r["h_verdict"] for r in refs}
        statuses = [_status(human[fid], a["proposed_verdict"]) for fid, a in analysed.items()]
        checks = [c for a in analysed.values() for c in _checks(a)]
        costs = [a["cost_usd"] for a in analysed.values() if a["cost_usd"] is not None]
        durations = [s for a in analysed.values() if (s := _seconds(a["started_at"], a["finished_at"])) is not None]
        summaries.append(
            {
                "version": v,
                "reference": len(refs),
                "analysed": len(analysed),
                "agree": statuses.count("accord"),
                "missed_tp": statuses.count("TP manqué"),
                "overcalled": statuses.count("sur-signalé"),
                "abstained": statuses.count("abstention"),
                "refs_ok": sum(1 for c in checks if c["status"] == "verified"),
                "refs_total": len(checks),
                "cost_usd": round(sum(costs), 4) if costs else None,
                "avg_seconds": round(sum(durations) / len(durations)) if durations else None,
            }
        )
    tp = sum(1 for r in refs if r["h_verdict"] == Verdict.TRUE_POSITIVE)
    warnings = []
    if len(refs) < 5:
        warnings.append(f"Jeu de référence de {len(refs)} cas : indicatif seulement, aucun seuil ne se fixe là-dessus.")
    if refs and tp == 0:
        warnings.append("Aucun True Positive dans la référence : le risque principal (TP manqué) n'est pas mesuré.")
    dependent = sum(1 for x in rows if not x["independent"])
    if dependent:
        warnings.append(
            f"{dependent} décision(s) de référence prise(s) en voyant une proposition : comparaison biaisée."
        )
    examples = conn.execute(
        "SELECT COUNT(*) FROM finding f JOIN decision_event e ON e.id = f.current_decision_id WHERE f.campaign_id = ?"
        " AND f.is_reference = 0 AND e.verdict IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE')",
        (campaign_id,),
    ).fetchone()[0]
    return {
        "version": version,
        "current_version": _current_version(conn),
        "rows": rows,
        "summaries": summaries,
        "summary": next(s for s in summaries if s["version"] == version),
        "reference_tp": tp,
        "examples": examples,
        "warnings": warnings,
        "to_enqueue": len(blind_candidates(conn, campaign_id)),
        "average_cost": average_cost(conn),
    }


def _checks(a: sqlite3.Row | None) -> list[dict[str, Any]]:
    return loads(a["validation_json"], {}).get("references", []) if a else []


# ----------------------------------------------------------------- temps : manuel vs assisté


def set_baseline(
    conn: sqlite3.Connection, campaign_id: str, minutes: float, findings: int, source: str = "saisi"
) -> dict[str, Any]:
    if minutes <= 0 or findings <= 0:
        raise CalibrationError("Temps et nombre de findings doivent être positifs.")
    campaign = store.get_campaign(conn, campaign_id)
    baseline = {
        "minutes": round(float(minutes), 1),
        "findings": int(findings),
        "source": source,
        "recorded_at": utcnow(),
    }
    cfg = campaign["config"]
    cfg["manual_baseline"] = baseline
    store.update_campaign_config(conn, campaign_id, cfg)
    return baseline


def time_gain(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    """Temps manuel de référence (par finding) contre temps de revue assistée mesuré dans Paladin."""
    baseline = store.get_campaign(conn, campaign_id)["config"].get("manual_baseline")
    times = [
        r[0]
        for r in conn.execute(
            "SELECT e.created_at FROM decision_event e JOIN finding f ON f.id = e.finding_id WHERE f.campaign_id = ?"
            " AND e.action IN ('accept', 'correct', 'investigate') AND e.authority = 'human'",
            (campaign_id,),
        )
    ]
    hours = _active_hours(times)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state IN ('to_review', 'reexam_required')",
        (campaign_id,),
    ).fetchone()[0]
    out: dict[str, Any] = {
        "baseline": baseline,
        "manual_min": round(baseline["minutes"] / baseline["findings"], 1) if baseline else None,
        "assisted_decisions": len(times),
        "assisted_hours": round(hours, 2),
        "assisted_min": round(hours * 60 / len(times), 1) if len(times) >= MIN_ASSISTED_DECISIONS and hours else None,
        "remaining": remaining,
        "agent_cost": average_cost(conn),
    }
    if out["manual_min"] is not None and out["assisted_min"] is not None:
        out["saved_min"] = round(out["manual_min"] - out["assisted_min"], 1)
        out["remaining_saved_hours"] = round(out["saved_min"] * remaining / 60, 1)
    return out

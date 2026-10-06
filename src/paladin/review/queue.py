"""File de revue : vues, ordre stable, compteurs et données de la carte.

L'ordre est global et déterministe (outil, famille, chemin, ligne, identifiant).
« Suivant » = premier finding *après la position courante* dans cet ordre qui
appartient à la vue : décider ne réordonne jamais la file sous le curseur.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from paladin.analysis import excerpt_for_finding, latest_analysis
from paladin.classify import FAMILIES, ROUTE_CHECKLIST
from paladin.contracts import ExportState, ProcessingState, ReviewState
from paladin.review.decisions import current_decision, events, get_draft
from paladin.util import loads

VIEWS: dict[str, str] = {
    "todo": "À revoir",
    "ready": "Proposition prête",
    "missing": "Contexte manquant",
    "investigating": "À investiguer",
    "reexam": "Réexamen requis",
    "validated": "Validés",
    "all": "Tous",
}

_ORDER = (
    "t.created_at, t.label, COALESCE(f.family, 'zz'), COALESCE(f.normalized_path, ''),"
    " COALESCE(f.line_number, 0), f.source_id"
)

_LATEST_VERDICT = "(SELECT a.proposed_verdict FROM analysis a WHERE a.finding_id = f.id ORDER BY a.seq DESC LIMIT 1)"


def _view_clause(view: str) -> str:
    to_review = f"f.review_state IN ('{ReviewState.TO_REVIEW}', '{ReviewState.REEXAM_REQUIRED}')"
    return {
        "todo": to_review,
        "ready": f"{to_review} AND f.processing_state = '{ProcessingState.PROPOSAL_READY}'"
                 f" AND {_LATEST_VERDICT} IN ('TRUE_POSITIVE', 'NOT_AN_ISSUE')",
        "missing": f"{to_review} AND ({_LATEST_VERDICT} IS NULL OR {_LATEST_VERDICT} = 'NEEDS_REVIEW'"
                   " OR f.divergent_fields_json != '[]')",
        "investigating": f"f.review_state = '{ReviewState.INVESTIGATING}'",
        "reexam": f"f.review_state = '{ReviewState.REEXAM_REQUIRED}'",
        "validated": f"f.review_state = '{ReviewState.VALIDATED}'",
        "all": "1 = 1",
    }.get(view, to_review)


def list_findings(conn: sqlite3.Connection, campaign_id: str, view: str = "todo", tool: str | None = None,
                  search: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    sql = (
        f"SELECT f.*, t.label AS tool_label, {_LATEST_VERDICT} AS proposed_verdict FROM finding f"
        f" JOIN tool t ON t.id = f.tool_id WHERE f.campaign_id = ? AND {_view_clause(view)}"
    )
    params: list[Any] = [campaign_id]
    if tool:
        sql += " AND t.label = ?"
        params.append(tool)
    if search:
        sql += " AND (f.source_id LIKE ? OR f.category LIKE ? OR f.normalized_path LIKE ? OR f.primary_rule_id LIKE ?)"
        params += [f"%{search}%"] * 4
    sql += f" ORDER BY {_ORDER} LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]


def neighbour(conn: sqlite3.Connection, campaign_id: str, finding_id: str, view: str, tool: str | None,
              direction: int = 1) -> str | None:
    """Finding suivant/précédent dans la vue, relativement à la position globale."""
    ordered = [r["id"] for r in conn.execute(
        f"SELECT f.id FROM finding f JOIN tool t ON t.id = f.tool_id WHERE f.campaign_id = ? ORDER BY {_ORDER}",
        (campaign_id,))]
    in_view = {r["id"] for r in list_findings(conn, campaign_id, view, tool, limit=100000)}
    if finding_id not in ordered:
        return next(iter(i for i in ordered if i in in_view), None)
    idx = ordered.index(finding_id)
    seq = ordered[idx + 1:] if direction > 0 else list(reversed(ordered[:idx]))
    return next((i for i in seq if i in in_view), None)


def position(conn: sqlite3.Connection, campaign_id: str, finding_id: str, view: str, tool: str | None) -> tuple[int, int]:
    ids = [r["id"] for r in list_findings(conn, campaign_id, view, tool, limit=100000)]
    return (ids.index(finding_id) + 1 if finding_id in ids else 0), len(ids)


def counters(conn: sqlite3.Connection, campaign_id: str) -> dict[str, int]:
    """Compteurs factuels : décisions, investigations, propositions en attente (aucun score)."""
    q = lambda sql: conn.execute(sql, (campaign_id,)).fetchone()[0]  # noqa: E731
    return {
        "total": q("SELECT COUNT(*) FROM finding WHERE campaign_id = ?"),
        "to_review": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state = '{ReviewState.TO_REVIEW}'"),
        "proposals_waiting": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state IN ('{ReviewState.TO_REVIEW}',"
                               f" '{ReviewState.REEXAM_REQUIRED}') AND processing_state = '{ProcessingState.PROPOSAL_READY}'"),
        "investigating": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state = '{ReviewState.INVESTIGATING}'"),
        "validated": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state = '{ReviewState.VALIDATED}'"),
        "reexam": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND review_state = '{ReviewState.REEXAM_REQUIRED}'"),
        "not_exported": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND current_decision_id IS NOT NULL"
                          f" AND export_state != '{ExportState.EXPORTED}'"),
        "stale": q(f"SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND export_state = '{ExportState.STALE}'"),
        "discussion": q("SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND discussion_required = 1"),
    }


def last_decided(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any] | None:
    """Dernière décision effective de la campagne (cible de « Annuler la dernière décision »)."""
    row = conn.execute(
        "SELECT e.*, f.source_id FROM decision_event e JOIN finding f ON f.current_decision_id = e.id"
        " WHERE f.campaign_id = ? ORDER BY e.created_at DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()
    return dict(row) if row else None


@dataclass
class Card:
    finding: dict[str, Any]
    tool: str
    details: dict[str, Any]
    cwe_ids: list[str]
    family_label: str
    checklist: tuple[str, ...]
    analysis: dict[str, Any] | None
    decision: dict[str, Any] | None
    history: list[dict[str, Any]]
    draft: dict[str, Any] | None
    excerpt: Any
    divergences: list[dict[str, Any]]
    provenance: list[dict[str, Any]]
    position: tuple[int, int]


def card(conn: sqlite3.Connection, campaign_id: str, finding_id: str, view: str, tool: str | None) -> Card:
    row = conn.execute(
        "SELECT f.*, t.label AS tool_label FROM finding f JOIN tool t ON t.id = f.tool_id WHERE f.id = ? AND f.campaign_id = ?",
        (finding_id, campaign_id),
    ).fetchone()
    if row is None:
        raise LookupError(finding_id)
    details = loads(row["details_json"], {})
    divergent = set(loads(row["divergent_fields_json"], []))
    divergences = []
    for fld in sorted(divergent):
        values = conn.execute(
            "SELECT v.value_json, r.role, r.locator FROM field_value v JOIN source_record r ON r.id = v.source_record_id"
            " WHERE v.finding_id = ? AND v.field = ? ORDER BY v.created_at DESC",
            (finding_id, fld),
        ).fetchall()
        seen, vals = set(), []
        for v in values:
            key = (v["role"], v["value_json"])
            if key not in seen:
                seen.add(key)
                vals.append({"role": v["role"], "value": loads(v["value_json"]), "locator": v["locator"]})
        divergences.append({"field": fld, "options": vals})
    provenance = [dict(r) for r in conn.execute(
        "SELECT r.role, r.locator, r.match_state, r.match_detail, r.created_at, s.original_path FROM source_record r"
        " LEFT JOIN source_file s ON s.id = r.source_file_id WHERE r.finding_id = ? ORDER BY r.created_at DESC LIMIT 6",
        (finding_id,))]
    route = row["analysis_route"] or "generic"
    return Card(
        finding=dict(row),
        tool=row["tool_label"],
        details=details,
        cwe_ids=loads(row["cwe_ids_json"], []),
        family_label=FAMILIES[row["family"]].label if row["family"] in FAMILIES else "Famille inconnue",
        checklist=ROUTE_CHECKLIST.get(route, ROUTE_CHECKLIST["generic"]),
        analysis=latest_analysis(conn, finding_id),
        decision=current_decision(conn, finding_id),
        history=list(reversed(events(conn, finding_id))),
        draft=get_draft(conn, finding_id),
        excerpt=excerpt_for_finding(conn, row),
        divergences=divergences,
        provenance=provenance,
        position=position(conn, campaign_id, finding_id, view, tool),
    )

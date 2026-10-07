"""Mémoire consultable (section 11) et mesures du pilote (section 17).

Précédents : décisions humaines sur des findings proches (même règle source, même
fichier, même famille dans la même application), avec leurs preuves, portée et
contradictions. Recherche d'abord par filtres SQL et texte ; pas d'index vectoriel.

Les findings du jeu de référence ne sont jamais montrés comme précédents à
l'agent : ils servent à mesurer les régressions de ses propositions.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

from paladin.contracts import DecisionAction, Verdict

CORRECTION_CATEGORIES = {
    "source": "source mal comprise",
    "protection": "protection manquée",
    "commit": "mauvais commit / mauvaise version",
    "context": "contexte métier",
    "definition": "définition TP / Not an issue",
    "wording": "rédaction seulement",
}
ACTIVE_GAP_MINUTES = 15


def precedents(
    conn: sqlite3.Connection, finding: sqlite3.Row | dict[str, Any], limit: int = 5, include_reference: bool = True
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT f.id, f.source_id, f.category, f.primary_rule_id, f.normalized_path, f.line_number, f.application_name,"
        " f.is_reference, e.verdict, e.comment, e.action, e.authority, e.created_at,"
        " CASE WHEN f.primary_rule_id = :rule THEN 'même règle'"
        "      WHEN f.normalized_path = :path THEN 'même fichier' ELSE 'même famille' END AS basis"
        " FROM finding f JOIN decision_event e ON e.id = f.current_decision_id"
        " WHERE f.campaign_id = :cid AND f.id != :id AND e.verdict IS NOT NULL"
        "   AND (f.primary_rule_id = :rule OR f.normalized_path = :path"
        "        OR (f.family = :family AND f.family IS NOT NULL))"
        "   AND (:ref OR f.is_reference = 0)"
        " ORDER BY (f.primary_rule_id = :rule) DESC, (f.normalized_path = :path) DESC, e.created_at DESC LIMIT :limit",
        {
            "cid": finding["campaign_id"],
            "id": finding["id"],
            "rule": finding["primary_rule_id"],
            "path": finding["normalized_path"],
            "family": finding["family"],
            "ref": int(include_reference),
            "limit": limit,
        },
    ).fetchall()
    items = [dict(r) for r in rows]
    same_rule = {r["verdict"] for r in items if r["basis"] == "même règle"}
    return {"items": items, "contradiction": len(same_rule) > 1}


def search(conn: sqlite3.Connection, campaign_id: str, text: str, limit: int = 30) -> list[dict[str, Any]]:
    """Recherche textuelle dans les décisions, commentaires et justifications."""
    like = f"%{text}%"
    rows = conn.execute(
        "SELECT DISTINCT f.id, f.source_id, f.category, f.normalized_path, f.line_number, e.verdict, e.comment"
        " FROM finding f LEFT JOIN decision_event e ON e.id = f.current_decision_id"
        " LEFT JOIN analysis a ON a.finding_id = f.id WHERE f.campaign_id = ? AND (e.comment LIKE ? OR"
        " e.investigation_question LIKE ? OR a.summary LIKE ? OR f.category LIKE ? OR f.source_comments LIKE ?)"
        " LIMIT ?",
        (campaign_id, like, like, like, like, like, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _active_hours(times: list[str]) -> float:
    """Temps de revue actif : somme des écarts entre décisions consécutives inférieurs à 15 minutes."""
    stamps = sorted(datetime.fromisoformat(t) for t in times)
    total = 0.0
    for a, b in itertools.pairwise(stamps):
        gap = (b - a).total_seconds() / 60
        if gap <= ACTIVE_GAP_MINUTES:
            total += gap
    return total / 60


def pilot_metrics(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    """Mesures avec effectifs (jamais de pourcentage seul)."""
    findings = conn.execute(
        "SELECT f.*, e.verdict AS d_verdict, e.action AS d_action, e.authority AS d_authority, e.comment AS d_comment,"
        " e.correction_category AS d_category,"
        " (SELECT a.proposed_verdict FROM analysis a WHERE a.finding_id = f.id ORDER BY a.seq DESC LIMIT 1)"
        "   AS p_verdict,"
        " (SELECT a.is_simulated FROM analysis a WHERE a.finding_id = f.id ORDER BY a.seq DESC LIMIT 1) AS p_sim"
        " FROM finding f LEFT JOIN decision_event e ON e.id = f.current_decision_id WHERE f.campaign_id = ?",
        (campaign_id,),
    ).fetchall()
    proposals = [f for f in findings if f["p_verdict"]]
    decided = [f for f in findings if f["d_verdict"]]
    compared = [f for f in decided if f["p_verdict"] in (Verdict.TRUE_POSITIVE, Verdict.NOT_AN_ISSUE)]
    verdict_changed = [f for f in compared if f["p_verdict"] != f["d_verdict"]]
    missed_tp = [
        f["source_id"]
        for f in compared
        if f["p_verdict"] == Verdict.NOT_AN_ISSUE and f["d_verdict"] == Verdict.TRUE_POSITIVE
    ]
    overcalled = [
        f["source_id"]
        for f in compared
        if f["p_verdict"] == Verdict.TRUE_POSITIVE and f["d_verdict"] == Verdict.NOT_AN_ISSUE
    ]
    comment_only = [f for f in compared if f["p_verdict"] == f["d_verdict"] and f["d_action"] == DecisionAction.CORRECT]
    accepted = [f for f in compared if f["d_action"] == DecisionAction.ACCEPT]
    bad_refs = conn.execute(
        "SELECT COUNT(*) FROM evidence e JOIN finding f ON f.id = e.finding_id WHERE f.campaign_id = ?"
        " AND e.reference_check != 'verified'",
        (campaign_id,),
    ).fetchone()[0]
    all_refs = conn.execute(
        "SELECT COUNT(*) FROM evidence e JOIN finding f ON f.id = e.finding_id WHERE f.campaign_id = ?", (campaign_id,)
    ).fetchone()[0]
    reference = [f for f in decided if f["is_reference"]]
    reference_agree = [f for f in reference if f["p_verdict"] == f["d_verdict"]]
    times = [
        r[0]
        for r in conn.execute(
            "SELECT e.created_at FROM decision_event e JOIN finding f ON f.id = e.finding_id WHERE f.campaign_id = ?"
            " AND e.action IN ('accept', 'correct', 'investigate') AND e.authority = 'human'",
            (campaign_id,),
        )
    ]
    hours = _active_hours(times)
    individual = sum(1 for f in decided if f["d_authority"] == "human")
    return {
        "findings": len(findings),
        "proposals": len(proposals),
        "proposals_simulated": sum(1 for f in proposals if f["p_sim"]),
        "abstentions": sum(1 for f in proposals if f["p_verdict"] == Verdict.NEEDS_REVIEW),
        "decided": len(decided),
        "decided_individual": individual,
        "decided_batch": len(decided) - individual,
        "decided_tp": sum(1 for f in decided if f["d_verdict"] == Verdict.TRUE_POSITIVE),
        "decided_nai": sum(1 for f in decided if f["d_verdict"] == Verdict.NOT_AN_ISSUE),
        "investigating": sum(1 for f in findings if f["review_state"] == "investigating"),
        "compared": len(compared),
        "accepted": len(accepted),
        "verdict_changed": len(verdict_changed),
        "comment_only": len(comment_only),
        "missed_tp": missed_tp,
        "overcalled": overcalled,
        "bad_references": bad_refs,
        "all_references": all_refs,
        "reference_total": len(reference),
        "reference_agree": len(reference_agree),
        "categories": Counter(
            CORRECTION_CATEGORIES.get(f["d_category"], f["d_category"]) for f in decided if f["d_category"]
        ),
        "active_hours": round(hours, 2),
        "decisions_per_hour": round(len(times) / hours, 1) if hours >= 0.05 else None,
    }

"""Rapprochement inter-outils (section 22).

Répond à « ce finding est-il aussi signalé par cet autre outil, et avec quelle
criticité ? », sans refaire l'analyse et sans propager de verdict.

* Candidats bornés et explicables : même fichier (chemin normalisé, ou à défaut
  même nom de fichier), puis proximité de ligne, fonction, famille et CWE. La
  CWE ou la ligne seules ne suffisent jamais.
* Liens un-vers-plusieurs et plusieurs-vers-plusieurs ; aucune transitivité.
* Un rejet est conservé : le même faux ami n'est pas reproposé sans changement.
* Toute décision est un événement (annulable) ; seuls les liens `same_occurrence`
  confirmés alimentent `Found in <outil>` (projection, section 22.5).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from paladin import store
from paladin.contracts import (
    FOUND_IN_NO_CONFIRMED,
    FOUND_IN_PENDING,
    FOUND_IN_UNKNOWN,
    FOUND_IN_YES,
    Completeness,
    ExportState,
    RelationState,
    RelationType,
)
from paladin.store import ConflictError
from paladin.util import dumps, loads, new_id, utcnow

COMPARATOR_VERSION = "cmp-1"
LINE_NEAR = 3
LINE_FAR = 15
MAX_CANDIDATES = 3
MIN_SCORE = 50
EXACT_SCORE = 100


class MatchingError(ValueError):
    pass


def _basename(path: str | None) -> str | None:
    return re.split(r"[/\\]", path)[-1] if path else None


@dataclass
class Candidate:
    a: sqlite3.Row
    b: sqlite3.Row
    score: int
    proposed_type: RelationType
    evidence: list[str]
    differences: list[str]
    cross_version: bool


def score_pair(a: sqlite3.Row, b: sqlite3.Row) -> Candidate | None:
    same_path = bool(a["normalized_path"]) and a["normalized_path"] == b["normalized_path"]
    same_base = (
        not same_path
        and _basename(a["normalized_path"] or a["full_filename"])
        == _basename(b["normalized_path"] or b["full_filename"])
        and _basename(a["normalized_path"] or a["full_filename"]) is not None
    )
    if not (same_path or same_base):
        return None  # la CWE ou la ligne seules ne prouvent rien
    evidence, differences = [], []
    score = 40 if same_path else 20
    evidence.append(
        f"même fichier {a['normalized_path']}"
        if same_path
        else f"même nom de fichier {_basename(a['normalized_path'] or a['full_filename'])}"
    )
    la, lb = a["line_number"], b["line_number"]
    delta = abs(la - lb) if la is not None and lb is not None else None
    if delta is None:
        differences.append("ligne absente d'un côté")
    elif delta == 0:
        score += 30
        evidence.append(f"même ligne {la}")
    elif delta <= LINE_NEAR:
        score += 20
        evidence.append(f"lignes proches {la} / {lb}")
    elif delta <= LINE_FAR:
        score += 10
        differences.append(f"lignes éloignées {la} / {lb}")
    else:
        differences.append(f"lignes distantes {la} / {lb}")
    same_func = bool(a["function_name"]) and a["function_name"] == b["function_name"]
    if same_func:
        score += 10
        evidence.append(f"même fonction {a['function_name']}")
    same_family = bool(a["family"]) and a["family"] == b["family"]
    cwe_a, cwe_b = set(loads(a["cwe_ids_json"], [])), set(loads(b["cwe_ids_json"], []))
    common_cwe = sorted(cwe_a & cwe_b)
    if same_family:
        score += 20
        evidence.append(f"même famille ({a['family']})")
    if common_cwe:
        score += 10
        evidence.append(f"CWE commune {', '.join(common_cwe)}")
    if not same_family and not common_cwe:
        score -= 30
        differences.append(f"familles différentes ({a['family'] or '?'} / {b['family'] or '?'})")
    if (a["category"] or "") != (b["category"] or ""):
        differences.append(f"catégories : « {a['category'] or '—'} » / « {b['category'] or '—'} »")
    if (a["criticality_raw"] or "") != (b["criticality_raw"] or ""):
        differences.append(f"criticités brutes : {a['criticality_raw'] or '—'} / {b['criticality_raw'] or '—'}")
    va, vb = a["version_name"], b["version_name"]
    cross_version = bool(va and vb and va != vb)
    if cross_version:
        differences.append(f"versions différentes ({va} / {vb}) : rapprochement inter-version")
    score = max(0, min(score, EXACT_SCORE))
    if same_path and same_family and (same_func or (delta is not None and delta <= LINE_NEAR)):
        kind = RelationType.SAME_OCCURRENCE
    elif same_path and (same_family or common_cwe):
        kind = RelationType.SAME_ROOT_CAUSE
    else:
        kind = RelationType.RELATED
    return Candidate(a, b, score, kind, evidence, differences, cross_version)


# ---------------------------------------------------------------------------
# Campagne de comparaison
# ---------------------------------------------------------------------------


@dataclass
class ComparisonResult:
    run_id: str
    tool_a: str
    tool_b: str
    completeness: str
    comparable: bool
    pairs_scored: int = 0
    new: int = 0
    unchanged: int = 0
    reproposed: int = 0
    reexam: int = 0
    without_candidate: int = 0
    notes: list[str] = field(default_factory=list)


def _tool_completeness(conn: sqlite3.Connection, tool_id: str) -> str:
    rows = conn.execute(
        "SELECT r.completeness FROM import_run r WHERE r.tool_id = ? AND r.started_at = ("
        " SELECT MAX(r2.started_at) FROM import_run r2 WHERE r2.tool_id = r.tool_id AND"
        " COALESCE(r2.source_file_id, '') = COALESCE(r.source_file_id, ''))",
        (tool_id,),
    ).fetchall()
    if not rows:
        return Completeness.UNKNOWN.value
    values = {r["completeness"] for r in rows}
    if values == {Completeness.COMPLETE.value}:
        return Completeness.COMPLETE.value
    return Completeness.PARTIAL.value if Completeness.PARTIAL.value in values else Completeness.UNKNOWN.value


def _pair_tools(conn: sqlite3.Connection, campaign_id: str, label_a: str, label_b: str) -> tuple[dict, dict]:
    ta, tb = store.get_tool(conn, campaign_id, label_a), store.get_tool(conn, campaign_id, label_b)
    return (ta, tb) if ta["label"] <= tb["label"] else (tb, ta)


def _event(
    conn,
    relation_id: str,
    action: str,
    author: str,
    relation_type: str | None = None,
    batch_id: str | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO relation_event (id, relation_id, action, relation_type, author, batch_id, reason, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), relation_id, action, relation_type, author, batch_id, reason, utcnow()),
    )


def compare(conn: sqlite3.Connection, campaign_id: str, label_a: str, label_b: str) -> ComparisonResult:
    """Prépare les candidats entre deux outils (idempotent, rejets conservés)."""
    ta, tb = _pair_tools(conn, campaign_id, label_a, label_b)
    if ta["id"] == tb["id"]:
        raise MatchingError("Choisir deux outils différents.")
    comp_a, comp_b = _tool_completeness(conn, ta["id"]), _tool_completeness(conn, tb["id"])
    completeness = (
        Completeness.COMPLETE.value
        if comp_a == comp_b == Completeness.COMPLETE.value
        else (
            Completeness.PARTIAL.value if Completeness.PARTIAL.value in (comp_a, comp_b) else Completeness.UNKNOWN.value
        )
    )
    fa = conn.execute("SELECT * FROM finding WHERE tool_id = ?", (ta["id"],)).fetchall()
    fb = conn.execute("SELECT * FROM finding WHERE tool_id = ?", (tb["id"],)).fetchall()
    comparable = completeness == Completeness.COMPLETE.value and bool(fa) and bool(fb)
    run_id = new_id()
    res = ComparisonResult(run_id, ta["label"], tb["label"], completeness, comparable)
    if not comparable:
        res.notes.append(
            f"Corpus non comparable ({ta['label']} : {comp_a}, {tb['label']} : {comp_b}) :"
            " les colonnes comparatives resteront « Unknown »."
        )
    by_path: dict[str, list[sqlite3.Row]] = {}
    by_base: dict[str, list[sqlite3.Row]] = {}
    for b in fb:
        if b["normalized_path"]:
            by_path.setdefault(b["normalized_path"], []).append(b)
        base = _basename(b["normalized_path"] or b["full_filename"])
        if base:
            by_base.setdefault(base, []).append(b)
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO comparison_run (id, campaign_id, tool_a_id, tool_b_id, corpus_json, filters_json,"
            " completeness, comparable, comparator_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                campaign_id,
                ta["id"],
                tb["id"],
                dumps(
                    {
                        ta["label"]: {"findings": len(fa), "completeness": comp_a},
                        tb["label"]: {"findings": len(fb), "completeness": comp_b},
                    }
                ),
                dumps(
                    {
                        "line_near": LINE_NEAR,
                        "line_far": LINE_FAR,
                        "max_candidates": MAX_CANDIDATES,
                        "min_score": MIN_SCORE,
                    }
                ),
                completeness,
                int(comparable),
                COMPARATOR_VERSION,
                utcnow(),
            ),
        )
        for a in fa:
            pool = {b["id"]: b for b in by_path.get(a["normalized_path"] or "", [])}
            for b in by_base.get(_basename(a["normalized_path"] or a["full_filename"]) or "", []):
                pool.setdefault(b["id"], b)
            scored = [c for c in (score_pair(a, b) for b in pool.values()) if c and c.score >= MIN_SCORE]
            res.pairs_scored += len(pool)
            scored.sort(key=lambda c: (-c.score, c.b["source_id"]))
            if not scored:
                res.without_candidate += 1
            for cand in scored[:MAX_CANDIDATES]:
                _store_candidate(conn, run_id, cand, res)
    return res


def _store_candidate(conn: sqlite3.Connection, run_id: str, c: Candidate, res: ComparisonResult) -> None:
    now = utcnow()
    row = conn.execute(
        "SELECT * FROM finding_relation WHERE finding_a_id = ? AND finding_b_id = ?", (c.a["id"], c.b["id"])
    ).fetchone()
    payload = (dumps({"score": c.score}), dumps(c.evidence), dumps(c.differences), int(c.cross_version))
    if row is None:
        rid = new_id()
        conn.execute(
            "INSERT INTO finding_relation (id, comparison_run_id, finding_a_id, finding_b_id, proposed_type, state,"
            " score_json, evidence_json, differences_json, cross_version, comparator_version, revision, created_at,"
            " updated_at, fingerprint_a, fingerprint_b, score)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (
                rid,
                run_id,
                c.a["id"],
                c.b["id"],
                c.proposed_type.value,
                RelationState.PROPOSED.value,
                *payload,
                COMPARATOR_VERSION,
                now,
                now,
                c.a["fingerprint"],
                c.b["fingerprint"],
                c.score,
            ),
        )
        _event(conn, rid, "propose", "comparateur", c.proposed_type.value)
        res.new += 1
        return
    changed = row["fingerprint_a"] != c.a["fingerprint"] or row["fingerprint_b"] != c.b["fingerprint"]
    if not changed:
        res.unchanged += 1
        return
    state = row["state"]
    if state == RelationState.CONFIRMED:
        new_state, action = RelationState.REEXAM_REQUIRED, "invalidate"
        res.reexam += 1
    elif state == RelationState.REJECTED:
        new_state, action = RelationState.PROPOSED, "repropose"
        res.reproposed += 1
    else:
        new_state, action = RelationState(state), "rescore"
    conn.execute(
        "UPDATE finding_relation SET comparison_run_id = ?, proposed_type = ?, state = ?, score_json = ?,"
        " evidence_json = ?, differences_json = ?, cross_version = ?, fingerprint_a = ?, fingerprint_b = ?, score = ?,"
        " revision = revision + 1, updated_at = ? WHERE id = ?",
        (
            run_id,
            c.proposed_type.value,
            new_state.value,
            *payload,
            c.a["fingerprint"],
            c.b["fingerprint"],
            c.score,
            now,
            row["id"],
        ),
    )
    _event(conn, row["id"], action, "comparateur", c.proposed_type.value, reason="source modifiée")
    _touch_export(conn, [row["finding_a_id"], row["finding_b_id"]])


def compare_all(conn: sqlite3.Connection, campaign_id: str) -> list[ComparisonResult]:
    labels = sorted(t["label"] for t in store.list_tools(conn, campaign_id))
    return [compare(conn, campaign_id, a, b) for i, a in enumerate(labels) for b in labels[i + 1 :]]


# ---------------------------------------------------------------------------
# Décisions de rapprochement
# ---------------------------------------------------------------------------

ACTIONS = {"confirm", "reject", "defer", "undo"}


def _touch_export(conn: sqlite3.Connection, finding_ids: list[str]) -> None:
    """Un lien qui change rend l'Excel déjà exporté périmé pour ces findings."""
    conn.execute(
        f"UPDATE finding SET export_state = ? WHERE export_state = ? AND id IN ({', '.join('?' * len(finding_ids))})",
        (ExportState.STALE.value, ExportState.EXPORTED.value, *finding_ids),
    )


def decide(
    conn: sqlite3.Connection,
    relation_id: str,
    action: str,
    *,
    author: str,
    expected_revision: int,
    relation_type: RelationType | str | None = None,
    batch_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if action not in ACTIONS:
        raise MatchingError(f"Action inconnue : {action}")
    with store.transaction(conn):
        rel = conn.execute("SELECT * FROM finding_relation WHERE id = ?", (relation_id,)).fetchone()
        if rel is None:
            raise MatchingError("Lien inconnu.")
        if rel["revision"] != expected_revision:
            raise ConflictError("Ce lien a changé depuis l'affichage : recharger avant de décider.")
        if action == "confirm":
            kind = RelationType(relation_type or rel["proposed_type"])
            if kind == RelationType.DIFFERENT:
                raise MatchingError("Pour « Différent », utiliser l'action rejeter.")
            new_state, confirmed_type = RelationState.CONFIRMED, kind.value
        elif action == "reject":
            new_state, confirmed_type = RelationState.REJECTED, RelationType.DIFFERENT.value
        elif action == "defer":
            new_state, confirmed_type = RelationState(rel["state"]), rel["confirmed_type"]
        else:  # undo : revenir à l'état d'avant la dernière décision humaine
            events = conn.execute(
                "SELECT * FROM relation_event WHERE relation_id = ? AND action IN ('confirm', 'reject', 'undo')"
                " ORDER BY created_at",
                (relation_id,),
            ).fetchall()
            stack: list[sqlite3.Row] = []
            for e in events:
                if e["action"] == "undo":
                    if stack:
                        stack.pop()
                else:
                    stack.append(e)
            if not stack:
                raise MatchingError("Aucune décision à annuler sur ce lien.")
            stack.pop()
            prev = stack[-1] if stack else None
            if prev is None:
                new_state, confirmed_type = RelationState.PROPOSED, None
            elif prev["action"] == "confirm":
                new_state, confirmed_type = RelationState.CONFIRMED, prev["relation_type"]
            else:
                new_state, confirmed_type = RelationState.REJECTED, RelationType.DIFFERENT.value
        conn.execute(
            "UPDATE finding_relation SET state = ?, confirmed_type = ?, revision = revision + 1, updated_at = ?"
            " WHERE id = ?",
            (new_state.value, confirmed_type, utcnow(), relation_id),
        )
        _event(conn, relation_id, action, author, confirmed_type, batch_id, reason)
        if action != "defer":
            _touch_export(conn, [rel["finding_a_id"], rel["finding_b_id"]])
    return dict(conn.execute("SELECT * FROM finding_relation WHERE id = ?", (relation_id,)).fetchone())


def exact_candidates(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    """Candidats homogènes pour une validation de lot : même fichier, même ligne, même famille, même version."""
    rows = conn.execute(
        "SELECT r.*, fa.source_id AS a_sid, fb.source_id AS b_sid, ta.label AS a_tool, tb.label AS b_tool,"
        " fa.normalized_path AS a_path, fa.line_number AS a_line FROM finding_relation r"
        " JOIN finding fa ON fa.id = r.finding_a_id JOIN finding fb ON fb.id = r.finding_b_id"
        " JOIN tool ta ON ta.id = fa.tool_id JOIN tool tb ON tb.id = fb.tool_id"
        " WHERE fa.campaign_id = ? AND r.state = 'proposed' AND r.proposed_type = 'same_occurrence'"
        " AND r.score >= ? AND r.cross_version = 0",
        (campaign_id, EXACT_SCORE - 10),
    ).fetchall()
    return [dict(r) for r in rows if any(e.startswith("même ligne") for e in loads(r["evidence_json"], []))]


def confirm_batch(conn: sqlite3.Connection, campaign_id: str, relation_ids: list[str], author: str) -> str:
    """Confirme une liste figée de liens ; un événement par lien, portant l'identifiant du lot."""
    batch_id = new_id()
    allowed = {r["id"]: r for r in exact_candidates(conn, campaign_id)}
    for rid in relation_ids:
        if rid not in allowed:
            raise MatchingError("La liste a changé depuis l'affichage : recharger avant de valider le lot.")
    for rid in relation_ids:
        decide(
            conn,
            rid,
            "confirm",
            author=author,
            expected_revision=allowed[rid]["revision"],
            relation_type=RelationType.SAME_OCCURRENCE,
            batch_id=batch_id,
            reason="validation de lot",
        )
    return batch_id


# ---------------------------------------------------------------------------
# Projection des colonnes comparatives (section 22.5)
# ---------------------------------------------------------------------------


@dataclass
class Projection:
    found_in: str
    criticality: str | None
    relation_ids: list[str]


def projection(conn: sqlite3.Connection, finding: sqlite3.Row | dict[str, Any], other_tool_id: str) -> Projection:
    rows = conn.execute(
        "SELECT r.*, o.source_id AS other_source_id, o.criticality_raw AS other_criticality FROM finding_relation r"
        " JOIN finding o ON o.id = CASE WHEN r.finding_a_id = ? THEN r.finding_b_id ELSE r.finding_a_id END"
        " WHERE (r.finding_a_id = ? OR r.finding_b_id = ?) AND o.tool_id = ?",
        (finding["id"], finding["id"], finding["id"], other_tool_id),
    ).fetchall()
    confirmed = [
        r
        for r in rows
        if r["state"] == RelationState.CONFIRMED
        and r["confirmed_type"] == RelationType.SAME_OCCURRENCE
        and not r["cross_version"]
    ]
    if confirmed:
        confirmed.sort(key=lambda r: r["other_source_id"])
        if len(confirmed) == 1:
            crit = confirmed[0]["other_criticality"]
        else:
            crit = "; ".join(f"{r['other_source_id']}: {r['other_criticality'] or '—'}" for r in confirmed)
        return Projection(FOUND_IN_YES, crit, [r["id"] for r in confirmed])
    pending = [r for r in rows if r["state"] in (RelationState.PROPOSED, RelationState.REEXAM_REQUIRED)]
    if pending:
        return Projection(FOUND_IN_PENDING, None, [r["id"] for r in pending])
    tool_ids = sorted([finding["tool_id"], other_tool_id])
    run = conn.execute(
        "SELECT * FROM comparison_run WHERE ((tool_a_id = ? AND tool_b_id = ?) OR (tool_a_id = ? AND tool_b_id = ?))"
        " ORDER BY created_at DESC LIMIT 1",
        (tool_ids[0], tool_ids[1], tool_ids[1], tool_ids[0]),
    ).fetchone()
    if run is None or not run["comparable"]:
        return Projection(FOUND_IN_UNKNOWN, None, [])
    return Projection(FOUND_IN_NO_CONFIRMED, None, [])


def counters(conn: sqlite3.Connection, campaign_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT r.state, COUNT(*) AS n FROM finding_relation r JOIN finding f ON f.id = r.finding_a_id"
        " WHERE f.campaign_id = ? GROUP BY r.state",
        (campaign_id,),
    ).fetchall()
    out = {s.value: 0 for s in RelationState}
    out.update({r["state"]: r["n"] for r in rows})
    return out

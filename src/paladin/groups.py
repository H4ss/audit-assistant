"""Groupes de revue et validation de lot (section 12).

Deux sources de groupes candidats :
  * une règle active : membres qui en remplissent toutes les conditions ;
  * un même point d'impact (même outil, même règle source, même fichier:ligne) :
    candidats « même cause racine », qui ne prouvent pas que les cas sont équivalents.

L'homogénéité se vérifie membre par membre : un échantillon revu ne démontre
rien pour les autres. Un membre est exclu s'il est déjà décidé, en
investigation, en exception, en collision, sans proposition individuelle, avec
une proposition contraire ou indéterminée, ou avec des références invalides.
Les différences (source, version) restent visibles.

Un lot applique une décision par membre de la liste figée, avec l'autorité
« lot », l'identifiant du lot et la règle/version. Un lot s'annule ; les membres
modifiés depuis ne sont pas touchés et sont listés.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from paladin import rules as rules_mod
from paladin import store
from paladin.contracts import Authority, DecisionAction, ReviewState, Verdict
from paladin.review import decisions
from paladin.util import dumps, loads, new_id, utcnow

_LINE_REF = re.compile(r"(\b(ligne|line|l\.)\s*\d+)|(\w\.\w{1,6}:\d+)", re.IGNORECASE)


class BatchError(ValueError):
    pass


@dataclass
class Member:
    finding_id: str
    source_id: str
    revision: int
    location: str
    source: str | None
    proposed: str | None
    eligible: bool
    reason: str | None = None
    differences: list[str] = field(default_factory=list)


@dataclass
class GroupView:
    key: str  # rule:<id> | sink:<tool>|<rule>|<path:line>
    kind: str  # rule | root_cause
    title: str
    verdict: str | None  # verdict proposé pour le lot (règle) ; None = à choisir
    comment: str | None
    rule: rules_mod.Rule | None
    members: list[Member]

    @property
    def eligible(self) -> list[Member]:
        return [m for m in self.members if m.eligible]

    @property
    def excluded(self) -> list[Member]:
        return [m for m in self.members if not m.eligible]


def _source_of(f: sqlite3.Row) -> str | None:
    trace = (loads(f["details_json"], {}) or {}).get("trace") or []
    for node in trace:
        if (node.get("nodeType") or "").lower() == "source":
            return f"{node.get('file', '?').rsplit('/', 1)[-1]}:{node.get('line', '?')}"
    return None


def _latest_analysis(conn: sqlite3.Connection, finding_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM analysis WHERE finding_id = ? ORDER BY seq DESC LIMIT 1", (finding_id,)
    ).fetchone()


def _member(
    conn: sqlite3.Connection, f: sqlite3.Row, verdict: str | None, reference: sqlite3.Row | None, exceptions: list[str]
) -> Member:
    a = _latest_analysis(conn, f["id"])
    proposed = a["proposed_verdict"] if a else None
    m = Member(
        f["id"],
        f["source_id"],
        f["revision"],
        f"{f['normalized_path']}:{f['line_number']}",
        _source_of(f),
        proposed,
        True,
    )
    if reference is not None and f["id"] != reference["id"]:
        if _source_of(reference) and m.source != _source_of(reference):
            m.differences.append(f"source {m.source or 'inconnue'} ≠ exemple {_source_of(reference)}")
        if (f["version_name"] or "") != (reference["version_name"] or ""):
            m.differences.append(f"version {f['version_name']} ≠ {reference['version_name']}")
    collisions = conn.execute(
        "SELECT COUNT(*) FROM fingerprint_collision WHERE finding_id = ? AND status = 'open'", (f["id"],)
    ).fetchone()[0]
    reason = None
    if f["review_state"] == ReviewState.VALIDATED:
        reason = "déjà décidé"
    elif f["review_state"] == ReviewState.INVESTIGATING:
        reason = "en investigation"
    elif f["source_id"] in exceptions:
        reason = "exception de la règle"
    elif collisions:
        reason = "collision d'identifiant non résolue"
    elif commit_mismatch(conn, f):
        reason = "commit scanné différent du commit du dépôt : équivalence non démontrée"
    elif a is None:
        reason = "aucune proposition individuelle : analyser ce membre d'abord"
    elif proposed == Verdict.NEEDS_REVIEW:
        reason = "proposition indéterminée (contexte manquant)"
    elif verdict and proposed != verdict:
        reason = f"proposition différente ({proposed})"
    else:
        refs = loads(a["validation_json"], {}).get("references") or []
        if any(r["status"] != "verified" for r in refs):
            reason = "références de code invalides dans la proposition"
    if reason:
        m.eligible, m.reason = False, reason
    return m


def commit_mismatch(conn: sqlite3.Connection, f: sqlite3.Row | dict[str, Any]) -> str | None:
    """Message si le commit scanné diffère du commit déclaré du dépôt (les deux connus)."""
    if not f["repo_id"] or not f["commit_sha"]:
        return None
    repo = conn.execute("SELECT name, commit_sha FROM repo WHERE id = ?", (f["repo_id"],)).fetchone()
    if repo is None or not repo["commit_sha"] or repo["commit_sha"] == f["commit_sha"]:
        return None
    return f"Commit scanné {f['commit_sha']} ≠ commit du dépôt {repo['name']} ({repo['commit_sha']})"


def _majority(conn: sqlite3.Connection, findings: list[sqlite3.Row]) -> str | None:
    votes: dict[str, int] = {}
    for f in findings:
        a = _latest_analysis(conn, f["id"])
        if a and a["proposed_verdict"] in (Verdict.TRUE_POSITIVE, Verdict.NOT_AN_ISSUE):
            votes[a["proposed_verdict"]] = votes.get(a["proposed_verdict"], 0) + 1
    return max(votes, key=lambda k: votes[k]) if votes else None


def groups(conn: sqlite3.Connection, campaign_id: str) -> list[GroupView]:
    tools = {t["id"]: t["label"] for t in store.list_tools(conn, campaign_id)}
    findings = conn.execute("SELECT * FROM finding WHERE campaign_id = ? ORDER BY source_id", (campaign_id,)).fetchall()
    out: list[GroupView] = []
    for rule in rules_mod.list_rules(conn, campaign_id):
        if rule.status != "active":
            continue
        members_f = [f for f in findings if rules_mod.matches(rule, f, tools[f["tool_id"]])[0]]
        ref_id = (rule.example or {}).get("finding_id")
        reference = next((f for f in findings if f["id"] == ref_id), None)
        members = [_member(conn, f, rule.verdict, reference, rule.exceptions) for f in members_f]
        if members:
            out.append(GroupView(f"rule:{rule.id}", "rule", rule.label, rule.verdict, rule.comment, rule, members))
    sinks: dict[tuple, list[sqlite3.Row]] = {}
    for f in findings:
        if f["normalized_path"] and f["line_number"] is not None and f["primary_rule_id"]:
            sinks.setdefault((f["tool_id"], f["primary_rule_id"], f["normalized_path"], f["line_number"]), []).append(f)
    for (tool_id, rule_id, path, line), fs in sorted(sinks.items(), key=lambda kv: kv[0][2:]):
        if len(fs) < 2:
            continue
        verdict = _majority(conn, fs)
        members = [_member(conn, f, verdict, None, []) for f in fs]
        title = f"{tools[tool_id]} · {fs[0]['category'] or rule_id} · même point d'impact {path}:{line}"
        out.append(
            GroupView(f"sink:{tool_id}|{rule_id}|{path}:{line}", "root_cause", title, verdict, None, None, members)
        )
    return out


def find(conn: sqlite3.Connection, campaign_id: str, key: str) -> GroupView:
    for g in groups(conn, campaign_id):
        if g.key == key:
            return g
    raise BatchError("Groupe introuvable : relancer l'affichage des groupes.")


def execute(
    conn: sqlite3.Connection,
    campaign_id: str,
    key: str,
    frozen: dict[str, int],
    *,
    verdict: str,
    comment: str | None,
    author: str,
) -> str:
    """Applique le lot à la liste figée {finding_id: révision affichée}."""
    if verdict not in (Verdict.TRUE_POSITIVE, Verdict.NOT_AN_ISSUE):
        raise BatchError("Verdict de lot : True Positive ou Not an issue.")
    if comment and _LINE_REF.search(comment):
        raise BatchError(
            "Un commentaire partagé ne cite pas de ligne de code : les références restent propres à chaque"
            " finding (laisser le commentaire générique)."
        )
    if not frozen:
        raise BatchError("Aucun membre sélectionné.")
    group = find(conn, campaign_id, key)
    by_id = {m.finding_id: m for m in group.members}
    for fid, rev in frozen.items():
        m = by_id.get(fid)
        if m is None or not m.eligible or m.revision != rev:
            raise BatchError(
                "La liste a changé depuis l'affichage (membre modifié, décidé ou devenu inéligible) :"
                " recharger le groupe avant de valider."
            )
        if group.verdict and verdict != group.verdict:
            raise BatchError("Le verdict du lot diffère de celui de la règle : décider individuellement.")
    batch_id, gid = new_id(), new_id()
    rule = group.rule
    excluded = [
        {"finding_id": m.finding_id, "source_id": m.source_id, "reason": m.reason or "retiré par l'analyste"}
        for m in group.members
        if m.finding_id not in frozen
    ]
    with store.transaction(conn):
        conn.execute(
            "INSERT INTO review_group (id, campaign_id, kind, rule_id, rule_version, criteria_json, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'validated', ?)",
            (
                gid,
                campaign_id,
                "root_cause" if group.kind == "root_cause" else "similar",
                rule.id if rule else None,
                rule.version if rule else None,
                dumps({"key": key, "title": group.title}),
                utcnow(),
            ),
        )
        for m in group.members:
            conn.execute(
                "INSERT INTO group_member (group_id, finding_id, comparison_json, eligible, exclusion_reason)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    gid,
                    m.finding_id,
                    dumps(asdict(m)),
                    int(m.finding_id in frozen),
                    None if m.finding_id in frozen else (m.reason or "retiré par l'analyste"),
                ),
            )
        conn.execute(
            "INSERT INTO batch (id, group_id, member_ids_json, excluded_json, verdict, comment, rule_id, rule_version,"
            " author, created_at, campaign_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                gid,
                dumps(sorted(frozen)),
                dumps(excluded),
                verdict,
                comment or None,
                rule.id if rule else None,
                rule.version if rule else None,
                author,
                utcnow(),
                campaign_id,
            ),
        )
    for fid, rev in frozen.items():
        analysis = _latest_analysis(conn, fid)
        decisions.record_decision(
            conn,
            fid,
            expected_revision=rev,
            action=DecisionAction.BATCH,
            author=author,
            verdict=verdict,
            comment=comment,
            analysis_id=analysis["id"] if analysis else None,
            authority=Authority.BATCH,
            batch_id=batch_id,
            rule_id=rule.id if rule else None,
            rule_version=rule.version if rule else None,
        )
    return batch_id


def undo(conn: sqlite3.Connection, batch_id: str, author: str) -> dict[str, list[str]]:
    """Annule les décisions du lot encore courantes ; les membres modifiés depuis sont listés, pas touchés."""
    batch = conn.execute("SELECT * FROM batch WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        raise BatchError("Lot inconnu.")
    if batch["undone_at"]:
        raise BatchError("Lot déjà annulé.")
    report: dict[str, list[str]] = {"annulés": [], "non touchés (modifiés depuis)": []}
    for fid in loads(batch["member_ids_json"], []):
        f = conn.execute("SELECT * FROM finding WHERE id = ?", (fid,)).fetchone()
        cur = (
            conn.execute("SELECT * FROM decision_event WHERE id = ?", (f["current_decision_id"],)).fetchone()
            if f["current_decision_id"]
            else None
        )
        if cur is not None and cur["batch_id"] == batch_id:
            decisions.undo_last(conn, fid, expected_revision=f["revision"], author=author)
            report["annulés"].append(f["source_id"])
        else:
            report["non touchés (modifiés depuis)"].append(f["source_id"])
    if batch["verdict"] == "REPRISE":
        # Reprise annulée : les cellules redeviennent des saisies humaines, que l'export ne touchera plus.
        conn.execute(
            "UPDATE export_run SET status = 'reverted' WHERE mode = 'reprise'"
            " AND json_extract(summary_json, '$.reprise_id') = ?",
            (batch_id,),
        )
        undone = list(loads(batch["member_ids_json"], []))
        conn.execute(
            "UPDATE finding SET export_state = 'not_exported', exported_decision_id = NULL, exported_run_id = NULL"
            f" WHERE current_decision_id IS NULL AND id IN ({', '.join('?' * len(undone))})",
            undone,
        )
    conn.execute(
        "UPDATE batch SET undone_at = ?, undo_report_json = ? WHERE id = ?", (utcnow(), dumps(report), batch_id)
    )
    return report


def history(conn: sqlite3.Connection, campaign_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM batch WHERE campaign_id = ? ORDER BY created_at DESC", (campaign_id,)).fetchall()
    return [
        dict(r)
        | {
            "members": loads(r["member_ids_json"], []),
            "excluded": loads(r["excluded_json"], []),
            "undo_report": loads(r["undo_report_json"]),
        }
        for r in rows
    ]

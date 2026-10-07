"""Règles réutilisables (section 11).

Une règle contient des préconditions vérifiables, une portée, des exceptions, un
exemple accepté (la décision d'origine) et un éventuel contre-exemple. Elle est
proposée, puis validée par l'analyste. Une correction isolée n'active jamais une
règle générale. Une règle n'applique rien d'elle-même : elle est montrée comme
« règle applicable » et sert de base aux lots. Sa révocation met en réexamen les
décisions qui en dérivent, sans réécrire l'historique.
"""

from __future__ import annotations

import fnmatch
import sqlite3
from dataclasses import dataclass
from typing import Any

from paladin import store
from paladin.contracts import ReviewState, RuleStatus
from paladin.util import dumps, loads, new_id, utcnow

CONDITION_KEYS = ("tool", "primary_rule_id", "family", "path_glob", "function_name", "sink")


class RuleError(ValueError):
    pass


@dataclass
class Rule:
    id: str
    version: int
    campaign_id: str | None
    title: str
    conditions: dict[str, Any]
    scope: dict[str, Any]
    exceptions: list[str]
    example: dict[str, Any] | None
    counter_example: str | None
    status: str
    verdict: str | None
    comment: str | None

    @property
    def label(self) -> str:
        return f"{self.title} (v{self.version})"


def _row_to_rule(row: sqlite3.Row) -> Rule:
    return Rule(
        row["id"],
        row["version"],
        row["campaign_id"],
        row["title"],
        loads(row["conditions_json"], {}),
        loads(row["scope_json"], {}),
        loads(row["exceptions_json"], []),
        loads(row["example_json"]),
        loads(row["counter_example_json"]),
        row["status"],
        row["verdict"],
        row["comment"],
    )


def get(conn: sqlite3.Connection, rule_id: str, version: int | None = None) -> Rule:
    sql = "SELECT * FROM rule WHERE id = ?" + (" AND version = ?" if version else " ORDER BY version DESC LIMIT 1")
    row = conn.execute(sql, (rule_id, version) if version else (rule_id,)).fetchone()
    if row is None:
        raise RuleError("Règle inconnue.")
    return _row_to_rule(row)


def list_rules(conn: sqlite3.Connection, campaign_id: str) -> list[Rule]:
    rows = conn.execute(
        "SELECT * FROM rule WHERE campaign_id = ? OR campaign_id IS NULL"
        " ORDER BY status = 'active' DESC, created_at DESC",
        (campaign_id,),
    ).fetchall()
    return [_row_to_rule(r) for r in rows]


def conditions_from_finding(f: sqlite3.Row, tool_label: str) -> dict[str, Any]:
    """Préconditions proposées à partir du finding d'exemple (modifiables avant enregistrement)."""
    cond: dict[str, Any] = {"tool": tool_label}
    if f["primary_rule_id"]:
        cond["primary_rule_id"] = f["primary_rule_id"]
    elif f["family"]:
        cond["family"] = f["family"]
    if f["function_name"]:
        cond["function_name"] = f["function_name"]
    if f["normalized_path"] and f["line_number"] is not None:
        cond["sink"] = f"{f['normalized_path']}:{f['line_number']}"
    return cond


def matches(rule: Rule, finding: sqlite3.Row | dict[str, Any], tool_label: str) -> tuple[bool, list[str]]:
    """(correspond, raisons). Chaque condition est vérifiée explicitement ; une condition inconnue échoue."""
    reasons, ok = [], True
    c = rule.conditions
    if finding["source_id"] in rule.exceptions:
        return False, ["exception déclarée dans la règle"]
    if rule.scope.get("application_name") and finding["application_name"] != rule.scope["application_name"]:
        return False, ["hors de la portée (application)"]
    for key, value in c.items():
        if key == "tool":
            good = tool_label == value
        elif key == "primary_rule_id":
            good = finding["primary_rule_id"] == value
        elif key == "family":
            good = finding["family"] == value
        elif key == "path_glob":
            good = bool(finding["normalized_path"]) and fnmatch.fnmatchcase(finding["normalized_path"], value)
        elif key == "function_name":
            good = finding["function_name"] == value
        elif key == "sink":
            good = f"{finding['normalized_path']}:{finding['line_number']}" == value
        else:
            good = False
        reasons.append(f"{key} = {value} : {'oui' if good else 'non'}")
        ok = ok and good
    return ok, reasons


def create_from_decision(
    conn: sqlite3.Connection,
    finding_id: str,
    *,
    title: str,
    author: str,
    conditions: dict[str, Any] | None = None,
    application_scope: bool = True,
    exceptions: list[str] | None = None,
    counter_example: str | None = None,
) -> Rule:
    f = conn.execute(
        "SELECT f.*, t.label AS tool_label FROM finding f JOIN tool t ON t.id = f.tool_id WHERE f.id = ?", (finding_id,)
    ).fetchone()
    if f is None or not f["current_decision_id"]:
        raise RuleError("Une règle se crée à partir d'une décision validée.")
    dec = conn.execute("SELECT * FROM decision_event WHERE id = ?", (f["current_decision_id"],)).fetchone()
    if not dec["verdict"]:
        raise RuleError("La décision d'exemple doit porter un verdict final (pas une investigation).")
    cond = {
        k: v
        for k, v in (conditions or conditions_from_finding(f, f["tool_label"])).items()
        if k in CONDITION_KEYS and v
    }
    if not set(cond) - {"tool"}:
        raise RuleError(
            "Au moins une condition vérifiable en plus de l'outil (règle, famille, chemin, fonction, sink)."
        )
    rid = new_id()
    example = {
        "finding_id": f["id"],
        "source_id": f["source_id"],
        "location": f"{f['normalized_path']}:{f['line_number']}",
        "verdict": dec["verdict"],
        "comment": dec["comment"],
        "decision_id": dec["id"],
    }
    conn.execute(
        "INSERT INTO rule (id, version, campaign_id, title, conditions_json, scope_json, exceptions_json, example_json,"
        " counter_example_json, status, created_at, verdict, comment, source_decision_id, created_by)"
        " VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rid,
            f["campaign_id"],
            title.strip() or "Règle sans titre",
            dumps(cond),
            dumps({"application_name": f["application_name"]} if application_scope else {}),
            dumps(exceptions or []),
            dumps(example),
            dumps(counter_example) if counter_example else None,
            RuleStatus.PROPOSED.value,
            utcnow(),
            dec["verdict"],
            dec["comment"],
            dec["id"],
            author,
        ),
    )
    return get(conn, rid)


def validate(conn: sqlite3.Connection, rule_id: str, author: str) -> Rule:
    rule = get(conn, rule_id)
    if rule.status != RuleStatus.PROPOSED:
        raise RuleError(f"Seule une règle proposée peut être validée (état : {rule.status}).")
    conn.execute(
        "UPDATE rule SET status = ?, validated_by = ?, validated_at = ? WHERE id = ? AND version = ?",
        (RuleStatus.ACTIVE.value, author, utcnow(), rule_id, rule.version),
    )
    return get(conn, rule_id)


def revoke(conn: sqlite3.Connection, rule_id: str, author: str, reason: str) -> int:
    """Révoque la règle ; les décisions courantes qui en dérivent passent en « réexamen requis »."""
    rule = get(conn, rule_id)
    if rule.status == RuleStatus.REVOKED:
        raise RuleError("Règle déjà révoquée.")
    with store.transaction(conn):
        conn.execute(
            "UPDATE rule SET status = ?, revoked_at = ?, revoked_by = ?, revoke_reason = ?"
            " WHERE id = ? AND version = ?",
            (RuleStatus.REVOKED.value, utcnow(), author, reason, rule_id, rule.version),
        )
        derived = conn.execute(
            "SELECT f.id FROM finding f JOIN decision_event e ON e.id = f.current_decision_id WHERE e.rule_id = ?",
            (rule_id,),
        ).fetchall()
        for row in derived:
            conn.execute(
                "UPDATE finding SET review_state = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
                (ReviewState.REEXAM_REQUIRED.value, utcnow(), row["id"]),
            )
    return len(derived)


def applicable(conn: sqlite3.Connection, finding: sqlite3.Row | dict[str, Any], tool_label: str) -> list[Rule]:
    out = []
    for r in conn.execute(
        "SELECT * FROM rule WHERE status = 'active' AND (campaign_id = ? OR campaign_id IS NULL)",
        (finding["campaign_id"],),
    ):
        rule = _row_to_rule(r)
        if matches(rule, finding, tool_label)[0]:
            out.append(rule)
    return out

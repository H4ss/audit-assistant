"""Décisions de l'analyste : journal append-only, révisions, annulation, brouillons.

* Accepter / Corriger / Lot : verdict final obligatoire (TRUE_POSITIVE ou
  NOT_AN_ISSUE) et commentaire exact, éventuellement vide.
* À investiguer : aucun verdict, une question et un motif obligatoires.
* Passer : simple trace, sans effet sur la décision courante.
* Annuler : nouvel événement qui annule la dernière décision effective ;
  l'historique n'est jamais réécrit.

Toute écriture exige la révision courante du finding (double clic, réponse
périmée) et l'incrémente.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from paladin import store
from paladin.contracts import (
    DISCUSSION_COMMENT,
    FINAL_VERDICTS,
    Authority,
    DecisionAction,
    ExportState,
    ReviewState,
    Verdict,
    verdict_to_excel,
)
from paladin.store import ConflictError, NotFoundError
from paladin.util import new_id, utcnow

EFFECTIVE_ACTIONS = {DecisionAction.ACCEPT, DecisionAction.CORRECT, DecisionAction.INVESTIGATE, DecisionAction.BATCH}


class DecisionError(ValueError):
    pass


def _finding(conn: sqlite3.Connection, finding_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM finding WHERE id = ?", (finding_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Finding inconnu : {finding_id}")
    return row


def events(conn: sqlite3.Connection, finding_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM decision_event WHERE finding_id = ? ORDER BY seq", (finding_id,))
    return [dict(r) for r in rows]


def effective_stack(evts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Décisions effectives restantes après application des annulations."""
    stack: list[dict[str, Any]] = []
    for e in evts:
        if e["action"] in EFFECTIVE_ACTIONS:
            stack.append(e)
        elif e["action"] == DecisionAction.UNDO and stack and stack[-1]["id"] == e["undoes_event_id"]:
            stack.pop()
    return stack


def current_decision(conn: sqlite3.Connection, finding_id: str) -> dict[str, Any] | None:
    row = _finding(conn, finding_id)
    if not row["current_decision_id"]:
        return None
    return dict(conn.execute("SELECT * FROM decision_event WHERE id = ?", (row["current_decision_id"],)).fetchone())


def excel_projection(decision: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(analysis result, Analysis result comment) tels qu'ils doivent apparaître dans l'Excel."""
    if decision is None or decision["action"] == DecisionAction.INVESTIGATE:
        return None, None
    verdict = Verdict(decision["verdict"]) if decision["verdict"] else None
    comment = decision["comment"] or None
    return verdict_to_excel(verdict), comment


def _export_state_after(conn, finding: sqlite3.Row, new_current: dict[str, Any] | None) -> str:
    state = finding["export_state"]
    if state not in (ExportState.EXPORTED, ExportState.STALE):
        return state
    exported = None
    if finding["exported_decision_id"]:
        exported = dict(conn.execute("SELECT * FROM decision_event WHERE id = ?", (finding["exported_decision_id"],)).fetchone())
    same = excel_projection(exported) == excel_projection(new_current)
    return ExportState.EXPORTED.value if same else ExportState.STALE.value


def _write_event(conn, finding: sqlite3.Row, action: DecisionAction, author: str, **fields: Any) -> dict[str, Any]:
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM decision_event WHERE finding_id = ?", (finding["id"],)).fetchone()[0]
    event = {
        "id": new_id(),
        "finding_id": finding["id"],
        "seq": seq,
        "action": action.value,
        "authority": fields.pop("authority", Authority.HUMAN).value,
        "author": author,
        "previous_event_id": finding["current_decision_id"],
        "finding_revision": finding["revision"],
        "created_at": utcnow(),
        "discussion_required": 0,
        **fields,
    }
    cols = ", ".join(event)
    conn.execute(f"INSERT INTO decision_event ({cols}) VALUES ({', '.join('?' * len(event))})", tuple(event.values()))
    return event


def _check_revision(finding: sqlite3.Row, expected_revision: int) -> None:
    if finding["revision"] != expected_revision:
        raise ConflictError(
            f"Révision périmée pour ce finding (attendue {expected_revision}, actuelle {finding['revision']}). "
            "La page a été mise à jour : recharger avant de décider."
        )


def record_decision(
    conn: sqlite3.Connection,
    finding_id: str,
    *,
    expected_revision: int,
    action: DecisionAction,
    author: str,
    verdict: Verdict | str | None = None,
    comment: str | None = None,
    analysis_id: str | None = None,
    discussion_required: bool | None = None,
    discussion_reason: str | None = None,
    investigation_question: str | None = None,
    investigation_reason: str | None = None,
    correction_category: str | None = None,
    authority: Authority = Authority.HUMAN,
    batch_id: str | None = None,
    rule_id: str | None = None,
    rule_version: int | None = None,
) -> dict[str, Any]:
    action = DecisionAction(action)
    if action == DecisionAction.UNDO:
        raise DecisionError("Utiliser undo_last pour annuler.")
    verdict_v = Verdict(verdict) if verdict else None
    if action in (DecisionAction.ACCEPT, DecisionAction.CORRECT, DecisionAction.BATCH):
        if verdict_v not in FINAL_VERDICTS:
            raise DecisionError("Une décision finale exige True Positive ou Not an issue. Sinon : « À investiguer ».")
    elif action == DecisionAction.INVESTIGATE:
        if verdict_v is not None:
            raise DecisionError("« À investiguer » ne porte pas de verdict.")
        if not (investigation_question or "").strip() or not (investigation_reason or "").strip():
            raise DecisionError("« À investiguer » exige une question précise et un motif.")
    if action == DecisionAction.BATCH and (authority != Authority.BATCH or not batch_id):
        raise DecisionError("Une décision de lot porte l'autorité et l'identifiant du lot.")
    if authority == Authority.BATCH and action != DecisionAction.BATCH:
        raise DecisionError("L'autorité de lot est réservée aux décisions de lot.")
    if comment is not None:
        comment = comment if comment.strip() else None
    if discussion_required is None:
        discussion_required = comment == DISCUSSION_COMMENT

    with store.transaction(conn):
        finding = _finding(conn, finding_id)
        _check_revision(finding, expected_revision)
        if action == DecisionAction.SKIP:
            event = _write_event(conn, finding, action, author)
            conn.execute("UPDATE finding SET revision = revision + 1, updated_at = ? WHERE id = ?", (utcnow(), finding_id))
            return event
        event = _write_event(
            conn, finding, action, author,
            authority=authority,
            analysis_id=analysis_id,
            verdict=verdict_v.value if verdict_v else None,
            comment=comment if action != DecisionAction.INVESTIGATE else None,
            discussion_required=int(bool(discussion_required)),
            discussion_reason=discussion_reason,
            investigation_question=investigation_question,
            investigation_reason=investigation_reason,
            correction_category=correction_category,
            batch_id=batch_id,
            rule_id=rule_id,
            rule_version=rule_version,
        )
        review = ReviewState.INVESTIGATING if action == DecisionAction.INVESTIGATE else ReviewState.VALIDATED
        export_state = _export_state_after(conn, finding, event)
        conn.execute(
            "UPDATE finding SET current_decision_id = ?, review_state = ?, export_state = ?, discussion_required = ?,"
            " discussion_reason = ?, discussion_state = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
            (event["id"], review.value, export_state, int(bool(discussion_required)), discussion_reason,
             "open" if discussion_required else None, utcnow(), finding_id),
        )
        conn.execute("DELETE FROM draft WHERE finding_id = ?", (finding_id,))
    return event


def undo_last(conn: sqlite3.Connection, finding_id: str, *, expected_revision: int, author: str) -> dict[str, Any]:
    """Annule la dernière décision effective. Le résultat Excel déjà exporté devient périmé."""
    with store.transaction(conn):
        finding = _finding(conn, finding_id)
        _check_revision(finding, expected_revision)
        stack = effective_stack(events(conn, finding_id))
        if not stack:
            raise DecisionError("Aucune décision à annuler.")
        target = stack.pop()
        event = _write_event(conn, finding, DecisionAction.UNDO, author, undoes_event_id=target["id"])
        new_current = stack[-1] if stack else None
        if new_current is None:
            review = ReviewState.TO_REVIEW
        elif new_current["action"] == DecisionAction.INVESTIGATE:
            review = ReviewState.INVESTIGATING
        else:
            review = ReviewState.VALIDATED
        export_state = _export_state_after(conn, finding, new_current)
        conn.execute(
            "UPDATE finding SET current_decision_id = ?, review_state = ?, export_state = ?, discussion_required = ?,"
            " discussion_reason = ?, revision = revision + 1, updated_at = ? WHERE id = ?",
            (new_current["id"] if new_current else None, review.value, export_state,
             int(bool(new_current and new_current["discussion_required"])),
             new_current["discussion_reason"] if new_current else None, utcnow(), finding_id),
        )
    return event


def save_draft(conn: sqlite3.Connection, finding_id: str, verdict: str | None, comment: str | None) -> None:
    conn.execute(
        "INSERT INTO draft (finding_id, verdict, comment, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (finding_id) DO UPDATE SET verdict = excluded.verdict, comment = excluded.comment,"
        " updated_at = excluded.updated_at",
        (finding_id, verdict, comment, utcnow()),
    )


def get_draft(conn: sqlite3.Connection, finding_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM draft WHERE finding_id = ?", (finding_id,)).fetchone()
    return dict(row) if row else None

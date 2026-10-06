"""Propositions d'analyse : enregistrement, vérification des références, extraits de code.

Une proposition n'est jamais une décision. Vérifier qu'une ligne citée existe
ne prouve pas que le raisonnement est juste : l'interface affiche les deux
notions séparément (« référence vérifiée » ≠ « raisonnement validé »).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paladin import __version__, store
from paladin.contracts import AgentProposal, ProcessingState
from paladin.util import dumps, loads, new_id, sha256_bytes, utcnow

EXCERPT_CONTEXT = 8


class ProposalRejected(ValueError):
    pass


@dataclass
class CodeExcerpt:
    repo: str
    path: str
    start: int
    lines: list[tuple[int, str]]
    highlight: set[int]


def _repo_for(conn: sqlite3.Connection, finding: sqlite3.Row, file_ref: str, repo_name: str | None) -> tuple[dict | None, str]:
    """Résout un fichier cité vers (dépôt autorisé, chemin relatif)."""
    repos = store.list_repos(conn, finding["campaign_id"])
    ref = file_ref.replace("\\", "/").lstrip("/")
    if repo_name:
        repo = next((r for r in repos if r["name"] == repo_name), None)
        if repo and ref.startswith(repo["name"] + "/"):
            ref = ref[len(repo["name"]) + 1 :]
        return repo, ref
    for r in repos:
        if ref.startswith(r["name"] + "/"):
            return r, ref[len(r["name"]) + 1 :]
    by_id = next((r for r in repos if r["id"] == finding["repo_id"]), None)
    return by_id, ref


def safe_repo_file(repo: dict, rel: str) -> Path | None:
    """Chemin d'un fichier du dépôt, ou None s'il sort de la racine (lecture seule)."""
    root = Path(repo["path"]).resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target if target.is_file() else None


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def check_reference(conn: sqlite3.Connection, finding: sqlite3.Row, ev: dict[str, Any]) -> tuple[str, str | None]:
    """verified | mismatch | missing_file | out_of_scope (+ extrait réel)."""
    repo, rel = _repo_for(conn, finding, ev["file"], ev.get("repo"))
    if repo is None:
        return "out_of_scope", None
    path = safe_repo_file(repo, rel)
    if path is None:
        return "missing_file", None
    lines = read_lines(path)
    start, end = ev["line_start"], ev.get("line_end") or ev["line_start"]
    if start > len(lines) or end > len(lines) or end < start:
        return "mismatch", None
    actual = "\n".join(lines[start - 1 : end])
    if ev.get("excerpt") and " ".join(ev["excerpt"].split()) not in " ".join(actual.split()):
        return "mismatch", actual
    return "verified", actual


def store_proposal(
    conn: sqlite3.Connection,
    finding_id: str,
    proposal: AgentProposal,
    *,
    job_id: str | None = None,
    model_requested: str | None = None,
    model_provider: str | None = None,
    model_resolved: str | None = None,
    skill_version: str | None = None,
    context_version: str | None = None,
    is_simulated: bool = False,
) -> dict[str, Any]:
    """Enregistre une proposition validée par schéma ; vérifie révision et références."""
    with store.transaction(conn):
        finding = conn.execute("SELECT * FROM finding WHERE id = ?", (finding_id,)).fetchone()
        if finding is None:
            raise ProposalRejected(f"Finding inconnu : {finding_id}")
        if proposal.input_revision != finding["revision"]:
            raise ProposalRejected(
                f"Proposition sur une révision périmée ({proposal.input_revision} ≠ {finding['revision']})."
            )
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM analysis WHERE finding_id = ?", (finding_id,)).fetchone()[0]
        aid = new_id()
        checked = []
        for ev in proposal.evidence:
            status, actual = check_reference(conn, finding, ev.model_dump())
            checked.append((ev, status, actual))
        checks = [{"file": ev.file, "line_start": ev.line_start, "status": st} for ev, st, _ in checked]
        validation = {"schema": "ok", "references": checks,
                      "all_references_verified": all(c["status"] == "verified" for c in checks) if checks else None}
        conn.execute(
            "INSERT INTO analysis (id, finding_id, job_id, seq, input_revision, proposed_verdict, summary,"
            " suggested_comment, discussion_required, discussion_reason, payload_json, validation_json, model_requested,"
            " model_provider, model_resolved, skill_version, software_version, context_version, is_simulated, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, finding_id, job_id, seq, proposal.input_revision, proposal.proposed_verdict.value, proposal.summary,
             proposal.suggested_analysis_result_comment, int(proposal.discussion_required), proposal.discussion_reason,
             dumps(proposal.model_dump(mode="json")), dumps(validation), model_requested, model_provider,
             model_resolved or "unknown", skill_version, __version__, context_version, int(is_simulated), utcnow()),
        )
        for ev, status, actual in checked:
            conn.execute(
                "INSERT INTO evidence (id, analysis_id, finding_id, repo_id, file_path, commit_sha, line_start, line_end,"
                " excerpt, excerpt_sha256, note, reference_check, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id(), aid, finding_id, None, ev.file, ev.commit, ev.line_start, ev.line_end,
                 actual if actual is not None else ev.excerpt,
                 sha256_bytes(actual.encode()) if actual else None, ev.note, status, utcnow()),
            )
        conn.execute(
            "UPDATE finding SET processing_state = ?, updated_at = ? WHERE id = ?",
            (ProcessingState.PROPOSAL_READY.value, utcnow(), finding_id),
        )
    return latest_analysis(conn, finding_id)  # type: ignore[return-value]


def latest_analysis(conn: sqlite3.Connection, finding_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM analysis WHERE finding_id = ? ORDER BY seq DESC LIMIT 1", (finding_id,)).fetchone()
    if row is None:
        return None
    a = dict(row)
    a["payload"] = loads(a.pop("payload_json"), {})
    a["validation"] = loads(a.pop("validation_json"), {})
    a["evidence"] = [dict(e) for e in conn.execute(
        "SELECT * FROM evidence WHERE analysis_id = ? ORDER BY line_start", (a["id"],))]
    return a


def excerpt_for_finding(conn: sqlite3.Connection, finding: sqlite3.Row) -> CodeExcerpt | None:
    """Extrait du code autour de la ligne du finding, lu dans le dépôt autorisé."""
    if not finding["normalized_path"]:
        return None
    repo, rel = _repo_for(conn, finding, finding["normalized_path"], None)
    if repo is None:
        return None
    path = safe_repo_file(repo, rel)
    if path is None:
        return None
    lines = read_lines(path)
    line = finding["line_number"]
    if line is None:
        lo, hi, highlight = 1, min(len(lines), 2 * EXCERPT_CONTEXT), set()
    else:
        lo, hi, highlight = max(1, line - EXCERPT_CONTEXT), min(len(lines), line + EXCERPT_CONTEXT), {line}
    return CodeExcerpt(repo["name"], rel, lo, [(i, lines[i - 1]) for i in range(lo, hi + 1)], highlight)

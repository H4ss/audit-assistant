"""Pipeline d'import d'un outil : lire → mapper → rapprocher (intra-outil) → enregistrer.

Règles d'identité (section 7) :
  * identifiant interne = uuid, jamais un numéro de ligne ;
  * identifiant source contextualisé par outil | application | version ;
  * sans identifiant source : empreinte documentée
    `fp:` + sha256(outil, règle, chemin normalisé, ligne, fonction, catégorie)[:20] ;
  * même identifiant reçu deux fois dans un import : doublon de transport si
    contenu identique, sinon collision exposée (jamais fusionnée) ;
  * réimport identique : provenance actualisée, aucune nouvelle occurrence.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paladin import store
from paladin.classify import classify
from paladin.config import Settings, is_inside
from paladin.contracts import (
    Completeness,
    MatchState,
    NormalizedFinding,
    ReviewState,
    SourceIdKind,
    SourceRole,
)
from paladin.importers import fortify as fty
from paladin.importers import profiles
from paladin.importers.mapping import apply_mapping, propose_mapping, signature, validate_mapping
from paladin.importers.markdown import read_markdown
from paladin.importers.records import RawRecord, SourceRead
from paladin.importers.sarif import SARIF_MAPPING, read_sarif
from paladin.importers.tabular import read_csv, read_excel
from paladin.util import dumps, fingerprint, new_id, sha256_file, utcnow

# Champs comparés entre inventaire et détails pour signaler les divergences.
COMPARED_FIELDS = ("category", "primary_rule_id", "full_filename", "line_number", "criticality_raw", "cwe_ids",
                   "application_name", "version_name")
FINDING_FIELDS = ("application_name", "version_name", "version_source_id", "category", "fortify_category",
                  "primary_rule_id", "analyzer_type", "primary_location", "line_number", "full_filename",
                  "function_name", "criticality_raw", "cwe_ids", "source_comments")

ANALYST_HEADERS = {"analysis result", "analysis result comment"}


class ImportBlocked(RuntimeError):
    def __init__(self, message: str, action: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.action = action
        self.details = details or {}


@dataclass
class SourceReport:
    role: str
    kind: str
    path: str
    records: int = 0
    completeness: str = Completeness.UNKNOWN.value
    unrecognized: list[dict[str, str]] = field(default_factory=list)
    ignored: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    profile: str = ""
    import_run_id: str = ""


@dataclass
class ImportReport:
    tool: str
    sources: list[SourceReport] = field(default_factory=list)
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    reexam_required: int = 0
    transport_duplicates: int = 0
    collisions: int = 0
    matched: int = 0
    inventory_only: int = 0
    details_only: int = 0
    ambiguous: int = 0
    divergent: int = 0
    completeness: str = Completeness.UNKNOWN.value
    error: dict[str, str] | None = None
    blocked: dict[str, Any] | None = None

    def summary(self) -> str:
        parts = [f"{self.tool} : {self.new} nouveaux, {self.updated} modifiés, {self.unchanged} inchangés"]
        if self.matched or self.inventory_only or self.details_only:
            parts.append(
                f"appariés {self.matched}, Excel sans détail MD {self.inventory_only}, "
                f"MD sans ligne Excel {self.details_only}, ambigus {self.ambiguous}, divergents {self.divergent}"
            )
        if self.transport_duplicates:
            parts.append(f"doublons de transport {self.transport_duplicates}")
        if self.collisions:
            parts.append(f"collisions {self.collisions} (à résoudre)")
        if self.reexam_required:
            parts.append(f"réexamen requis {self.reexam_required}")
        parts.append(f"complétude : {self.completeness}")
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Lecture des sources déclarées
# ---------------------------------------------------------------------------


@dataclass
class _Loaded:
    spec: dict[str, Any]
    read: SourceRead
    findings: list[NormalizedFinding]
    report: SourceReport
    source_file_id: str | None
    import_run_id: str


def _campaign_inputs(settings: Settings, campaign_id: str) -> Path:
    return settings.campaign_dir(campaign_id) / "inputs"


def resolve_source_path(settings: Settings, campaign: dict[str, Any], spec: dict[str, Any]) -> Path:
    inputs = _campaign_inputs(settings, campaign["id"])
    raw = spec["path"]
    if raw == "@target":
        raw = campaign["config"]["target_workbook"]
    p = Path(raw)
    return p if p.is_absolute() else inputs / p


def _register_file(
    conn: sqlite3.Connection, settings: Settings, campaign_id: str, tool_id: str, role: str, path: Path
) -> str:
    """Enregistre le fichier source ; copie l'original dans l'espace de campagne si besoin."""
    digest = sha256_file(path)
    stored = path
    campaign_dir = settings.campaign_dir(campaign_id)
    if not is_inside(path, campaign_dir):
        dest = campaign_dir / "inputs" / "originals" / f"{digest[:12]}-{path.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(path, dest)
        stored = dest
    sid = new_id()
    conn.execute(
        "INSERT INTO source_file (id, campaign_id, tool_id, role, original_path, stored_path, sha256, size_bytes,"
        " received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, campaign_id, tool_id, role, str(path), str(stored), digest, path.stat().st_size, utcnow()),
    )
    return sid


def _fortify_mapping(field_map: dict[str, str]) -> dict[str, Any]:
    transforms = {"line_number": "int", "cwe_ids": "cwe_list"}
    return {
        "fields": {k: {"source": v, "transform": transforms.get(k, "text")} for k, v in field_map.items()},
        "constants": {},
        "comments_from": [],
    }


def _resolve_mapping(
    conn: sqlite3.Connection, campaign_id: str, tool: str, spec: dict[str, Any], read: SourceRead
) -> tuple[dict[str, Any], str]:
    """Mapping à appliquer : déclaré, profil validé de même signature, sinon blocage avec proposition."""
    if read.kind == "sarif":
        return SARIF_MAPPING, "sarif-standard"
    if spec.get("mapping"):
        validate_mapping(spec["mapping"], read.field_names)
        return spec["mapping"], "déclaré dans la configuration de campagne"
    sig = signature(read.field_names)
    prof = profiles.find_validated(conn, campaign_id, sig)
    if prof:
        validate_mapping(prof["mapping"], read.field_names)
        return prof["mapping"], f"profil validé {prof['name']} v{prof['version']}"
    proposal = propose_mapping(read.field_names, read.records)
    saved = profiles.save_proposal(
        conn, campaign_id, f"{tool}-{read.kind}", read.kind, sig, proposal.as_mapping(), "heuristic"
    )
    raise ImportBlocked(
        f"Aucun profil validé pour cette source {read.kind} de {tool}.",
        f"Vérifier puis valider la proposition : python -m paladin profile show {saved['id']}",
        {
            "profile_id": saved["id"],
            "proposal": proposal.as_mapping(),
            "unmapped": proposal.unmapped,
            "missing": proposal.missing,
            "basis": {g.key: g.basis for g in proposal.guesses},
        },
    )


def _read_source(path: Path, spec: dict[str, Any]) -> SourceRead:
    kind = spec["kind"]
    if kind == "excel":
        return read_excel(path, spec.get("sheet"))
    if kind == "csv":
        return read_csv(path)
    if kind == "md":
        return read_markdown(path, spec["profile"], spec.get("options") or {})
    if kind == "sarif":
        return read_sarif(path)
    raise ImportBlocked(f"Type de source inconnu : {kind}", "Types pris en charge : excel, csv, md, sarif, fortify_fixture.")


def _start_run(conn, campaign_id, tool_id, kind, source_file_id, profile, scope) -> str:
    rid = new_id()
    conn.execute(
        "INSERT INTO import_run (id, campaign_id, tool_id, source_kind, source_file_id, profile, scope_json, status,"
        " started_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)",
        (rid, campaign_id, tool_id, kind, source_file_id, profile, dumps(scope), utcnow()),
    )
    return rid


def _finish_run(conn, run_id: str, read: SourceRead, imported: int, status: str, report: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE import_run SET expected_total = ?, imported_total = ?, completeness = ?, status = ?, report_json = ?,"
        " finished_at = ? WHERE id = ?",
        (read.expected_total, imported, read.completeness.value, status, dumps(report), utcnow(), run_id),
    )


# ---------------------------------------------------------------------------
# Normalisation des chemins et dépôts
# ---------------------------------------------------------------------------


def resolve_repo(path: str | None, repos: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    """(repo_id, nom du dépôt, chemin relatif au dépôt). La casse est conservée."""
    if not path:
        return None, None, None
    p = path.replace("\\", "/")
    for repo in repos:
        for root in repo["scanner_roots"]:
            r = root.replace("\\", "/")
            if p.startswith(r):
                return repo["id"], repo["name"], p[len(r):].lstrip("/")
    q = p
    while q.startswith("./"):
        q = q[2:]
    q = q.lstrip("/")
    for repo in repos:
        if q.startswith(repo["name"] + "/"):
            return repo["id"], repo["name"], q[len(repo["name"]) + 1 :]
    return None, None, None


def normalized_path(path: str | None, repos: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    repo_id, name, rel = resolve_repo(path, repos)
    if name:
        return f"{name}/{rel}", repo_id
    if not path:
        return None, None
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/"), None


# ---------------------------------------------------------------------------
# Rapprochement intra-outil (inventaire Excel + détails MD)
# ---------------------------------------------------------------------------


@dataclass
class _Merged:
    primary: NormalizedFinding  # valeurs retenues
    members: list[tuple[str, NormalizedFinding, int]]  # (rôle, finding, index dans sa source)
    match_state: MatchState
    match_detail: str
    divergences: list[dict[str, Any]] = field(default_factory=list)


def _comparable(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(value)
    if isinstance(value, str):
        return value.strip().replace("\\", "/")
    return value


def _merge(inv: NormalizedFinding, det: NormalizedFinding, priority: dict[str, str]) -> tuple[NormalizedFinding, list[dict[str, Any]]]:
    data = inv.model_dump()
    d = det.model_dump()
    divergences = []
    for key, dval in d.items():
        if key in ("tool", "locator", "raw", "extra"):
            continue
        ival = data.get(key)
        if ival in (None, [], "") and dval not in (None, [], ""):
            data[key] = dval
        elif key in COMPARED_FIELDS and dval not in (None, [], "") and _comparable(ival) != _comparable(dval):
            chosen = priority.get(key)
            divergences.append({
                "field": key, "inventory": ival, "details": dval,
                "selected": chosen, "reason": f"priorité validée : {chosen}" if chosen else "à résoudre",
            })
            if chosen == "details":
                data[key] = dval
    data["extra"] = {**d.get("extra", {}), **inv.extra}
    data["raw"] = {"inventory": inv.raw, "details": det.raw}
    return NormalizedFinding.model_validate(data), divergences


def reconcile(
    inventory: list[NormalizedFinding], details: list[NormalizedFinding], priority: dict[str, str]
) -> list[_Merged]:
    out: list[_Merged] = []
    det_by_id: dict[str, list[int]] = {}
    for i, f in enumerate(details):
        if f.source_id:
            det_by_id.setdefault(f.source_id, []).append(i)
    used_details: set[int] = set()

    def secondary(f: NormalizedFinding) -> tuple:
        return (f.primary_rule_id, _comparable(f.full_filename), f.line_number, f.application_name, f.version_name)

    det_by_key: dict[tuple, list[int]] = {}
    for i, f in enumerate(details):
        if f.full_filename and f.line_number is not None:
            det_by_key.setdefault(secondary(f), []).append(i)

    for ii, inv in enumerate(inventory):
        cands = det_by_id.get(inv.source_id or "", [])
        detail = "identifiant commun"
        if not cands and inv.full_filename and inv.line_number is not None:
            cands = [i for i in det_by_key.get(secondary(inv), []) if not details[i].source_id or not inv.source_id]
            detail = "règle + fichier + ligne + application/version"
        cands = [c for c in cands if c not in used_details]
        if len(cands) == 1:
            di = cands[0]
            used_details.add(di)
            merged, divs = _merge(inv, details[di], priority)
            out.append(_Merged(merged, [("inventory", inv, ii), ("details", details[di], di)], MatchState.MATCHED, detail, divs))
        elif len(cands) > 1:
            out.append(_Merged(inv, [("inventory", inv, ii)], MatchState.AMBIGUOUS,
                               f"{len(cands)} détails candidats : confirmation requise"))
        else:
            out.append(_Merged(inv, [("inventory", inv, ii)], MatchState.INVENTORY_ONLY, "aucun détail MD"))
    for di, det in enumerate(details):
        if di in used_details:
            continue
        ambiguous_with = any(m.match_state == MatchState.AMBIGUOUS and det_by_id.get(m.primary.source_id or "") and
                             di in det_by_id[m.primary.source_id or ""] for m in out)
        state = MatchState.AMBIGUOUS if ambiguous_with else MatchState.DETAILS_ONLY
        out.append(_Merged(det, [("details", det, di)], state,
                           "candidat ambigu" if ambiguous_with else "MD sans ligne Excel : proposition de nouvelle ligne"))
    return out


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------


def _content_fingerprint(merged: _Merged) -> str:
    """Empreinte des valeurs retenues, des sections de détail et des divergences.

    Les données brutes et les champs non mappés (dont les colonnes analyste et
    comparatives que Paladin écrit lui-même) sont exclus : un export ne doit pas
    provoquer de « modification de source » au réimport.
    """
    f = merged.primary
    content = f.model_dump(exclude={"locator", "raw", "extra"})
    content["sections"] = f.extra.get("_sections")
    content["divergences"] = merged.divergences
    return fingerprint(content)


def _identity(f: NormalizedFinding, norm_path: str | None) -> tuple[str, str]:
    if f.source_id:
        return f.source_id, SourceIdKind.NATIVE.value
    fp = fingerprint(f.tool, f.primary_rule_id, norm_path, f.line_number, f.function_name, f.category)[:20]
    return f"fp:{fp}", SourceIdKind.FINGERPRINT.value


def _scope_key(tool: str, f: NormalizedFinding, scope: dict[str, Any]) -> str:
    app = scope.get("application_name") or f.application_name or "-"
    version = scope.get("version_id") or scope.get("version_name") or f.version_name or "-"
    return f"{tool}|{app}|{version}"


def _details_json(f: NormalizedFinding, merged: _Merged | None) -> dict[str, Any]:
    pre = {}
    raws = [f.raw.get("inventory", f.raw)] if isinstance(f.raw, dict) else []
    for raw in raws:
        for k, v in (raw or {}).items():
            if str(k).strip().lower() in ANALYST_HEADERS and v not in (None, ""):
                pre[k] = v
    return {
        "description": f.description,
        "recommendation": f.recommendation,
        "trace": f.trace,
        "trace_available": f.trace is not None,
        "extra": f.extra,
        "preexisting_analyst_values": pre,
        "match": None if merged is None else {"state": merged.match_state.value, "detail": merged.match_detail},
    }


def _insert_source_record(conn, run_id, source_file_id, finding_id, role, f: NormalizedFinding, merged) -> str:
    rid = new_id()
    conn.execute(
        "INSERT INTO source_record (id, import_run_id, source_file_id, finding_id, role, locator, record_hash,"
        " payload_json, match_state, match_detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, run_id, source_file_id, finding_id, role, f.locator, fingerprint(f.raw), dumps(f.model_dump()),
         None if merged is None else merged.match_state.value, None if merged is None else merged.match_detail, utcnow()),
    )
    return rid


def _insert_field_values(conn, finding_id: str, record_id: str, f: NormalizedFinding, selected_fields: set[str], reason: str):
    now = utcnow()
    for key in FINDING_FIELDS:
        val = getattr(f, key)
        if val in (None, [], ""):
            continue
        conn.execute(
            "INSERT INTO field_value (id, finding_id, field, value_json, source_record_id, selected, selection_reason,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id(), finding_id, key, dumps(val), record_id, int(key in selected_fields), reason, now),
        )


def _upsert(
    conn: sqlite3.Connection,
    campaign_id: str,
    tool: dict[str, Any],
    merged: _Merged,
    scope: dict[str, Any],
    repos: list[dict[str, Any]],
    runs: dict[str, tuple[str, str | None]],
    seen: dict[tuple[str, str], str],
    report: ImportReport,
    commit_sha: str | None,
) -> None:
    f = merged.primary
    norm, repo_id = normalized_path(f.full_filename, repos)
    source_id, id_kind = _identity(f, norm)
    scope_key = _scope_key(tool["label"], f, scope)
    content_fp = _content_fingerprint(merged)
    primary_role = merged.members[0][0]
    run_id, source_file_id = runs[primary_role]

    key = (scope_key, source_id)
    if key in seen:
        existing_fp = seen[key]
        if existing_fp == content_fp:
            report.transport_duplicates += 1
            return
        # Même identifiant, contenu différent : collision exposée, pas de fusion.
        fid = conn.execute(
            "SELECT id FROM finding WHERE campaign_id = ? AND tool_id = ? AND scope_key = ? AND source_id = ?",
            (campaign_id, tool["id"], scope_key, source_id),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO fingerprint_collision (id, campaign_id, finding_id, import_run_id, locator, payload_json,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
            (new_id(), campaign_id, fid, run_id, f.locator, dumps(f.model_dump()), utcnow()),
        )
        report.collisions += 1
        return
    seen[key] = content_fp

    cls = classify(f.cwe_ids, f.category, f.primary_rule_id, f.description)
    now = utcnow()
    row = conn.execute(
        "SELECT id, fingerprint, review_state, revision FROM finding WHERE campaign_id = ? AND tool_id = ?"
        " AND scope_key = ? AND source_id = ?",
        (campaign_id, tool["id"], scope_key, source_id),
    ).fetchone()
    divergent = [d["field"] for d in merged.divergences if d["selected"] is None]
    values = {
        "application_name": f.application_name or scope.get("application_name"),
        "version_name": f.version_name or scope.get("version_name"),
        "version_source_id": f.version_source_id or (str(scope["version_id"]) if scope.get("version_id") else None),
        "category": f.category, "fortify_category": f.fortify_category, "primary_rule_id": f.primary_rule_id,
        "analyzer_type": f.analyzer_type, "primary_location": f.primary_location, "line_number": f.line_number,
        "full_filename": f.full_filename, "normalized_path": norm, "function_name": f.function_name,
        "criticality_raw": f.criticality_raw, "cwe_ids_json": dumps(f.cwe_ids), "source_comments": f.source_comments,
        "details_json": dumps(_details_json(f, merged)), "repo_id": repo_id, "commit_sha": commit_sha,
        "family": cls.family, "family_basis": cls.basis, "analysis_route": cls.route,
        "divergent_fields_json": dumps(divergent),
    }
    if row is None:
        fid = new_id()
        cols = ["id", "campaign_id", "tool_id", "scope_key", "source_id", "source_id_kind", "fingerprint",
                "first_import_id", "last_import_id", "created_at", "updated_at", *values]
        params = [fid, campaign_id, tool["id"], scope_key, source_id, id_kind, content_fp, run_id, run_id, now, now,
                  *values.values()]
        conn.execute(f"INSERT INTO finding ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", params)
        report.new += 1
        changed = True
    else:
        fid = row["id"]
        changed = row["fingerprint"] != content_fp
        if changed:
            sets = ", ".join(f"{k} = ?" for k in values)
            review_state = row["review_state"]
            if review_state == ReviewState.VALIDATED.value:
                review_state = ReviewState.REEXAM_REQUIRED.value
                report.reexam_required += 1
            conn.execute(
                f"UPDATE finding SET {sets}, fingerprint = ?, review_state = ?, revision = revision + 1,"
                " last_import_id = ?, updated_at = ? WHERE id = ?",
                (*values.values(), content_fp, review_state, run_id, now, fid),
            )
            report.updated += 1
        else:
            conn.execute("UPDATE finding SET last_import_id = ?, updated_at = ? WHERE id = ?", (run_id, now, fid))
            report.unchanged += 1

    for role, member, _ in merged.members:
        m_run, m_file = runs[role]
        rec_id = _insert_source_record(conn, m_run, m_file, fid, role, member, merged)
        if changed:
            if len(merged.members) == 1:
                selected = set(FINDING_FIELDS)
                reason = "source unique"
            else:
                div_fields = {d["field"] for d in merged.divergences}
                if role == "inventory":
                    selected = {k for k in FINDING_FIELDS if k not in div_fields}
                else:
                    selected = {k for k in FINDING_FIELDS if getattr(merged.members[0][1], k) in (None, [], "")}
                    selected |= {d["field"] for d in merged.divergences if d["selected"] == "details"}
                reason = f"rapprochement : {role}"
            _insert_field_values(conn, fid, rec_id, member, selected, reason)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def _tool_spec(campaign: dict[str, Any], label: str) -> dict[str, Any]:
    for t in campaign["config"].get("tools", []):
        if t["label"] == label:
            return t
    raise ImportBlocked(f"Outil {label!r} absent de la configuration de campagne.", "Ajouter l'outil à la campagne.")


@dataclass
class _Prepared:
    spec: dict[str, Any]
    read: SourceRead
    findings: list[NormalizedFinding]
    report: SourceReport
    path: Path | None


def import_tool(
    settings: Settings,
    conn: sqlite3.Connection,
    campaign_id: str,
    tool_label: str,
    *,
    fortify_source: fty.FortifySource | None = None,
    resume: bool = False,
) -> ImportReport:
    """Importe toutes les sources déclarées d'un outil.

    Phase 1 (sans verrou d'écriture) : lecture, collecte, résolution du mapping.
    Une proposition de profil est enregistrée puis l'import est bloqué.
    Phase 2 (une transaction) : provenance, rapprochement, enregistrement.
    """
    campaign = store.get_campaign(conn, campaign_id)
    spec = _tool_spec(campaign, tool_label)
    tool = store.get_tool(conn, campaign_id, tool_label)
    repos = store.list_repos(conn, campaign_id)
    report = ImportReport(tool=tool_label)

    prepared: list[_Prepared] = []
    try:
        for src in spec["sources"]:
            if src["kind"] in ("fortify_fixture", "fortify_api"):
                prepared.append(_prepare_fortify(settings, campaign, tool, spec, src, fortify_source, resume, report))
                continue
            path = resolve_source_path(settings, campaign, src)
            if not path.exists():
                raise ImportBlocked(f"Fichier source introuvable : {path}", "Vérifier le chemin dans la configuration.")
            read = _read_source(path, src)
            mapping, basis = _resolve_mapping(conn, campaign_id, tool_label, src, read)
            findings = [apply_mapping(r, mapping, tool_label) for r in read.records]
            sr = SourceReport(src["role"], read.kind, str(path), len(findings), read.completeness.value,
                              [vars(u) for u in read.unrecognized], [vars(u) for u in read.ignored], read.notes, basis)
            prepared.append(_Prepared(src, read, findings, sr, path))
    except (ImportBlocked, fty.VersionSelectionError) as exc:
        report.blocked = {"message": str(exc), "action": exc.action, **getattr(exc, "details", {})}
        return report

    with store.transaction(conn):
        loaded: dict[str, _Loaded] = {}
        for pr in prepared:
            role = pr.spec["role"]
            sf_id = _register_file(conn, settings, campaign_id, tool["id"], role, pr.path) if pr.path else None
            run_id = _start_run(conn, campaign_id, tool["id"], pr.spec["kind"], sf_id, pr.report.profile,
                                {**pr.read.scope, **(pr.spec.get("scope") or {})})
            pr.report.import_run_id = run_id
            report.sources.append(pr.report)
            loaded[role] = _Loaded(pr.spec, pr.read, pr.findings, pr.report, sf_id, run_id)
        _ingest(conn, campaign_id, tool, spec, loaded, repos, report)
    return report


def _ingest(conn, campaign_id, tool, spec, loaded: dict[str, _Loaded], repos, report: ImportReport) -> None:
    priority = spec.get("field_priority", {})
    scope: dict[str, Any] = {}
    for lo in loaded.values():
        scope.update({k: v for k, v in lo.read.scope.items() if k in ("application_name", "version_name",
                                                                         "version_id", "application_id")})
    commit_sha = (spec.get("fortify") or {}).get("scanned_commit") or spec.get("scanned_commit")
    runs = {role: (lo.import_run_id, lo.source_file_id) for role, lo in loaded.items()}

    if SourceRole.INVENTORY.value in loaded and SourceRole.DETAILS.value in loaded:
        merged_list = reconcile(loaded["inventory"].findings, loaded["details"].findings, priority)
        for m in merged_list:
            report.matched += m.match_state == MatchState.MATCHED
            report.inventory_only += m.match_state == MatchState.INVENTORY_ONLY
            report.details_only += m.match_state == MatchState.DETAILS_ONLY
            report.ambiguous += m.match_state == MatchState.AMBIGUOUS
            report.divergent += bool(m.divergences)
    else:
        merged_list = []
        for role, lo in loaded.items():
            merged_list += [_Merged(f, [(role, f, i)], MatchState.MATCHED, "source unique") for i, f in enumerate(lo.findings)]

    seen: dict[tuple[str, str], str] = {}
    for m in merged_list:
        _upsert(conn, campaign_id, tool, m, scope, repos, runs, seen, report, commit_sha)

    completeness = [Completeness(lo.read.completeness) for lo in loaded.values()]
    if all(c == Completeness.COMPLETE for c in completeness):
        report.completeness = Completeness.COMPLETE.value
    elif any(c == Completeness.PARTIAL for c in completeness):
        report.completeness = Completeness.PARTIAL.value
    else:
        report.completeness = Completeness.UNKNOWN.value
    for lo in loaded.values():
        status = "done" if lo.read.completeness == Completeness.COMPLETE else "partial"
        imported = sum(1 for m in merged_list for role, _, _ in m.members if role == lo.spec["role"])
        _finish_run(conn, lo.import_run_id, lo.read, imported, status, {
            "unrecognized": [vars(u) for u in lo.read.unrecognized],
            "ignored": [vars(u) for u in lo.read.ignored],
            "notes": lo.read.notes,
            "tool_summary": report.summary(),
        })


def _prepare_fortify(settings, campaign, tool, spec, src, source, resume, report) -> _Prepared:
    cfg = spec.get("fortify") or {}
    if source is None:
        if src["kind"] != "fortify_fixture":
            raise ImportBlocked(
                "Connecteur Fortify réel non disponible : aucun endpoint n'a été vérifié sur l'instance.",
                "Exécuter le diagnostic sur le PC de travail (palier P4 / étape B).",
            )
        source = fty.FixtureFortifySource(resolve_source_path(settings, campaign, src))
    choice = fty.select_version(source, cfg["application_name"], cfg.get("version_name", "release"), cfg.get("version_id"))
    captures = settings.campaign_dir(campaign["id"]) / "captures"
    resume_manifest = None
    if resume:
        latest = sorted(captures.glob("fortify-*/manifest.json"))
        if latest:
            m = json.loads(latest[-1].read_text(encoding="utf-8"))
            if m.get("completeness") != "complete":
                resume_manifest = m
    capture_dir = captures / f"fortify-{utcnow()[:19].replace(':', '').replace('-', '')}-{new_id()[:6]}"
    result = fty.collect(source, choice, capture_dir, page_size=int(cfg.get("page_size", 8)),
                         filters=cfg.get("filters"), resume_manifest=resume_manifest)
    read = result.read
    mapping = _fortify_mapping(cfg["field_map"])
    validate_mapping(mapping)
    findings = []
    for rec in read.records:
        nf = apply_mapping(RawRecord(fields={k: v for k, v in rec.fields.items() if k != "_details"},
                                     locator=rec.locator), mapping, tool["label"])
        extra = fty.details_to_fields(rec.fields)
        nf = nf.model_copy(update={k: v for k, v in extra.items() if v is not None and k != "source_comments"})
        if extra["source_comments"]:
            nf = nf.model_copy(update={"source_comments": "\n".join(filter(None, [nf.source_comments, extra["source_comments"]]))})
        nf = nf.model_copy(update={"application_name": choice.application_name, "version_name": choice.version_name,
                                   "version_source_id": str(choice.version_id)})
        findings.append(nf)
    sr = SourceReport(src["role"], "fortify", str(result.manifest_path), len(findings), read.completeness.value,
                      [], [], read.notes, "field_map déclaré (à vérifier sur l'instance réelle)")
    if result.error:
        report.error = {"message": str(result.error), "action": result.error.action}
    return _Prepared(src, read, findings, sr, None)

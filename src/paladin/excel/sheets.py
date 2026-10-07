"""Schéma d'onglet pour un outil sans onglet (section 21.4).

Proposition déterministe à partir des findings importés : seules les colonnes qui
ont des données sont proposées, les champs spécifiques détectés sont ajoutés, les
colonnes analyste et comparatives sont verrouillées dans leur sens métier.
L'utilisateur renomme, retire ou réordonne les colonnes non obligatoires, puis
valide une fois. Le schéma est versionné : une évolution ajoute des colonnes,
n'en retire jamais. Aucun code généré n'est exécuté.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from pydantic import ValidationError

from paladin import store
from paladin.contracts import (
    DEFAULT_COLUMNS,
    FORTIFY_ONLY_KEYS,
    SchemaStatus,
    SheetColumnProposal,
    SheetSchemaProposal,
    criticality_in_header,
    format_cwe_ids,
    found_in_header,
)
from paladin.util import dumps, loads, new_id, utcnow

ROLE_KEY, ROLE_META, ROLE_ANALYST, ROLE_COMPARATIVE = "key", "metadata", "analyst", "comparative"
SAMPLE = 200
_FORBIDDEN_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


class SheetSchemaError(ValueError):
    pass


def sheet_name_for(label: str, existing: list[str]) -> str:
    base = _FORBIDDEN_SHEET_CHARS.sub("-", label).strip("'")[:31] or "Outil"
    name, n = base, 2
    lowered = {s.lower() for s in existing}
    while name.lower() in lowered or name.lower() == "history":
        suffix = f" ({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    return name


def _findings(conn: sqlite3.Connection, tool_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM finding WHERE tool_id = ? ORDER BY created_at LIMIT ?", (tool_id, SAMPLE)
    ).fetchall()


def finding_value(f: sqlite3.Row | dict[str, Any], key: str) -> Any:
    """Valeur d'une colonne de métadonnées pour un finding (clé interne ou `extra:<champ>`)."""
    if key == "source_id":
        return f["source_id"]
    if key == "instance_id":
        return f["source_id"] if f["source_id_kind"] == "native" else None
    if key == "cwe_ids":
        ids = loads(f["cwe_ids_json"], [])
        return format_cwe_ids(ids) if ids else None
    if key.startswith("extra:"):
        value = (loads(f["details_json"], {}).get("extra") or {}).get(key[6:])
        return None if value in (None, "") else (value if isinstance(value, int | float) else str(value))
    if key in f.keys():  # noqa: SIM118 — sqlite3.Row : `in` porte sur les valeurs
        return f[key]
    return None


def propose(
    conn: sqlite3.Connection, campaign_id: str, tool_label: str, existing_sheets: list[str]
) -> SheetSchemaProposal:
    tool = store.get_tool(conn, campaign_id, tool_label)
    rows = _findings(conn, tool["id"])
    if not rows:
        raise SheetSchemaError(f"Aucun finding importé pour {tool_label} : importer avant de proposer un onglet.")
    others = [t["label"] for t in store.list_tools(conn, campaign_id) if t["label"] != tool_label]
    is_fortify = tool["kind"] == "fortify"

    def availability(key: str) -> tuple[str, Any]:
        values = [finding_value(r, key) for r in rows]
        present = [v for v in values if v not in (None, "")]
        if not present:
            return "absent", None
        return ("present" if len(present) == len(values) else "partial"), present[0]

    cols: list[SheetColumnProposal] = [
        SheetColumnProposal(
            header="Finding ID",
            key="source_id",
            source_field="identifiant source",
            example=str(rows[0]["source_id"]),
            required=True,
            locked=True,
        )
    ]
    for c in DEFAULT_COLUMNS:
        if c.analyst or c.key == "instance_id" or (c.key in FORTIFY_ONLY_KEYS and not is_fortify):
            continue
        avail, example = availability(c.key)
        if avail == "absent":
            continue
        cols.append(
            SheetColumnProposal(
                header=c.header,
                key=c.key,
                type="integer" if c.key == "line_number" else "text",
                source_field=c.key,
                example=None if example is None else str(example)[:80],
                availability=avail,
            )
        )
    extras: dict[str, int] = {}
    for r in rows:
        for name, value in (loads(r["details_json"], {}).get("extra") or {}).items():
            if not name.startswith("_") and value not in (None, ""):
                extras[name] = extras.get(name, 0) + 1
    uncovered = []
    for name, count in sorted(extras.items(), key=lambda kv: -kv[1]):
        key = "extra_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or any(c.header.lower() == name.lower() for c in cols):
            uncovered.append(name)
            continue
        cols.append(
            SheetColumnProposal(
                header=name[:255],
                key=key,
                source_field=f"extra:{name}",
                availability="present" if count == len(rows) else "partial",
                transformation="valeur brute de la source",
            )
        )
    for c in DEFAULT_COLUMNS:
        if c.analyst:
            cols.append(
                SheetColumnProposal(
                    header=c.header, key=c.key, required=True, locked=True, source_field="décision validée"
                )
            )
    for other in others:
        slug = re.sub(r"[^a-z0-9]+", "_", other.lower()).strip("_") or "outil"
        cols.append(
            SheetColumnProposal(
                header=found_in_header(other),
                key=f"found_in_{slug}",
                required=True,
                locked=True,
                source_field=f"liens confirmés avec {other}",
            )
        )
        cols.append(
            SheetColumnProposal(
                header=criticality_in_header(other),
                key=f"criticality_in_{slug}",
                required=True,
                locked=True,
                source_field=f"criticité originale dans {other}",
            )
        )
    return SheetSchemaProposal(
        tool=tool_label,
        sheet_name=sheet_name_for(tool_label, existing_sheets),
        columns=cols,
        uncovered_fields=uncovered,
        notes=f"{len(rows)} finding(s) examiné(s) ; colonnes sans donnée non proposées.",
    )


def preview(
    conn: sqlite3.Connection, campaign_id: str, proposal: SheetSchemaProposal, limit: int = 5
) -> list[list[Any]]:
    tool = store.get_tool(conn, campaign_id, proposal.tool)
    out = []
    for r in _findings(conn, tool["id"])[:limit]:
        row = []
        for c in proposal.columns:
            src = c.source_field or ""
            if (
                c.key == "source_id"
                or c.key.startswith("extra_")
                or c.key in {d.key for d in DEFAULT_COLUMNS if not d.analyst}
            ):
                row.append(finding_value(r, src if src.startswith("extra:") else c.key))
            else:
                row.append("…")
        out.append(row)
    return out


def validate(
    proposal: SheetSchemaProposal, existing_sheets: list[str], previous: SheetSchemaProposal | None = None
) -> None:
    headers = [c.header.strip() for c in proposal.columns]
    if any(not h for h in headers):
        raise SheetSchemaError("Un en-tête est vide.")
    dupes = {h for h in headers if headers.count(h) > 1}
    if dupes:
        raise SheetSchemaError(f"En-têtes en double : {sorted(dupes)}.")
    required = {"source_id", "analyst_result", "analyst_comment"}
    if not required <= {c.key for c in proposal.columns}:
        raise SheetSchemaError("La clé et les deux colonnes analyste sont obligatoires.")
    if previous is None and proposal.sheet_name.lower() in {s.lower() for s in existing_sheets}:
        raise SheetSchemaError(f"Un onglet « {proposal.sheet_name} » existe déjà dans le classeur.")
    if previous is not None:
        removed = {c.key for c in previous.columns} - {c.key for c in proposal.columns}
        if removed:
            raise SheetSchemaError(f"Une évolution ne retire jamais de colonne existante : {sorted(removed)}.")


def apply_edits(proposal: SheetSchemaProposal, edits: dict[str, Any]) -> SheetSchemaProposal:
    """Renommage, retrait et ordre des colonnes non verrouillées. `edits` vient du formulaire."""
    cols = []
    for i, c in enumerate(proposal.columns):
        if not c.locked and not c.required and edits.get(f"keep_{c.key}") != "1":
            continue
        header = c.header if c.locked else (edits.get(f"header_{c.key}") or c.header).strip()
        order = float(edits.get(f"order_{c.key}") or i) if not c.locked else None
        cols.append((order, i, c.model_copy(update={"header": header})))
    movable = sorted([x for x in cols if x[0] is not None], key=lambda x: (x[0], x[1]))
    locked_tail = [x for x in cols if x[0] is None and x[2].key != "source_id"]
    head = [x for x in cols if x[2].key == "source_id"]
    ordered = [x[2] for x in head + movable + locked_tail]
    try:
        return proposal.model_copy(
            update={"columns": ordered, "sheet_name": (edits.get("sheet_name") or proposal.sheet_name).strip()}
        )
    except ValidationError as exc:
        raise SheetSchemaError(str(exc)) from None


def current_schema(conn: sqlite3.Connection, tool_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM sheet_schema WHERE tool_id = ? AND status = 'validated' ORDER BY version DESC LIMIT 1",
        (tool_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["proposal"] = SheetSchemaProposal.model_validate(loads(d["proposal_json"]))
    return d


def save_validated(conn: sqlite3.Connection, campaign_id: str, proposal: SheetSchemaProposal, proposed_by: str) -> int:
    SheetSchemaProposal.model_validate(proposal.model_dump())  # contraintes de nommage Excel
    tool = store.get_tool(conn, campaign_id, proposal.tool)
    with store.transaction(conn):
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM sheet_schema WHERE tool_id = ?", (tool["id"],)
        ).fetchone()[0]
        conn.execute(
            "UPDATE sheet_schema SET status = ? WHERE tool_id = ? AND status = 'validated'",
            (SchemaStatus.SUPERSEDED.value, tool["id"]),
        )
        columns = [
            {"header": c.header, "key": c.key, "source": c.source_field, "role": _role(c.key)} for c in proposal.columns
        ]
        conn.execute(
            "INSERT INTO sheet_schema (id, campaign_id, tool_id, version, sheet_name, mode, row_key_json, columns_json,"
            " status, proposed_by, proposal_json, validated_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id(),
                campaign_id,
                tool["id"],
                version,
                proposal.sheet_name,
                "generate_rows",
                dumps(["source_id"]),
                dumps(columns),
                SchemaStatus.VALIDATED.value,
                proposed_by,
                dumps(proposal.model_dump()),
                utcnow(),
                utcnow(),
            ),
        )
        conn.execute("UPDATE tool SET sheet_name = ? WHERE id = ?", (proposal.sheet_name, tool["id"]))
    return version


def _role(key: str) -> str:
    if key == "source_id":
        return ROLE_KEY
    if key in ("analyst_result", "analyst_comment"):
        return ROLE_ANALYST
    if key.startswith(("found_in_", "criticality_in_")):
        return ROLE_COMPARATIVE
    return ROLE_META

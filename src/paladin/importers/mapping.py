"""Mapping multi-entrées : champs source -> clés internes.

Un mapping est déclaratif (aucun code exécuté) :

    {
      "fields": {
        "source_id":     {"source": "Finding ID"},
        "line_number":   {"source": "Line", "transform": "int"},
        "full_filename": {"source": "Location", "transform": "location_path"},
        "line_number":   {"source": "Location", "transform": "location_line"},
        "cwe_ids":       {"source": "CWE", "transform": "cwe_list"}
      },
      "constants": {"application_name": "ShopApp"},
      "comments_from": ["Commentaires"]
    }

`propose_mapping` infère une proposition à partir des noms de champs et
d'échantillons de valeurs. Une proposition n'est jamais appliquée sans
validation : elle devient un profil validé, réutilisé pour toute source de même
signature.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from paladin.contracts import NormalizedFinding, parse_cwe_list
from paladin.importers.records import RawRecord
from paladin.util import fingerprint

# Clés internes cibles d'un mapping d'entrée.
MAPPABLE_KEYS: tuple[str, ...] = (
    "source_id",
    "application_name",
    "version_name",
    "category",
    "fortify_category",
    "primary_rule_id",
    "analyzer_type",
    "primary_location",
    "line_number",
    "full_filename",
    "function_name",
    "criticality_raw",
    "cwe_ids",
    "source_comments",
    "description",
    "recommendation",
)

TRANSFORMS = ("text", "int", "cwe_list", "location_path", "location_line", "basename")

# Synonymes normalisés (minuscules, sans accents ni ponctuation).
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "source_id": (
        "id",
        "finding id",
        "issue id",
        "instance id",
        "ref",
        "reference",
        "identifiant",
        "key",
        "issueinstanceid",
        "finding",
        "vuln id",
        "alert id",
        "numero",
    ),
    "application_name": ("application", "application name", "app", "project", "projet", "projectname", "produit"),
    "version_name": ("version", "version name", "branch", "branche", "release", "projectversionname"),
    "category": (
        "category",
        "categorie",
        "issue",
        "issuename",
        "type",
        "vulnerability",
        "vulnerabilite",
        "title",
        "titre",
        "name",
        "nom",
        "check",
        "issue type",
        "finding type",
    ),
    "fortify_category": ("fortify category", "kingdom"),
    "primary_rule_id": (
        "rule",
        "rule id",
        "regle",
        "ruleid",
        "primary rule id",
        "primaryruleguid",
        "check id",
        "test id",
        "query",
    ),
    "analyzer_type": ("analyzer", "analyseur", "engine", "engine type"),
    "primary_location": ("primary location", "primarylocation"),
    "line_number": ("line", "line number", "ligne", "linenumber", "start line", "startline", "lineno"),
    "full_filename": (
        "file",
        "file path",
        "filepath",
        "full filename",
        "fullfilename",
        "path",
        "chemin",
        "fichier",
        "filename",
        "source file",
        "component",
        "composant",
        "location",
        "emplacement",
    ),
    "function_name": ("function", "fonction", "method", "methode", "functionname"),
    "criticality_raw": (
        "severity",
        "criticality",
        "criticite",
        "gravite",
        "priority",
        "priorite",
        "risk",
        "risque",
        "friority",
        "level",
        "niveau",
        "impact",
    ),
    "cwe_ids": ("cwe", "cwe id", "cwes", "cwe ids"),
    "source_comments": ("commentaires", "comments", "comment", "commentaire", "notes", "audit comment"),
    "description": ("description", "details", "detail", "message", "brief", "abstract", "resume"),
    "recommendation": ("recommendation", "recommandation", "remediation", "fix", "correctif", "solution"),
}

_SEVERITY_WORDS = {
    "critical",
    "critique",
    "high",
    "haute",
    "eleve",
    "elevee",
    "medium",
    "moyen",
    "moyenne",
    "low",
    "faible",
    "basse",
    "info",
    "informational",
    "blocker",
    "major",
    "minor",
    "trivial",
    "error",
    "warning",
    "note",
}
_LOCATION_RE = re.compile(r"^(?P<path>[^\s:]+\.[A-Za-z0-9]{1,8}|[^\s:]*[/\\][^\s:]+):(?P<line>\d+)(?::\d+)?$")
_PATH_RE = re.compile(r"^[^\s]+[/\\][^\s]+\.[A-Za-z0-9]{1,8}$")
_CWE_VALUE_RE = re.compile(r"^\s*(cwe[\s\-:_]*(id)?[\s\-:_]*)?\d{1,4}(\s*[;,]\s*(cwe[\s\-:_]*)?\d{1,4})*\s*$", re.I)


def norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return text


_TARGET_EXACT = {"analysis result", "analysis result comment"}


def is_target_column(name: str) -> bool:
    """Colonnes écrites par Paladin (analyste, comparatives) : jamais des champs source."""
    n = norm_name(name)
    return n in _TARGET_EXACT or n.startswith(("found in ", "criticality in "))


def guess_key(name: str) -> str | None:
    """Clé interne dont `name` est un synonyme exact, sinon None."""
    n = norm_name(name)
    return next((key for key, syns in _SYNONYMS.items() if n in syns), None)


def signature(field_names: list[str]) -> str:
    return fingerprint(sorted(norm_name(n) for n in field_names if str(n).strip()))[:24]


@dataclass
class FieldGuess:
    key: str
    source: str
    transform: str
    basis: str  # "nom:exact", "nom:partiel", "valeurs:emplacement"...
    score: int


@dataclass
class MappingProposal:
    fields: dict[str, dict[str, str]]
    guesses: list[FieldGuess]
    unmapped: list[str]
    missing: list[str]  # clés importantes non trouvées
    constants: dict[str, Any] = field(default_factory=dict)
    comments_from: list[str] = field(default_factory=list)

    detected_fields: list[str] = field(default_factory=list)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "constants": self.constants,
            "comments_from": self.comments_from,
            "detected_fields": self.detected_fields,
        }


IMPORTANT_KEYS = ("source_id", "category", "full_filename", "line_number", "criticality_raw")


def _value_kind(values: list[Any]) -> str | None:
    sample = [str(v).strip() for v in values if v not in (None, "") and str(v).strip()]
    if not sample:
        return None

    def share(pred) -> float:
        return sum(1 for v in sample if pred(v)) / len(sample)

    if share(lambda v: bool(_LOCATION_RE.match(v))) >= 0.6:
        return "location"
    if share(lambda v: bool(_CWE_VALUE_RE.match(v)) and "cwe" in v.lower()) >= 0.6:
        return "cwe"
    if share(lambda v: norm_name(v) in _SEVERITY_WORDS) >= 0.8:
        return "severity"
    if share(lambda v: bool(_PATH_RE.match(v))) >= 0.6:
        return "path"
    if share(lambda v: v.isdigit()) >= 0.9:
        return "integer"
    return None


def propose_mapping(field_names: list[str], records: list[RawRecord], sample_size: int = 30) -> MappingProposal:
    """Propose un mapping à partir des noms de champs et des valeurs observées."""
    samples = {name: [r.fields.get(name) for r in records[:sample_size]] for name in field_names}
    candidates: list[FieldGuess] = []
    for name in field_names:
        n = norm_name(name)
        if not n or is_target_column(name):
            continue
        kind = _value_kind(samples[name])
        for key, syns in _SYNONYMS.items():
            if n in syns:
                candidates.append(FieldGuess(key, name, "text", "nom:exact", 100))
            elif any(len(s) > 3 and (s in n.split() or n.startswith(s + " ") or n.endswith(" " + s)) for s in syns):
                candidates.append(FieldGuess(key, name, "text", "nom:partiel", 60))
        if kind == "location":
            candidates.append(FieldGuess("full_filename", name, "location_path", "valeurs:chemin:ligne", 95))
            candidates.append(FieldGuess("line_number", name, "location_line", "valeurs:chemin:ligne", 90))
        elif kind == "cwe":
            candidates.append(FieldGuess("cwe_ids", name, "cwe_list", "valeurs:cwe", 90))
        elif kind == "severity":
            candidates.append(FieldGuess("criticality_raw", name, "text", "valeurs:sévérité", 80))
        elif kind == "path":
            candidates.append(FieldGuess("full_filename", name, "text", "valeurs:chemin", 70))

    # Ajuster les transformations selon la nature des valeurs.
    for g in candidates:
        kind = _value_kind(samples[g.source])
        if g.key == "line_number" and g.transform == "text":
            g.transform = "int"
            if kind not in (None, "integer"):
                g.score -= 40
        if g.key == "cwe_ids" and g.transform == "text":
            g.transform = "cwe_list"
        if g.key == "full_filename" and g.transform == "text" and kind == "location":
            g.transform = "location_path"

    chosen: dict[str, FieldGuess] = {}
    used_text_sources: set[str] = set()
    for g in sorted(candidates, key=lambda g: -g.score):
        if g.key in chosen:
            continue
        # Une colonne ne nourrit qu'une clé, sauf emplacement -> chemin + ligne.
        if g.source in used_text_sources and g.transform not in ("location_path", "location_line"):
            continue
        if g.key == "source_comments":
            continue  # géré par comments_from
        chosen[g.key] = g
        if g.transform not in ("location_path", "location_line"):
            used_text_sources.add(g.source)

    comments = [
        name
        for name in field_names
        if norm_name(name) in _SYNONYMS["source_comments"] and name not in used_text_sources
    ]
    used = {g.source for g in chosen.values()} | set(comments)
    return MappingProposal(
        fields={k: {"source": g.source, "transform": g.transform} for k, g in chosen.items()},
        guesses=sorted(chosen.values(), key=lambda g: MAPPABLE_KEYS.index(g.key)),
        unmapped=[n for n in field_names if n not in used],
        missing=[k for k in IMPORTANT_KEYS if k not in chosen],
        comments_from=comments,
        detected_fields=list(field_names),
    )


# ---------------------------------------------------------------------------
# Application d'un mapping
# ---------------------------------------------------------------------------


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def _int(v: Any) -> int | None:
    s = _text(v)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def apply_transform(transform: str, value: Any) -> Any:
    if transform == "int":
        return _int(value)
    if transform == "cwe_list":
        if isinstance(value, list):
            return parse_cwe_list([str(x) for x in value])
        return parse_cwe_list(_text(value))
    if transform in ("location_path", "location_line"):
        s = _text(value)
        if s is None:
            return None
        m = _LOCATION_RE.match(s)
        if transform == "location_path":
            return m.group("path") if m else s
        return int(m.group("line")) if m else None
    if transform == "basename":
        s = _text(value)
        return re.split(r"[/\\]", s)[-1] if s else None
    return _text(value)


class MappingError(ValueError):
    pass


def validate_mapping(mapping: dict[str, Any], field_names: list[str] | None = None) -> None:
    for key, spec in mapping.get("fields", {}).items():
        if key not in MAPPABLE_KEYS:
            raise MappingError(f"Clé interne inconnue : {key}")
        if spec.get("transform", "text") not in TRANSFORMS:
            raise MappingError(f"Transformation inconnue : {spec.get('transform')}")
        if field_names is not None and spec["source"] not in field_names:
            raise MappingError(f"Champ source absent : {spec['source']!r}")
    for key in mapping.get("constants", {}):
        if key not in MAPPABLE_KEYS:
            raise MappingError(f"Constante sur une clé inconnue : {key}")


def apply_mapping(record: RawRecord, mapping: dict[str, Any], tool: str) -> NormalizedFinding:
    values: dict[str, Any] = {}
    for key, value in mapping.get("constants", {}).items():
        values[key] = value
    for key, value in record.defaults.items():
        if key in MAPPABLE_KEYS and value is not None:
            values.setdefault(key, value)
    for key, spec in mapping.get("fields", {}).items():
        v = apply_transform(spec.get("transform", "text"), record.fields.get(spec["source"]))
        if (v is not None and v != []) or key not in values:
            values[key] = v
    comments = [
        f"{name}: {_text(record.fields.get(name))}"
        if len(mapping.get("comments_from", [])) > 1
        else _text(record.fields.get(name))
        for name in mapping.get("comments_from", [])
        if _text(record.fields.get(name))
    ]
    if comments:
        values["source_comments"] = "\n".join(c for c in comments if c)
    for key in ("description", "recommendation"):
        for title, body in record.sections.items():
            if norm_name(title) in _SYNONYMS[key] and not values.get(key):
                values[key] = body.strip()
    used = {spec["source"] for spec in mapping.get("fields", {}).values()} | set(mapping.get("comments_from", []))
    extra = {k: v for k, v in record.fields.items() if k not in used and v not in (None, "")}
    if record.sections:
        extra["_sections"] = record.sections
    return NormalizedFinding(
        tool=tool,
        source_id=_text(values.get("source_id")),
        application_name=_text(values.get("application_name")),
        version_name=_text(values.get("version_name")),
        category=_text(values.get("category")),
        fortify_category=_text(values.get("fortify_category")),
        primary_rule_id=_text(values.get("primary_rule_id")),
        analyzer_type=_text(values.get("analyzer_type")),
        primary_location=_text(values.get("primary_location")),
        line_number=values.get("line_number")
        if isinstance(values.get("line_number"), int)
        else _int(values.get("line_number")),
        full_filename=_text(values.get("full_filename")),
        function_name=_text(values.get("function_name")),
        criticality_raw=_text(values.get("criticality_raw")),
        cwe_ids=values.get("cwe_ids") or [],
        source_comments=_text(values.get("source_comments")),
        description=_text(values.get("description")),
        recommendation=_text(values.get("recommendation")),
        extra=_jsonable(extra),
        locator=record.locator,
        raw=_jsonable(record.fields),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

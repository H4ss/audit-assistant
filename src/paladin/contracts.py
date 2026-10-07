"""Contrats partagés de Paladin.

Ce module est la source unique des valeurs métier figées par la spécification
(sections 8, 10, 21 et 22). Toute autre partie du code importe ces constantes
plutôt que de réécrire des chaînes.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Verdicts (section 8, 10, 21.1)
# ---------------------------------------------------------------------------


class Verdict(StrEnum):
    """Verdict interne. NEEDS_REVIEW n'est jamais une valeur Excel."""

    TRUE_POSITIVE = "TRUE_POSITIVE"
    NOT_AN_ISSUE = "NOT_AN_ISSUE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


FINAL_VERDICTS: frozenset[Verdict] = frozenset({Verdict.TRUE_POSITIVE, Verdict.NOT_AN_ISSUE})

# Valeurs exactes autorisées dans la colonne Excel `analysis result`.
EXCEL_TRUE_POSITIVE = "True Positive"
EXCEL_NOT_AN_ISSUE = "Not an issue"
EXCEL_ANALYSIS_RESULT_VALUES: frozenset[str] = frozenset({EXCEL_TRUE_POSITIVE, EXCEL_NOT_AN_ISSUE})

# Commentaire de discussion, indépendant du verdict (section 21.2).
DISCUSSION_COMMENT = "security appetite to be discussed"

_LEGACY_VERDICT_ALIASES: dict[str, Verdict] = {
    "TP": Verdict.TRUE_POSITIVE,
    "TRUE POSITIVE": Verdict.TRUE_POSITIVE,
    "TRUE_POSITIVE": Verdict.TRUE_POSITIVE,
    "FP": Verdict.NOT_AN_ISSUE,
    "FALSE POSITIVE": Verdict.NOT_AN_ISSUE,
    "NOT AN ISSUE": Verdict.NOT_AN_ISSUE,
    "NOT_AN_ISSUE": Verdict.NOT_AN_ISSUE,
    "NEEDS_REVIEW": Verdict.NEEDS_REVIEW,
    "NEEDS REVIEW": Verdict.NEEDS_REVIEW,
}


def normalize_verdict(raw: str) -> Verdict:
    """Normalise un libellé interne historique (TP/FP...) vers un Verdict.

    Lève ValueError pour toute valeur inconnue : on ne devine pas.
    """
    key = " ".join(raw.strip().upper().replace("-", " ").split())
    try:
        return _LEGACY_VERDICT_ALIASES[key]
    except KeyError:
        try:
            return _LEGACY_VERDICT_ALIASES[key.replace(" ", "_")]
        except KeyError:
            raise ValueError(f"Verdict inconnu : {raw!r}") from None


def verdict_to_excel(verdict: Verdict | None) -> str | None:
    """Traduit un verdict *validé* vers la cellule `analysis result`.

    NEEDS_REVIEW et None donnent une cellule vide (None).
    """
    if verdict == Verdict.TRUE_POSITIVE:
        return EXCEL_TRUE_POSITIVE
    if verdict == Verdict.NOT_AN_ISSUE:
        return EXCEL_NOT_AN_ISSUE
    return None


# ---------------------------------------------------------------------------
# États (section 8) — trois dimensions séparées
# ---------------------------------------------------------------------------


class ProcessingState(StrEnum):
    IMPORTED = "imported"
    PENDING = "pending"
    ANALYZING = "analyzing"
    PROPOSAL_READY = "proposal_ready"
    ERROR = "error"


class ReviewState(StrEnum):
    TO_REVIEW = "to_review"
    INVESTIGATING = "investigating"
    VALIDATED = "validated"
    REEXAM_REQUIRED = "reexam_required"


class ExportState(StrEnum):
    NOT_EXPORTED = "not_exported"
    EXPORTED = "exported"
    STALE = "stale"
    CONFLICT = "conflict"


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    ANALYSIS = "analysis"
    SHEET_SCHEMA = "sheet_schema"
    COMPARISON = "comparison"


class DecisionAction(StrEnum):
    ACCEPT = "accept"  # proposition acceptée telle quelle
    CORRECT = "correct"  # verdict et/ou commentaire modifié par l'analyste
    INVESTIGATE = "investigate"  # « À investiguer », avec question et motif
    SKIP = "skip"  # passer (pas de décision, simple trace)
    UNDO = "undo"  # annule l'événement désigné
    BATCH = "batch"  # décision issue d'un lot
    IMPORT = "import"  # reprise d'une valeur déjà saisie dans un classeur existant


class Authority(StrEnum):
    """Qui a produit l'événement. L'agent n'a jamais l'autorité de décision."""

    HUMAN = "human"
    BATCH = "batch"
    IMPORT = "import"  # valeur saisie hors Paladin, reprise d'un classeur existant


class Completeness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class SourceIdKind(StrEnum):
    NATIVE = "native"  # identifiant fourni par l'outil
    FINGERPRINT = "fingerprint"  # empreinte documentée calculée par Paladin


class SourceRole(StrEnum):
    """Rôle d'une source pour un outil (section 21.3) — configurable, jamais deviné."""

    INVENTORY = "inventory"  # lignes à compléter (ex. Excel concurrent)
    DETAILS = "details"  # contexte et preuves (ex. MD)
    FINDINGS = "findings"  # source unique d'inventaire et de détails (ex. Fortify)


class MatchState(StrEnum):
    """Rapprochement intra-outil d'un enregistrement source (Excel/MD)."""

    MATCHED = "matched"
    INVENTORY_ONLY = "inventory_only"  # Excel sans détail MD
    DETAILS_ONLY = "details_only"  # MD sans ligne Excel -> proposition de nouvelle ligne
    AMBIGUOUS = "ambiguous"
    COLLISION = "collision"


# ---------------------------------------------------------------------------
# Rapprochement inter-outils (section 22)
# ---------------------------------------------------------------------------


class RelationType(StrEnum):
    SAME_OCCURRENCE = "same_occurrence"
    SAME_ROOT_CAUSE = "same_root_cause"
    RELATED = "related"
    DIFFERENT = "different"


class RelationState(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    REEXAM_REQUIRED = "reexam_required"


# Valeurs par défaut de la projection `Found in <outil>` (section 22.5).
FOUND_IN_YES = "Yes"
FOUND_IN_PENDING = "Pending review"
FOUND_IN_UNKNOWN = "Unknown"
FOUND_IN_NO_CONFIRMED = "No confirmed match"


class RuleStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    REVOKED = "revoked"


class SchemaStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Contrat Excel métier (section 21.1)
# ---------------------------------------------------------------------------


class ExcelColumn(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    header: str
    analyst: bool = False  # colonne sous contrôle exclusif de l'analyste
    comparative: bool = False  # colonne projetée depuis les liens inter-outils
    text: bool = False  # toujours écrite comme texte (identifiants)


# Ordre et libellés par défaut d'un classeur neuf. Un classeur existant garde
# ses en-têtes réels, associés à ces clés par mapping.
DEFAULT_COLUMNS: tuple[ExcelColumn, ...] = (
    ExcelColumn(key="application_name", header="Application name"),
    ExcelColumn(key="version_name", header="Version name"),
    ExcelColumn(key="category", header="Category"),
    ExcelColumn(key="primary_location", header="Primary location"),
    ExcelColumn(key="line_number", header="Line number"),
    ExcelColumn(key="full_filename", header="Full filename"),
    ExcelColumn(key="criticality_raw", header="Criticality"),
    ExcelColumn(key="source_comments", header="Comments"),
    ExcelColumn(key="analyzer_type", header="Analyzer"),
    ExcelColumn(key="primary_rule_id", header="Primary rule ID", text=True),
    ExcelColumn(key="instance_id", header="Instance ID", text=True),
    ExcelColumn(key="fortify_category", header="Fortify Category"),
    ExcelColumn(key="cwe_ids", header="CWE"),
    ExcelColumn(key="analyst_result", header="analysis result", analyst=True),
    ExcelColumn(key="analyst_comment", header="Analysis result comment", analyst=True, text=True),
)

ANALYST_KEYS: frozenset[str] = frozenset(c.key for c in DEFAULT_COLUMNS if c.analyst)

# En-têtes équivalents reconnus dans un classeur existant (export en anglais, anciens modèles conservés).
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "source_comments": ("Commentaires",),  # libellé par défaut de la spec 21.1, avant le passage à l'anglais
}

# Champs purement Fortify : non imposés aux onglets concurrents (section 21.1).
FORTIFY_ONLY_KEYS: frozenset[str] = frozenset({"fortify_category", "analyzer_type"})


def found_in_header(tool_label: str) -> str:
    return f"Found in {tool_label}"


def criticality_in_header(tool_label: str) -> str:
    return f"criticality in {tool_label}"


def format_cwe_ids(cwe_ids: list[str]) -> str:
    """Export stable : `CWE-79; CWE-89` (ordre numérique, sans doublon)."""

    def _num(c: str) -> tuple[int, str]:
        digits = "".join(ch for ch in c if ch.isdigit())
        return (int(digits) if digits else 10**9, c)

    return "; ".join(sorted(set(cwe_ids), key=_num))


_CWE_RE = re.compile(r"^(?:CWE)?[\s\-:_]*(?:ID)?[\s\-:_]*(\d+)$", re.IGNORECASE)


def normalize_cwe(raw: str | int) -> str | None:
    """`79`, `CWE-79`, `cwe 79`, `CWE ID 79` -> `CWE-79`. None si non reconnu."""
    m = _CWE_RE.match(str(raw).strip())
    return f"CWE-{int(m.group(1))}" if m else None


def parse_cwe_list(raw: str | list[Any] | None) -> list[str]:
    if raw is None:
        return []
    items: list[Any] = raw if isinstance(raw, list) else str(raw).replace(",", ";").split(";")
    out: list[str] = []
    for item in items:
        n = normalize_cwe(item) if str(item).strip() else None
        if n and n not in out:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Finding normalisé (schéma commun des importeurs)
# ---------------------------------------------------------------------------


class NormalizedFinding(BaseModel):
    """Sortie commune de tous les importeurs.

    Les valeurs sont brutes (telles que fournies par la source). Une valeur
    absente reste None : aucun 0, aucune CWE ou catégorie devinée.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str
    source_id: str | None = None  # identifiant natif (Instance ID ou équivalent)
    application_name: str | None = None
    version_name: str | None = None
    version_source_id: str | None = None  # identifiant réel de la version (Fortify)
    category: str | None = None
    fortify_category: str | None = None
    primary_rule_id: str | None = None
    analyzer_type: str | None = None
    primary_location: str | None = None
    line_number: int | None = None
    full_filename: str | None = None
    function_name: str | None = None
    criticality_raw: str | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    source_comments: str | None = None
    description: str | None = None
    recommendation: str | None = None
    trace: list[dict[str, Any]] | None = None  # None = trace indisponible
    extra: dict[str, Any] = Field(default_factory=dict)  # champs spécifiques à l'outil
    locator: str  # où se trouve l'enregistrement dans la source (onglet/ligne, section MD...)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("line_number")
    @classmethod
    def _positive_line(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            return None
        return v


# ---------------------------------------------------------------------------
# Contrat de l'agent (section 10)
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line_start: int = Field(ge=1)
    line_end: int | None = Field(default=None, ge=1)
    repo: str | None = None
    commit: str | None = None
    excerpt: str | None = None
    note: str | None = None


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    detail: str | None = None


class ModelConfidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["low", "medium", "high"]
    calibrated: Literal[False] = False  # aucune calibration au MVP


class AgentProposal(BaseModel):
    """Réponse structurée obligatoire de l'agent (section 10)."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    input_revision: int = Field(ge=1)
    proposed_verdict: Verdict
    summary: str = Field(min_length=1, max_length=4000)
    suggested_analysis_result_comment: str = Field(default="", max_length=2000)
    discussion_required: bool = False
    discussion_reason: str = ""
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    model_confidence: ModelConfidence
    candidate_rule_ids: list[str] = Field(default_factory=list)
    next_action: str = ""

    @field_validator("proposed_verdict", mode="before")
    @classmethod
    def _normalize(cls, v: Any) -> Any:
        return normalize_verdict(v) if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Proposition de schéma d'onglet (section 21.4)
# ---------------------------------------------------------------------------


class SheetColumnProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header: str = Field(min_length=1, max_length=255)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: Literal["text", "integer", "list", "enum"] = "text"
    source_field: str | None = None  # champ détecté dans la source
    example: str | None = None
    availability: Literal["present", "partial", "absent"] = "present"
    required: bool = False
    transformation: str | None = None  # description déclarative, jamais du code exécuté
    locked: bool = False  # colonne analyste/comparative au sens métier figé


class SheetSchemaProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    sheet_name: str = Field(min_length=1, max_length=31)
    columns: list[SheetColumnProposal]
    uncovered_fields: list[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("sheet_name")
    @classmethod
    def _excel_sheet_name(cls, v: str) -> str:
        forbidden = set("[]:*?/\\")
        if any(ch in forbidden for ch in v) or v.startswith("'") or v.endswith("'"):
            raise ValueError("Nom d'onglet Excel invalide")
        if v.strip().lower() == "history":
            raise ValueError("Nom d'onglet réservé par Excel")
        return v

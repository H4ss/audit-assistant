"""Enregistrements bruts communs à toutes les sources.

Chaque lecteur (Excel, CSV, MD, SARIF, Fortify) produit des `RawRecord` :
un dictionnaire champ -> valeur tel que lu, et un localisateur précis. Le
mapping transforme ensuite ces enregistrements en `NormalizedFinding`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paladin.contracts import Completeness


@dataclass
class RawRecord:
    fields: dict[str, Any]
    locator: str  # fichier!onglet!R5, fichier.md#L12-L40, page API 2 / index 3...
    defaults: dict[str, Any] = field(default_factory=dict)  # valeurs de niveau document (app, version)
    sections: dict[str, str] = field(default_factory=dict)  # sous-sections MD (Description, Evidence...)


@dataclass
class UnrecognizedPart:
    locator: str
    reason: str
    excerpt: str


@dataclass
class SourceRead:
    """Résultat de lecture d'une source, avant mapping."""

    kind: str  # excel | csv | md | sarif | fortify
    records: list[RawRecord]
    field_names: list[str]  # champs détectés (en-têtes, clés MD, champs JSON)
    unrecognized: list[UnrecognizedPart] = field(default_factory=list)
    ignored: list[UnrecognizedPart] = field(default_factory=list)  # ignorés par le profil déclaré
    expected_total: int | None = None
    completeness: Completeness = Completeness.UNKNOWN
    notes: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)

    def finalize_completeness(self) -> None:
        """Complète si rien n'est resté non reconnu ; sinon partielle. Jamais présumée."""
        if self.completeness == Completeness.PARTIAL:
            return
        if self.unrecognized or (self.expected_total is not None and self.expected_total != len(self.records)):
            self.completeness = Completeness.PARTIAL
        else:
            self.completeness = Completeness.COMPLETE

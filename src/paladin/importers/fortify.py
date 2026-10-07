"""Collecte Fortify.

Le connecteur est découpé en deux parties :

* une **source** qui parle à Fortify (`FortifySource`). Seule la source de
  fixtures existe à ce stade : aucun endpoint réel n'est codé tant qu'il n'a
  pas été vérifié sur l'instance (section 5) ;
* un **collecteur** indépendant de la source : sélection stricte de la version
  `release`, pagination, doublons, totaux, réponses brutes horodatées avec
  empreintes, manifeste et reprise après échec.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from paladin.contracts import Completeness
from paladin.importers.records import RawRecord, SourceRead
from paladin.util import sha256_bytes, utcnow


class FortifyError(RuntimeError):
    """Erreur avec action corrective pour l'utilisateur."""

    def __init__(self, message: str, action: str) -> None:
        super().__init__(message)
        self.action = action


class TokenExpiredError(FortifyError):
    def __init__(self) -> None:
        super().__init__("Jeton Fortify expiré ou refusé.", "Renouveler le jeton puis relancer l'import avec --resume.")


class PageFailedError(FortifyError):
    def __init__(self, start: int, detail: str) -> None:
        super().__init__(f"Échec de la page démarrant à {start} : {detail}", "Relancer l'import avec --resume.")


class VersionSelectionError(FortifyError):
    pass


@dataclass
class Page:
    data: list[dict[str, Any]]
    total: int | None
    raw: bytes  # réponse brute, conservée telle quelle


class FortifySource(Protocol):
    name: str

    def list_applications(self) -> Page: ...
    def list_versions(self, application_id: Any) -> Page: ...
    def issues_page(self, version_id: Any, start: int, limit: int) -> Page: ...
    def issue_details(self, issue_id: Any) -> Page: ...


class FixtureFortifySource:
    """Source lisant des captures fictives. `faults` simule les erreurs réelles."""

    name = "fixture"

    def __init__(self, root: Path, faults: dict[str, Any] | None = None) -> None:
        self.root = root
        self.faults = faults or {}
        self.calls = 0

    def _load(self, rel: str) -> Page:
        self.calls += 1
        expire_after = self.faults.get("expire_token_after_calls")
        if expire_after is not None and self.calls > expire_after:
            raise TokenExpiredError()
        path = self.root / rel
        if not path.exists():
            return Page([], 0, b'{"data": [], "count": 0}')
        raw = path.read_bytes()
        doc = json.loads(raw)
        data = doc.get("data", [])
        if isinstance(data, dict):
            data = [data]
        return Page(data, doc.get("count"), raw)

    def list_applications(self) -> Page:
        return self._load("projects.json")

    def list_versions(self, application_id: Any) -> Page:
        return self._load(f"versions_{application_id}.json")

    def issues_page(self, version_id: Any, start: int, limit: int) -> Page:
        if start in self.faults.get("fail_pages_at", ()):
            self.faults["fail_pages_at"] = [s for s in self.faults["fail_pages_at"] if s != start]
            raise PageFailedError(start, "erreur simulée (HTTP 502)")
        self.calls += 1
        expire_after = self.faults.get("expire_token_after_calls")
        if expire_after is not None and self.calls > expire_after:
            raise TokenExpiredError()
        # Les captures sont rangées en fichiers p1, p2… ; la page demandée est découpée dans leur concaténation.
        items: list[dict[str, Any]] = []
        total = None
        for page in sorted(self.root.glob(f"issues_{version_id}_p*.json")):
            doc = json.loads(page.read_bytes())
            items += doc.get("data", [])
            total = doc.get("count", total)
        chunk = items[start : start + limit]
        raw = json.dumps({"data": chunk, "count": total, "start": start, "limit": limit}).encode("utf-8")
        return Page(chunk, total, raw)

    def issue_details(self, issue_id: Any) -> Page:
        return self._load(f"details/{issue_id}.json")


# ---------------------------------------------------------------------------
# Sélection stricte de l'application et de la version
# ---------------------------------------------------------------------------


@dataclass
class VersionChoice:
    application_id: Any
    application_name: str
    version_id: Any
    version_name: str


def select_version(
    source: FortifySource,
    application_name: str,
    version_name: str = "release",
    version_id: Any = None,
) -> VersionChoice:
    """Sélectionne exactement la version nommée `version_name`.

    Absente ou ambiguë : blocage. `version_id` ne sert qu'à lever une
    ambiguïté entre versions portant exactement ce nom ; il ne permet jamais de
    choisir une autre version.
    """
    apps = [a for a in source.list_applications().data if a.get("name") == application_name]
    if not apps:
        raise VersionSelectionError(
            f"Application {application_name!r} introuvable dans Fortify.",
            "Vérifier le nom exact de l'application (sensible à la casse) et les droits du compte.",
        )
    if len(apps) > 1:
        raise VersionSelectionError(
            f"Plusieurs applications nommées {application_name!r} : {[a.get('id') for a in apps]}.",
            "Préciser l'identifiant d'application dans la configuration de campagne.",
        )
    app = apps[0]
    versions = source.list_versions(app["id"]).data
    matching = [v for v in versions if v.get("name") == version_name]
    available = sorted({str(v.get("name")) for v in versions})
    if not matching:
        raise VersionSelectionError(
            f"Version {version_name!r} absente pour {application_name!r}. Versions disponibles : {available}.",
            f"Créer ou renommer la version {version_name!r} dans Fortify, ou corriger la configuration. "
            "Aucune autre version n'est sélectionnée automatiquement.",
        )
    if version_id is not None:
        matching = [v for v in matching if str(v.get("id")) == str(version_id)]
        if not matching:
            raise VersionSelectionError(
                f"La version d'identifiant {version_id} ne s'appelle pas {version_name!r}.",
                "Choisir un identifiant parmi les versions portant exactement ce nom.",
            )
    if len(matching) > 1:
        raise VersionSelectionError(
            f"Version {version_name!r} ambiguë : identifiants {[v.get('id') for v in matching]}.",
            "Indiquer `version_id` dans la configuration de campagne pour lever l'ambiguïté.",
        )
    v = matching[0]
    return VersionChoice(app["id"], app["name"], v["id"], v["name"])


# ---------------------------------------------------------------------------
# Collecte paginée avec manifeste et reprise
# ---------------------------------------------------------------------------


@dataclass
class CollectResult:
    read: SourceRead
    manifest: dict[str, Any]
    manifest_path: Path
    error: FortifyError | None = None


@dataclass
class _Capture:
    dir: Path
    entries: list[dict[str, Any]] = field(default_factory=list)

    def save(self, name: str, raw: bytes, **meta: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_bytes(raw)
        self.entries.append({"file": name, "sha256": sha256_bytes(raw), "collected_at": utcnow(), **meta})


def _iter_pages(source: FortifySource, version_id: Any, limit: int, start: int) -> Iterator[tuple[int, Page]]:
    while True:
        page = source.issues_page(version_id, start, limit)
        yield start, page
        if not page.data or len(page.data) < limit:
            return
        start += limit


def collect(
    source: FortifySource,
    choice: VersionChoice,
    capture_dir: Path,
    page_size: int = 8,
    with_details: bool = True,
    filters: dict[str, Any] | None = None,
    resume_manifest: dict[str, Any] | None = None,
) -> CollectResult:
    """Collecte toutes les pages de la version choisie.

    En cas d'échec, les pages déjà collectées restent importables et la
    collecte est marquée partielle ; `resume_manifest` permet de reprendre.
    """
    capture = _Capture(capture_dir)
    by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    pages_done: list[int] = []
    total: int | None = None
    start = 0
    if resume_manifest:
        pages_done = list(resume_manifest.get("pages_done", []))
        capture.entries = list(resume_manifest.get("captures", []))
        for entry in capture.entries:
            if entry.get("kind") == "issues_page":
                doc = json.loads((Path(resume_manifest["capture_dir"]) / entry["file"]).read_bytes())
                for item in doc.get("data", []):
                    _absorb(item, entry["start"], by_id, duplicates)
                total = doc.get("count", total)
        start = max(pages_done) + page_size if pages_done else 0
        capture.dir = Path(resume_manifest["capture_dir"])

    error: FortifyError | None = None
    try:
        for page_start, page in _iter_pages(source, choice.version_id, page_size, start):
            capture.save(f"issues-{page_start:06d}.json", page.raw, kind="issues_page", start=page_start)
            pages_done.append(page_start)
            total = page.total if page.total is not None else total
            for item in page.data:
                _absorb(item, page_start, by_id, duplicates)
        if with_details:
            done_details = {e["issue_id"] for e in capture.entries if e.get("kind") == "details"}
            for item in by_id.values():
                if str(item["id"]) in done_details:
                    continue
                det = source.issue_details(item["id"])
                capture.save(f"details-{item['id']}.json", det.raw, kind="details", issue_id=str(item["id"]))
    except FortifyError as exc:
        error = exc

    details = _load_details(capture)
    records = []
    for iid, item in by_id.items():
        merged = dict(item)
        d = details.get(str(item["id"]))
        if d is not None:
            merged["_details"] = d
        records.append(RawRecord(fields=merged, locator=f"fortify:version={choice.version_id}:issue={iid}"))
    missing_details = [r.fields["id"] for r in records if "_details" not in r.fields] if with_details else []

    complete = error is None and total is not None and total == len(by_id) and not missing_details
    read = SourceRead(
        kind="fortify",
        records=records,
        field_names=sorted({k for r in records for k in r.fields if not k.startswith("_")}),
        expected_total=total,
        completeness=Completeness.COMPLETE if complete else Completeness.PARTIAL,
    )
    read.scope = {
        "application_id": choice.application_id,
        "application_name": choice.application_name,
        "version_id": choice.version_id,
        "version_name": choice.version_name,
        "filters": filters or {},
        "source": source.name,
    }
    if duplicates:
        read.notes.append(f"{len(duplicates)} doublon(s) de transport ignoré(s) (même identifiant d'instance).")
    if total is not None and total != len(by_id):
        read.notes.append(f"Total annoncé {total}, identifiants uniques collectés {len(by_id)}.")
    if missing_details:
        read.notes.append(f"Détails manquants pour {len(missing_details)} finding(s).")
    if error:
        read.notes.append(f"Collecte interrompue : {error} → {error.action}")

    manifest = {
        "collected_at": utcnow(),
        "source": source.name,
        "scope": read.scope,
        "page_size": page_size,
        "pages_done": pages_done,
        "expected_total": total,
        "unique_ids": len(by_id),
        "transport_duplicates": duplicates,
        "missing_details": missing_details,
        "completeness": read.completeness.value,
        "error": None if error is None else {"message": str(error), "action": error.action},
        "immutable_snapshot": False,
        "snapshot_note": "La source ne garantit pas un instantané immuable : date de collecte et réponses brutes"
        " conservées.",
        "capture_dir": str(capture.dir),
        "captures": capture.entries,
    }
    capture.dir.mkdir(parents=True, exist_ok=True)
    manifest_path = capture.dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return CollectResult(read, manifest, manifest_path, error)


def _absorb(item: dict[str, Any], page_start: int, by_id: dict[str, dict[str, Any]], duplicates: list) -> None:
    iid = str(item.get("issueInstanceId") or item.get("id"))
    if iid in by_id:
        duplicates.append({"instance_id": iid, "page_start": page_start, "identical": by_id[iid] == item})
        return
    by_id[iid] = item


def _load_details(capture: _Capture) -> dict[str, dict[str, Any]]:
    out = {}
    for e in capture.entries:
        if e.get("kind") == "details":
            doc = json.loads((capture.dir / e["file"]).read_bytes())
            data = doc.get("data", doc)
            out[e["issue_id"]] = data
    return out


def details_to_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Champs normalisés issus de la réponse de détail (forme fictive, à vérifier)."""
    d = fields.get("_details") or {}
    trace = d.get("traceNodes")
    comments = d.get("comments") or []
    return {
        "description": d.get("brief"),
        "recommendation": d.get("recommendation"),
        "function_name": d.get("functionName"),
        "trace": trace if isinstance(trace, list) else None,
        "source_comments": "\n".join(
            f"[{c.get('username', '?')}] {c.get('comment', '')}" for c in comments if c.get("comment")
        )
        or None,
    }

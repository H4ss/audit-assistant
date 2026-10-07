"""Diagnostic Fortify SSC (section 5) : `paladin fortify check`.

Appels en lecture seule sur l'instance réelle. Chaque contrôle est OK, WARN ou
BLOCK avec une action. Le rapport (Markdown + JSON, sans secret) contient :
endpoints vérifiés, forme du jeton, filtres, totaux, sélection `release`,
matrice de disponibilité des champs et état global :

    « configuration bloquée » | « import possible, analyse limitée » | « parcours vérifié »

Le troisième état exige en plus un import et un export réussis sur une campagne
SSC (constaté, pas présumé).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from paladin.config import Settings
from paladin.doctor import Check, Status
from paladin.fortify.discovery import STATUS_OK, discover
from paladin.fortify.ssc import SSCClient, make_client, read_token
from paladin.importers.fortify import FortifyError
from paladin.importers.pipeline import DEFAULT_FORTIFY_FIELD_MAP
from paladin.util import file_stamp, utcnow

STATE_BLOCKED = "configuration bloquée"
STATE_LIMITED = "import possible, analyse limitée"
STATE_VERIFIED = "parcours vérifié"

# Champs du contrat Excel (section 21.1) et où on les attend dans SSC.
FIELD_FAMILIES = {
    "Identité": ["source_id"],
    "Détection": ["category", "fortify_category", "primary_rule_id", "cwe_ids", "criticality_raw", "analyzer_type"],
    "Localisation": ["primary_location", "line_number", "full_filename"],
}
DETAIL_FIELDS = {
    "description": "brief",
    "recommendation": "recommendation",
    "trace": "traceNodes",
    "function_name": "functionName",
    "audit_comments": "comments",
}


@dataclass
class FortifyReport:
    checks: list[Check] = field(default_factory=list)
    state: str = STATE_BLOCKED
    endpoints: list[dict[str, Any]] = field(default_factory=list)
    field_matrix: list[dict[str, Any]] = field(default_factory=list)
    sample: dict[str, Any] = field(default_factory=dict)
    groups: list[dict[str, Any]] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    token_form: str = ""

    def add(self, area: str, name: str, status: Status, detail: str, action: str = "") -> None:
        self.checks.append(Check(area, name, status, detail, action))

    @property
    def blocked(self) -> bool:
        return any(c.status == Status.BLOCK for c in self.checks)


def _field_matrix(issue: dict[str, Any], detail: dict[str, Any] | None, field_map: dict[str, str]) -> list[dict]:
    rows = []
    for family, keys in FIELD_FAMILIES.items():
        for key in keys:
            src = field_map.get(key)
            if src and issue.get(src) not in (None, "", []):
                where = "présent dans la liste"
            elif src and detail and detail.get(src) not in (None, "", []):
                where = "disponible via détail"
            elif src and src in issue:
                where = "présent mais vide sur l'échantillon"
            else:
                where = "indisponible (fourni par le dépôt, manuellement, ou à mapper)"
            rows.append({"famille": family, "champ": key, "source": src or "—", "disponibilité": where})
    for key, src in DETAIL_FIELDS.items():
        ok = bool(detail and detail.get(src) not in (None, "", []))
        rows.append(
            {
                "famille": "Analyse / audit",
                "champ": key,
                "source": f"issueDetails.{src}",
                "disponibilité": "disponible via détail" if ok else "indisponible sur l'échantillon",
            }
        )
    return rows


def run_check(
    settings: Settings, client: SSCClient | None = None, sample_app: str | None = None, discover_all: bool = True
) -> FortifyReport:
    rep = FortifyReport()
    url = (settings.fortify.get("url") or "").strip()
    if not url:
        rep.add("config", "url", Status.BLOCK, "URL SSC absente", "Renseigner l'URL (ex. https://ssc.entreprise/ssc).")
        return rep
    rep.add("config", "url", Status.OK, url if not url.startswith("demo://") else "SSC de démonstration (fictif)")
    if not url.startswith("demo://"):
        token, origin = read_token(settings)
        if not token:
            rep.add(
                "config",
                "jeton",
                Status.BLOCK,
                "Jeton absent",
                "Créer un jeton dans SSC (Administration > Gestion des jetons, type UnifiedLoginToken ou CIToken), "
                "puis le saisir dans « Prêt pour le travail ».",
            )
            return rep
        rep.add("config", "jeton", Status.OK, f"Jeton présent ({origin}) — jamais écrit dans le rapport")
        ca = settings.fortify.get("ca_bundle") or ""
        if ca and not Path(ca).is_file():
            rep.add(
                "config", "certificat", Status.BLOCK, f"ca_bundle introuvable : {ca}", "Corriger le chemin du .pem."
            )
            return rep
    try:
        client = client or make_client(settings)
    except FortifyError as exc:
        rep.add("config", "client", Status.BLOCK, str(exc), exc.action)
        return rep
    rep.filters = client.filters.as_dict()

    # 1. Accès et authentification.
    try:
        apps = client.list_applications().data
    except FortifyError as exc:
        rep.add("accès", "applications", Status.BLOCK, str(exc), exc.action)
        rep.endpoints = client.calls
        return rep
    rep.token_form = client.token_form
    rep.add("accès", "authentification", Status.OK, f"Jeton accepté (forme {client.token_form})")
    rep.add(
        "accès",
        "GET /projects",
        Status.OK if apps else Status.WARN,
        f"{len(apps)} application(s) visible(s)",
        "" if apps else "Aucune application visible : vérifier les droits du compte du jeton.",
    )

    # 2. Découverte (groupes, release, comptes).
    groups = []
    if discover_all and apps:
        try:
            groups = discover(client)
        except FortifyError as exc:
            rep.add("découverte", "versions", Status.BLOCK, str(exc), exc.action)
    rep.groups = [g.as_dict() for g in groups]
    if groups:
        subs = [a for g in groups for a in g.apps]
        ok = [a for a in subs if a.status == STATUS_OK]
        rep.add("découverte", "GET /projects/{id}/versions", Status.OK, f"{len(subs)} sous-application(s) lues")
        rep.add(
            "découverte",
            "version release",
            Status.OK if ok else Status.WARN,
            f"{len(ok)} avec une version « release » unique, {len(subs) - len(ok)} absente(s) ou ambiguë(s)",
            "" if len(ok) == len(subs) else "Les sous-applications sans « release » unique ne seront pas importées.",
        )

    # 3. Échantillon : findings et détail.
    target = None
    for g in groups:
        for a in g.ready:
            if (sample_app is None or a.app_name == sample_app) and (a.issue_count or 0) > 0:
                target = a
                break
        if target:
            break
    if target is None:
        rep.add(
            "findings",
            "échantillon",
            Status.WARN,
            "Aucune version release avec findings pour l'échantillon",
            "Indiquer une application avec --app.",
        )
    else:
        try:
            page = client.issues_page(target.version_id, 0, 1)
            issue = page.data[0] if page.data else {}
            rep.add(
                "findings",
                "GET /projectVersions/{id}/issues",
                Status.OK,
                f"{target.app_name} : {page.total} finding(s) annoncé(s) avec les filtres actuels",
            )
            detail = None
            try:
                det = client.issue_details(issue.get("id"))
                detail = det.data[0] if det.data else None
                rep.add(
                    "findings",
                    "GET /issueDetails/{id}",
                    Status.OK if detail else Status.WARN,
                    "détail lu" if detail else "détail vide",
                    "" if detail else "Trace et description indisponibles.",
                )
            except FortifyError as exc:
                rep.add(
                    "findings",
                    "GET /issueDetails/{id}",
                    Status.WARN,
                    str(exc),
                    "Import possible sans trace : analyse limitée. " + exc.action,
                )
            rep.field_matrix = _field_matrix(issue, detail, DEFAULT_FORTIFY_FIELD_MAP)
            rep.sample = {
                "application": target.app_name,
                "version_id": target.version_id,
                "issue_fields": sorted(issue),
                "detail_fields": sorted(detail or {}),
            }
            missing = [
                r["champ"]
                for r in rep.field_matrix
                if r["disponibilité"].startswith("indisponible") and r["famille"] != "Analyse / audit"
            ]
            if missing:
                rep.add(
                    "champs",
                    "matrice",
                    Status.WARN,
                    f"Champs du contrat non trouvés : {missing}",
                    "Ajuster field_map de la campagne d'après « issue_fields » du rapport, ou accepter ces vides.",
                )
            else:
                rep.add("champs", "matrice", Status.OK, "Tous les champs du contrat ont une source")
        except FortifyError as exc:
            rep.add("findings", "GET /projectVersions/{id}/issues", Status.BLOCK, str(exc), exc.action)
    rep.endpoints = client.calls
    # Sans import + export réussis, le meilleur état atteignable par ce diagnostic est « import possible ».
    rep.state = STATE_BLOCKED if rep.blocked else STATE_LIMITED
    return rep


def write_report(settings: Settings, rep: FortifyReport) -> tuple[Path, Path]:
    """Rapport sans secret : jamais de jeton, seulement sa forme acceptée."""
    reports = settings.home / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = file_stamp()
    data = {
        "generated_at": utcnow(),
        "state": rep.state,
        "checks": [asdict(c) | {"status": c.status.value} for c in rep.checks],
        "token_form": rep.token_form,
        "filters": rep.filters,
        "endpoints": rep.endpoints,
        "field_matrix": rep.field_matrix,
        "sample": rep.sample,
        "groups": rep.groups,
    }
    jpath = reports / f"fortify-check-{stamp}.json"
    jpath.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    lines = [
        f"# Diagnostic Fortify SSC — {data['generated_at'][:19]}",
        "",
        f"**État : {rep.state}**",
        "",
        "## Contrôles",
        "",
        "| Statut | Domaine | Contrôle | Détail | Action |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {c.status.value} | {c.area} | {c.name} | {c.detail} | {c.action} |" for c in rep.checks]
    lines += ["", f"Filtres de collecte : `{json.dumps(rep.filters)}`", "", "## Endpoints appelés", ""]
    seen = set()
    for e in rep.endpoints:
        key = (e["path"].split("?")[0], e["status"])
        if key not in seen:
            seen.add(key)
            lines.append(f"- `{key[0]}` → HTTP {key[1]}")
    if rep.field_matrix:
        lines += [
            "",
            "## Matrice de disponibilité des champs",
            "",
            "| Famille | Champ | Source | Disponibilité |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r['famille']} | {r['champ']} | `{r['source']}` | {r['disponibilité']} |" for r in rep.field_matrix
        ]
        lines += [
            "",
            f"Champs vus dans la liste : `{', '.join(rep.sample.get('issue_fields', []))}`",
            f"Champs vus dans le détail : `{', '.join(rep.sample.get('detail_fields', []))}`",
        ]
    if rep.groups:
        lines += [
            "",
            "## Applications (groupées par préfixe)",
            "",
            "| Groupe | Sous-application | Release | Findings |",
            "|---|---|---|---|",
        ]
        for g in rep.groups:
            for a in g["apps"]:
                rel = a["version_id"] if a["status"] == STATUS_OK else a["status"]
                count = a["issue_count"] if a["issue_count"] is not None else "—"
                lines.append(f"| {g['key']} | {a['app_name']} | {rel} | {count} |")
    mpath = reports / f"fortify-check-{stamp}.md"
    mpath.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mpath, jpath

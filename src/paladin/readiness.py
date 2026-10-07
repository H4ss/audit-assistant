"""« Prêt pour le travail ? » : checklist vivante du PC de travail.

Chaque élément est calculé à partir de l'état réel (configuration, fichiers,
résultats mémorisés des tests de connexion) et porte l'action suivante. Les
résultats des tests réels (modèle, sondage, diagnostic Fortify) sont mémorisés
dans `<home>/run/status.json` (sans secret).
"""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paladin import __version__, store
from paladin.config import Settings
from paladin.util import utcnow

OK, TODO, WARN = "ok", "à faire", "attention"


def _status_file(settings: Settings) -> Path:
    return settings.home / "run" / "status.json"


def record(settings: Settings, key: str, ok: bool, summary: str, **extra: Any) -> None:
    path = _status_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[key] = {"ok": ok, "summary": summary, "at": utcnow(), **extra}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def recorded(settings: Settings) -> dict[str, Any]:
    path = _status_file(settings)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@dataclass
class Item:
    section: str
    label: str
    status: str
    detail: str
    action: str = ""
    link: str = ""


def _when(entry: dict[str, Any]) -> str:
    return entry["at"][:16].replace("T", " ")


def checklist(settings: Settings, conn: sqlite3.Connection) -> list[Item]:
    st = recorded(settings)
    items: list[Item] = []
    add = items.append

    # Poste
    add(
        Item(
            "Poste",
            "Paladin installé",
            OK,
            f"Paladin {__version__}, Python {platform.python_version()} ({sys.platform})",
        )
    )
    add(Item("Poste", "Dossier de données", OK, str(settings.home), "Hors du dépôt Git ; ne jamais le partager."))

    # Agent
    exe = shutil.which("opencode")
    add(
        Item(
            "Agent (OpenCode + modèle)",
            "OpenCode installé",
            OK if exe else TODO,
            exe or "introuvable dans le PATH",
            "" if exe else "Installer OpenCode (https://opencode.ai) puis le connecter au fournisseur de l'entreprise.",
        )
    )
    model = settings.agent.get("model")
    smoke = st.get("agent_smoke")
    if smoke and smoke["ok"] and smoke.get("model") == model:
        add(Item("Agent (OpenCode + modèle)", "Modèle connecté et testé", OK, f"{model} — testé le {_when(smoke)}"))
    else:
        detail = f"{smoke['summary']}" if smoke and not smoke["ok"] else (model or "aucun modèle choisi")
        add(
            Item(
                "Agent (OpenCode + modèle)",
                "Modèle connecté et testé",
                TODO,
                detail,
                "Page « Agent » : détecter, choisir le GLM, « Tester et utiliser ».",
                "/agent",
            )
        )
    probe = st.get("agent_probe")
    add(
        Item(
            "Agent (OpenCode + modèle)",
            "Sondage de sécurité",
            OK if probe and probe["ok"] else TODO,
            f"{probe['summary']} ({_when(probe)})" if probe else "jamais lancé",
            "" if probe and probe["ok"] else "Page « Agent » : « Lancer le sondage ».",
            "/agent",
        )
    )

    # Fortify
    url = (settings.fortify.get("url") or "").strip()
    add(
        Item(
            "Fortify SSC",
            "URL SSC",
            OK if url else TODO,
            url or "non renseignée",
            "" if url else "Saisir l'URL ci-dessous (ex. https://ssc.entreprise/ssc).",
            "#ssc",
        )
    )
    if url.startswith("demo://"):
        add(Item("Fortify SSC", "Jeton", OK, "SSC de démonstration : jeton factice"))
    else:
        from paladin.fortify.ssc import read_token

        token, origin = read_token(settings)
        add(
            Item(
                "Fortify SSC",
                "Jeton (lecture seule)",
                OK if token else TODO,
                origin,
                "" if token else "Créer un jeton UnifiedLoginToken/CIToken dans SSC, le coller ci-dessous.",
                "#ssc",
            )
        )
        ca = settings.fortify.get("ca_bundle") or ""
        if ca:
            add(
                Item(
                    "Fortify SSC",
                    "Certificat d'entreprise",
                    OK if Path(ca).is_file() else WARN,
                    ca,
                    "" if Path(ca).is_file() else "Fichier .pem introuvable : corriger le chemin.",
                    "#ssc",
                )
            )
        else:
            add(
                Item(
                    "Fortify SSC",
                    "Certificat d'entreprise",
                    OK,
                    "magasin système (à renseigner seulement si erreur TLS)",
                )
            )
    chk = st.get("fortify_check")
    if chk:
        status = OK if chk["ok"] else WARN
        add(
            Item(
                "Fortify SSC",
                "Diagnostic « fortify check »",
                status,
                f"{chk['summary']} ({_when(chk)})",
                "" if chk["ok"] else "Ouvrir le rapport et suivre les actions.",
                chk.get("report", ""),
            )
        )
    else:
        add(
            Item(
                "Fortify SSC",
                "Diagnostic « fortify check »",
                TODO,
                "jamais lancé",
                "Bouton « Lancer le diagnostic ».",
                "#ssc",
            )
        )

    # Campagnes
    ssc_campaigns = [c for c in store.list_campaigns(conn) if not c["is_demo"] and _is_ssc(conn, c["id"])]
    add(
        Item(
            "Campagne",
            "Applications choisies (groupe SSC)",
            OK if ssc_campaigns else TODO,
            ", ".join(c["id"] for c in ssc_campaigns) or "aucune campagne SSC",
            "" if ssc_campaigns else "« Découvrir les applications », cocher le groupe APP, « Créer ».",
            "/fortify/discover",
        )
    )
    for c in ssc_campaigns:
        repos = store.list_repos(conn, c["id"])
        missing = [r["name"] for r in repos if not Path(r["path"]).is_dir()]
        add(
            Item(
                "Campagne",
                f"{c['id']} : dépôts de code",
                OK if repos and not missing else WARN,
                ", ".join(r["name"] for r in repos) or "aucun dépôt déclaré",
                "Sans dépôt, l'agent ne peut pas lire le code : ajouter les dossiers à la création."
                if not repos
                else (f"Introuvables : {missing}" if missing else ""),
            )
        )
        verified = conn.execute(
            "SELECT 1 FROM export_run WHERE campaign_id = ? AND status = 'verified' LIMIT 1", (c["id"],)
        ).fetchone()
        imported = conn.execute("SELECT COUNT(*) FROM finding WHERE campaign_id = ?", (c["id"],)).fetchone()[0]
        decided = conn.execute(
            "SELECT COUNT(*) FROM finding WHERE campaign_id = ? AND current_decision_id IS NOT NULL", (c["id"],)
        ).fetchone()[0]
        done = bool(imported and decided and verified)
        add(
            Item(
                "Campagne",
                f"{c['id']} : parcours vérifié",
                OK if done else TODO,
                f"{imported} importé(s), {decided} décidé(s), export vérifié : {'oui' if verified else 'non'}",
                "" if done else "Importer, décider quelques findings, exporter : cela vérifie toute la chaîne.",
                f"/c/{c['id']}",
            )
        )
    return items


def _is_ssc(conn: sqlite3.Connection, campaign_id: str) -> bool:
    cfg = store.get_campaign(conn, campaign_id)["config"]
    return any(s.get("kind") == "fortify_ssc" for t in cfg.get("tools", []) for s in t.get("sources", []))

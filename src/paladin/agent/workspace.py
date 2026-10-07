"""Espace de travail OpenCode dédié à Paladin.

Généré dans le dossier de données (`<home>/agent/`), jamais dans la
configuration OpenCode globale de l'utilisateur, qui reste intacte. Contient :

    opencode.json                      modèle, fournisseur, permissions (tout refusé sauf paladin_*)
    .opencode/plugins/paladin.ts       plugin V2 sans dépendance : outils paladin_* (API agent locale)
    .opencode/agents/paladin-analyst.md
    .opencode/skills/paladin-appsec-triage/SKILL.md
    .paladin/connection.json           URL + jeton d'agent (local, jamais versionné)
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from paladin.config import Settings
from paladin.util import sha256_bytes

DEFAULT_MODEL = "openrouter/z-ai/glm-5.3"
TEMPLATE_FILES = (
    "plugins/paladin.ts",
    "agents/paladin-analyst.md",
    "skills/paladin-appsec-triage/SKILL.md",
)


@dataclass
class WorkspaceFile:
    path: Path
    action: str  # créé | mis à jour | inchangé


def workspace_dir(settings: Settings) -> Path:
    return settings.home / "agent"


def _template(rel: str) -> str:
    return (resources.files("paladin.agent") / "opencode" / rel).read_text(encoding="utf-8")


def skill_version() -> str:
    """Empreinte des instructions de l'agent (outil, agent, skill) : tracée avec chaque proposition."""
    return "skill-" + sha256_bytes("".join(_template(f) for f in TEMPLATE_FILES).encode("utf-8"))[:12]


def model_parts(model: str) -> tuple[str, str]:
    """`openrouter/z-ai/glm-5.3` -> (`openrouter`, `z-ai/glm-5.3`)."""
    provider, _, name = model.partition("/")
    if not name:
        raise ValueError(f"Modèle attendu au format fournisseur/modèle : {model!r}")
    return provider, name


def opencode_config(model: str) -> dict:
    """Configuration du projet de l'agent : modèle et permissions seulement.

    Aucun bloc `provider` : le fournisseur, son authentification et son proxy viennent de la
    configuration OpenCode déjà en place sur le poste (plug and play).
    """
    model_parts(model)
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        # Défense en profondeur : même l'agent par défaut de cet espace n'a que les outils Paladin.
        "permission": {"*": "deny", "paladin_*": "allow", "skill": {"*": "deny", "paladin-appsec-triage": "allow"}},
    }


def _write(path: Path, content: str, out: list[WorkspaceFile], mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    action = "créé" if previous is None else ("inchangé" if previous == content else "mis à jour")
    if action != "inchangé":
        path.write_text(content, encoding="utf-8")
    if mode is not None:
        with contextlib.suppress(OSError):  # Windows : ACL héritées du profil
            path.chmod(mode)
    out.append(WorkspaceFile(path, action))


def setup(settings: Settings, model: str | None = None) -> list[WorkspaceFile]:
    """Crée ou met à jour l'espace OpenCode de Paladin. Idempotent."""
    model = model or settings.agent.get("model") or DEFAULT_MODEL
    root = workspace_dir(settings)
    out: list[WorkspaceFile] = []
    _write(root / "opencode.json", json.dumps(opencode_config(model), indent=2) + "\n", out)
    # Fichiers d'une version précédente (outils au format OpenCode V1, ignorés par la V2).
    for stale in (root / ".opencode" / "tools" / "paladin.ts", root / ".opencode" / "package.json"):
        if stale.exists():
            stale.unlink()
            out.append(WorkspaceFile(stale, "supprimé"))
    for rel in TEMPLATE_FILES:
        _write(root / ".opencode" / rel, _template(rel), out)
    _write(root / ".gitignore", ".paladin/\nnode_modules/\n", out)
    return out


def write_connection(
    settings: Settings, url: str, model: str, campaign_id: str | None, worker: str = "opencode"
) -> Path:
    """Paramètres de connexion lus par les outils (jeton d'agent : autorité « proposer » uniquement)."""
    provider, _ = model_parts(model)
    conn = {
        "url": url,
        "token": settings.agent_token(),
        "model_requested": model,
        "model_provider": provider,
        "campaign_id": campaign_id,
        "worker": worker,
    }
    out: list[WorkspaceFile] = []
    path = workspace_dir(settings) / ".paladin" / "connection.json"
    _write(path, json.dumps(conn, indent=2) + "\n", out, mode=0o600)
    return path

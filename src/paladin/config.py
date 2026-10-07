"""Espace de travail local et configuration.

Le logiciel (dépôt Git) et les données métier sont séparés : l'espace de
travail vit hors du dépôt, par défaut dans le dossier de données de
l'utilisateur. Rien dans ce module n'écrit dans le dépôt.

Disposition d'un espace :

    <home>/
      paladin.toml            configuration locale (sans secret)
      paladin.sqlite          base durable
      secrets/                jetons (agent, Fortify) — jamais journalisés
      campaigns/<id>/
        inputs/               copies des fichiers originaux
        captures/             réponses brutes Fortify + manifeste
        exports/              classeurs produits
        backups/              sauvegardes avant écriture
        reports/              rapports doctor / recette
"""

from __future__ import annotations

import contextlib
import os
import secrets
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ENV_HOME = "PALADIN_HOME"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def default_home() -> Path:
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Paladin"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "paladin"


def default_demo_home() -> Path:
    """La démo vit dans un espace distinct de l'espace de travail réel."""
    return default_home().with_name(default_home().name + "-demo")


CONFIG_TEMPLATE = """\
# Configuration locale Paladin. Aucun secret ici : les jetons sont lus depuis
# des variables d'environnement ou le dossier secrets/ de l'espace.

[server]
host = "127.0.0.1"   # boucle locale uniquement
port = {port}

[agent]
# Client d'analyse : OpenCode. Le modèle est une configuration, pas une dépendance.
client = "opencode"
model = "openrouter/z-ai/glm-5.3"   # fournisseur/modèle ; version épinglée (l'alias glm-latest masque la version)
budget_usd = 1.5         # plafond par exécution de `paladin agent run`
lease_seconds = 900

[fortify]
product = "ssc"          # hypothèse à confirmer par le diagnostic
url = ""
version_name = "release" # version cible ; jamais remplacée silencieusement
token_env = "PALADIN_FORTIFY_TOKEN"
ca_bundle = ""           # certificat d'entreprise ; ne jamais désactiver TLS

[editor]
# Commande pour « ouvrir dans l'éditeur » ; {{path}} et {{line}} sont remplacés.
open_command = ""
"""


@dataclass
class Settings:
    home: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    agent: dict[str, Any] = field(default_factory=dict)
    fortify: dict[str, Any] = field(default_factory=dict)
    editor: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.home / "paladin.sqlite"

    @property
    def config_path(self) -> Path:
        return self.home / "paladin.toml"

    @property
    def secrets_dir(self) -> Path:
        return self.home / "secrets"

    def campaign_dir(self, campaign_id: str) -> Path:
        return self.home / "campaigns" / campaign_id

    def agent_token(self) -> str:
        """Jeton d'autorité *agent* : propose, ne valide jamais."""
        return _read_or_create_token(self.secrets_dir / "agent.token")

    def ui_token(self) -> str:
        """Jeton d'autorité *humaine* (interface locale), distinct de celui de l'agent."""
        return _read_or_create_token(self.secrets_dir / "ui.token")


def _read_or_create_token(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    with contextlib.suppress(OSError):  # Windows : ACL héritées du profil utilisateur
        path.chmod(0o600)
    return token


def init_home(home: Path, port: int = DEFAULT_PORT) -> Path:
    """Crée l'espace de travail s'il n'existe pas. N'écrase rien."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "campaigns").mkdir(exist_ok=True)
    (home / "secrets").mkdir(exist_ok=True)
    cfg = home / "paladin.toml"
    if not cfg.exists():
        cfg.write_text(CONFIG_TEMPLATE.format(port=port), encoding="utf-8")
    return home


def load_settings(home: Path | None = None) -> Settings:
    home = (home or default_home()).expanduser().resolve()
    data: dict[str, Any] = {}
    cfg = home / "paladin.toml"
    if cfg.exists():
        with cfg.open("rb") as fh:
            data = tomllib.load(fh)
    server = data.get("server", {})
    return Settings(
        home=home,
        host=server.get("host", DEFAULT_HOST),
        port=int(server.get("port", DEFAULT_PORT)),
        agent=data.get("agent", {}),
        fortify=data.get("fortify", {}),
        editor=data.get("editor", {}),
    )


def ensure_campaign_dirs(settings: Settings, campaign_id: str) -> Path:
    root = settings.campaign_dir(campaign_id)
    for sub in ("inputs", "captures", "exports", "backups", "reports"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False

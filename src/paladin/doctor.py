"""Diagnostic `paladin doctor`.

Chaque contrôle retourne OK, WARN (avertissement) ou BLOCK (bloquant) avec une
action corrective. Le rapport ne contient jamais de secret.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from paladin import __version__
from paladin.config import Settings
from paladin.db import applied_versions, available_migrations, connect

REFERENCE_PYTHON = (3, 14)
MIN_PYTHON = (3, 12)


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass
class Check:
    area: str
    name: str
    status: Status
    detail: str
    action: str = ""


def check_python() -> Check:
    v = sys.version_info[:2]
    detail = f"Python {platform.python_version()} ({sys.executable})"
    if v < MIN_PYTHON:
        return Check(
            "système",
            "python",
            Status.BLOCK,
            detail,
            f"Installer Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ (référence 3.14).",
        )
    if v != REFERENCE_PYTHON:
        return Check(
            "système", "python", Status.WARN, detail, "Version prise en charge mais différente de la référence 3.14."
        )
    return Check("système", "python", Status.OK, detail)


def check_os() -> Check:
    return Check("système", "os", Status.OK, f"{platform.system()} {platform.release()} ({platform.machine()})")


def check_home(settings: Settings) -> Check:
    home = settings.home
    if not home.exists():
        return Check("données", "dossier", Status.BLOCK, f"{home} absent", "Lancer `python -m paladin init`.")
    probe = home / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check(
            "données", "dossier", Status.BLOCK, f"{home} non inscriptible : {exc}", "Vérifier les droits du dossier."
        )
    return Check("données", "dossier", Status.OK, str(home))


def check_database(settings: Settings) -> Check:
    if not settings.db_path.exists():
        return Check("données", "base", Status.BLOCK, "Base absente", "Lancer `python -m paladin init`.")
    conn = connect(settings.db_path)
    try:
        done = applied_versions(conn)
    finally:
        conn.close()
    expected = {v for v, _, _ in available_migrations()}
    missing = sorted(expected - set(done))
    if missing:
        return Check(
            "données",
            "base",
            Status.WARN,
            f"Migrations en attente : {missing}",
            "Lancer `python -m paladin init` (sauvegarde automatique).",
        )
    return Check("données", "base", Status.OK, f"{settings.db_path} — schéma v{max(expected)}")


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        # Exécutable résolu par shutil.which, arguments fixes, sans shell.
        proc = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def check_opencode(settings: Settings) -> Check:
    exe = shutil.which("opencode")
    if not exe:
        return Check(
            "agent",
            "opencode",
            Status.WARN,
            "OpenCode introuvable dans le PATH",
            "Installer OpenCode (mode sans LLM toujours disponible : consultation, décisions manuelles, export).",
        )
    code, out = _run([exe, "--version"])
    version = out.splitlines()[0].split()[-1].lstrip("v") if out else "inconnue"
    if code != 0:
        return Check(
            "agent",
            "opencode",
            Status.WARN,
            f"{exe} : version illisible ({version})",
            "Vérifier l'installation OpenCode.",
        )
    model = settings.agent.get("model_requested", "glm-latest")
    provider = settings.agent.get("provider") or "non renseigné"
    return Check("agent", "opencode", Status.OK, f"{exe} v{version} — modèle demandé {model}, fournisseur {provider}")


def check_agent(settings: Settings) -> Check:
    from paladin.agent.workspace import DEFAULT_MODEL, model_parts, workspace_dir

    model = settings.agent.get("model") or DEFAULT_MODEL
    try:
        model_parts(model)
    except ValueError as exc:
        return Check("agent", "modèle", Status.BLOCK, str(exc), "Corriger [agent] model dans paladin.toml.")
    if not (workspace_dir(settings) / "opencode.json").exists():
        return Check(
            "agent",
            "espace OpenCode",
            Status.WARN,
            "Espace de l'agent non préparé",
            "Lancer `paladin agent setup` (la configuration OpenCode globale n'est pas modifiée).",
        )
    if not settings.agent.get("model"):
        return Check(
            "agent",
            "modèle",
            Status.WARN,
            f"Modèle par défaut {model} (non choisi explicitement)",
            "Lancer `Paladin.cmd agent connect` pour choisir et tester le modèle de votre OpenCode.",
        )
    return Check("agent", "espace OpenCode", Status.OK, f"Modèle {model} — espace {workspace_dir(settings)}")


def check_fortify(settings: Settings) -> Check:
    url = settings.fortify.get("url", "")
    if not url:
        return Check(
            "fortify",
            "configuration",
            Status.WARN,
            "Configuration bloquée : URL Fortify absente",
            "Renseigner [fortify] dans paladin.toml sur le PC de travail. Les campagnes MD/Excel restent utilisables.",
        )
    token_env = settings.fortify.get("token_env", "PALADIN_FORTIFY_TOKEN")
    if not os.environ.get(token_env):
        return Check(
            "fortify",
            "configuration",
            Status.WARN,
            f"Jeton absent ({token_env})",
            f"Définir la variable {token_env} (jamais dans Git).",
        )
    return Check(
        "fortify",
        "configuration",
        Status.WARN,
        "Configurée mais non vérifiée",
        "Le diagnostic API détaillé arrive au palier P4.",
    )


def run_checks(settings: Settings) -> list[Check]:
    checks = [check_python(), check_os(), check_home(settings)]
    if checks[-1].status != Status.BLOCK:
        checks.append(check_database(settings))
    checks += [check_opencode(settings), check_agent(settings), check_fortify(settings)]
    return checks


def render_text(checks: list[Check]) -> str:
    lines = [f"Paladin {__version__} — diagnostic"]
    for c in checks:
        lines.append(f"[{c.status.value:5}] {c.area}/{c.name} : {c.detail}")
        if c.action and c.status != Status.OK:
            lines.append(f"        → {c.action}")
    return "\n".join(lines)


def to_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) | {"status": c.status.value} for c in checks]


def write_report(settings: Settings, checks: list[Check]) -> Path:
    import json

    from paladin.util import utcnow

    reports = settings.home / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "doctor-latest.json"
    path.write_text(
        json.dumps(
            {"generated_at": utcnow(), "version": __version__, "checks": to_dicts(checks)}, indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return path

"""Connexion « plug and play » de l'agent à l'OpenCode déjà configuré sur le poste.

Paladin ne demande aucune clé de modèle : il réutilise les fournisseurs que
l'utilisateur a déjà connectés dans OpenCode (`opencode auth login`, `/connect`,
ou configuration globale de l'entreprise). Ce module :

1. détecte OpenCode et sa version ;
2. liste les modèles que cet OpenCode connaît (GLM en premier) ;
3. teste le modèle choisi avec une question d'une ligne (coût : une fraction de centime) ;
4. traduit l'erreur éventuelle en action précise ;
5. enregistre le modèle dans `paladin.toml`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from paladin.agent.runner import parse_opencode_output
from paladin.agent.workspace import model_parts, setup, workspace_dir
from paladin.config import Settings, set_config_value

SMOKE_PROMPT = "Test de connexion Paladin : réponds uniquement OK."


@dataclass
class ModelChoice:
    id: str  # fournisseur/modèle, tel qu'attendu par `opencode run --model`
    name: str
    provider: str

    @property
    def is_glm(self) -> bool:
        return "glm" in self.id.lower() or "glm" in self.name.lower()


@dataclass
class OpenCodeInfo:
    path: str | None
    version: str | None
    models: list[ModelChoice] = field(default_factory=list)
    default_model: str | None = None
    error: str | None = None


@dataclass
class SmokeResult:
    ok: bool
    model: str
    answer: str
    seconds: float
    cost_usd: float | None
    error: str | None = None
    action: str | None = None


def _run(args: list[str], settings: Settings, timeout: int) -> subprocess.CompletedProcess[str]:
    root = workspace_dir(settings)
    return subprocess.run(  # noqa: S603 — exécutable résolu par shutil.which, arguments fixes, sans shell
        args,
        cwd=root,
        env={**os.environ, "PWD": str(root)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _api_get(exe: str, settings: Settings, path: str) -> Any:
    proc = _run([exe, "api", "--standalone", "GET", path], settings, timeout=90)
    try:
        return json.loads(proc.stdout).get("data")
    except (json.JSONDecodeError, AttributeError):
        return None


def detect(settings: Settings) -> OpenCodeInfo:
    """OpenCode installé, sa version et les modèles qu'il sait déjà utiliser."""
    exe = shutil.which("opencode")
    if not exe:
        return OpenCodeInfo(None, None, error="OpenCode introuvable dans le PATH.")
    setup(settings)
    version = _run([exe, "--version"], settings, timeout=30).stdout.strip().split()[-1:] or [None]
    info = OpenCodeInfo(exe, (version[0] or "").lstrip("v") or None)
    seen: set[str] = set()
    for m in _api_get(exe, settings, "/api/model") or []:
        provider, model_id = m.get("providerID"), m.get("modelID") or m.get("id")
        if not provider or not model_id:
            continue
        full = f"{provider}/{model_id}"
        if full not in seen:
            seen.add(full)
            info.models.append(ModelChoice(full, m.get("name") or model_id, provider))
    info.models.sort(key=lambda c: (not c.is_glm, c.id))
    default = _api_get(exe, settings, "/api/model/default")
    if isinstance(default, dict) and default.get("providerID"):
        info.default_model = f"{default['providerID']}/{default.get('modelID') or default.get('id')}"
    return info


def explain_error(message: str, model: str) -> str:
    """Traduit une erreur d'OpenCode ou du fournisseur en action pour l'utilisateur."""
    provider = model.split("/", 1)[0]
    m = message.lower()
    if any(s in m for s in ("authentication", "unauthorized", "401", "api key", "apikey", "credential")):
        return (
            f"Le fournisseur « {provider} » n'est pas connecté dans OpenCode. Connecter-le une fois : "
            f"`opencode auth login` (ou `/connect` dans OpenCode), puis relancer ce test. "
            "Variante : définir la variable d'environnement de la clé avant de lancer Paladin."
        )
    if "not found" in m and "model" in m:
        return "Modèle inconnu de cet OpenCode : choisir un modèle dans la liste détectée (format fournisseur/modèle)."
    if "agent not found" in m:
        return "Espace de l'agent incomplet : lancer `Paladin.cmd agent setup`."
    if any(s in m for s in ("timeout", "timed out", "econnrefused", "unable to connect", "proxy", "certificate")):
        return (
            "Fournisseur injoignable : vérifier le proxy d'entreprise (HTTPS_PROXY)"
            " et le certificat (NODE_EXTRA_CA_CERTS)."
        )
    if "insufficient" in m or "credit" in m or "quota" in m or "402" in m:
        return "Crédit ou quota du fournisseur épuisé : vérifier le compte du fournisseur."
    return "Consulter le message ci-dessus ; `Paladin.cmd doctor` aide à localiser le problème."


def smoke_test(settings: Settings, model: str, timeout: int = 120) -> SmokeResult:
    """Pose une question d'une ligne au modèle via OpenCode (sans les outils Paladin)."""
    model_parts(model)  # valide le format fournisseur/modèle
    exe = shutil.which("opencode")
    if not exe:
        return SmokeResult(False, model, "", 0.0, None, "OpenCode introuvable.", "Installer OpenCode puis relancer.")
    setup(settings, model)
    t0 = time.monotonic()
    try:
        proc = _run([exe, "run", "--standalone", "--model", model, "--format", "json", SMOKE_PROMPT], settings, timeout)
    except subprocess.TimeoutExpired:
        return SmokeResult(
            False, model, "", float(timeout), None, "Pas de réponse dans le délai.", explain_error("timeout", model)
        )
    seconds = time.monotonic() - t0
    texts, errors = [], []
    for line in proc.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            texts.append(str((event.get("part") or {}).get("text", "")))
        elif event.get("type") == "error":
            err = event.get("error") or {}
            errors.append(str(err.get("message") or err))
    cost = parse_opencode_output(proc.stdout)["cost_usd"]
    answer = " ".join(texts).strip()
    if errors or not answer:
        message = "; ".join(errors) or (proc.stderr.strip()[-300:] or f"aucune réponse (code {proc.returncode})")
        return SmokeResult(False, model, answer, seconds, cost, message, explain_error(message, model))
    return SmokeResult(True, model, answer[:200], seconds, cost)


def record_smoke(settings: Settings, res: SmokeResult) -> None:
    from paladin import readiness

    summary = f"réponse « {res.answer} » en {res.seconds:.0f} s" if res.ok else f"échec : {res.error}"
    readiness.record(settings, "agent_smoke", res.ok, summary, model=res.model)


def save_model(settings: Settings, model: str) -> None:
    model_parts(model)
    set_config_value(settings.config_path, "agent", "model", model)
    settings.agent["model"] = model
    setup(settings, model)

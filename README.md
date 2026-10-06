# Project Paladin

Assistant **local** de triage et de comparaison AppSec : transformer un volume ingérable de findings (Fortify, rapports Markdown, classeurs concurrents) en un volume gérable de **décisions vérifiables**, puis compléter fidèlement l'Excel d'audit.

Le modèle **propose**, l'analyste **valide**. L'Excel ne reçoit que des décisions validées, au texte exact.

> Spécification de référence : [`SPECS_ASSISTANT_TRIAGE_APPSEC.md`](SPECS_ASSISTANT_TRIAGE_APPSEC.md) · Architecture : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Avancement : [`docs/BACKLOG.md`](docs/BACKLOG.md) · Limites : [`docs/LIMITS.md`](docs/LIMITS.md)

## État actuel

Palier **P0 — socle et contrats** : contrats métier, schéma SQLite et migrations, CLI, fixtures synthétiques, démo, diagnostic de base, CI Windows/Linux. Les imports, la revue, l'export et l'agent arrivent aux paliers suivants (voir le backlog).

Combinaisons vérifiées : Python 3.14 sur Linux (poste de développement) ; Windows/Linux 3.14 et Linux 3.12 via la CI. **Aucune connexion Fortify réelle ni GLM réelle n'a été vérifiée à ce stade.**

## Prérequis

- Git
- Python **3.14** (référence) — 3.12 et 3.13 pris en charge
- Aucun Docker, Node, compte payant ou clé LLM pour la démo

## Installation

### Linux

```bash
git clone https://github.com/H4ss/audit-assitant.git project-paladin
cd project-paladin
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m paladin demo
python -m paladin serve
```

### Windows (PowerShell)

```powershell
git clone https://github.com/H4ss/audit-assitant.git project-paladin
cd project-paladin
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m paladin demo
python -m paladin serve
```

Si l'activation PowerShell est bloquée par la stratégie d'exécution, appeler directement le Python du venv, sans activer :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m paladin demo
.\.venv\Scripts\python.exe -m paladin serve
```

`serve` affiche l'URL locale (boucle locale uniquement, port suivant libre si `8765` est occupé), le dossier de données et l'état des connecteurs.

## Où sont les données ?

Jamais dans le dépôt. Par défaut :

| OS | Espace de travail | Espace de démo |
|---|---|---|
| Windows | `%LOCALAPPDATA%\Paladin` | `%LOCALAPPDATA%\Paladin-demo` |
| Linux | `~/.local/share/paladin` | `~/.local/share/paladin-demo` |

Changer avec `--home <dossier>` ou la variable `PALADIN_HOME`. Paladin refuse un dossier de données situé dans le dépôt. Une mise à jour du logiciel ne touche pas aux campagnes.

## Commandes

| Commande | Rôle |
|---|---|
| `python -m paladin init` | Créer l'espace de travail réel (config, base, jetons locaux) |
| `python -m paladin demo [--reset]` | Créer l'espace de démonstration (données fictives) |
| `python -m paladin serve [--demo] [--port N]` | Lancer l'interface locale |
| `python -m paladin doctor [--json]` | Diagnostic : Python, dossiers, base, OpenCode, Fortify |
| `python -m paladin status` | Lister les campagnes |

## Tests

```bash
python -m pip install -r requirements-dev.lock
python -m pytest -m "not real"
```

Les tests marqués `real` (OpenCode/GLM, Fortify) sont opt-in et exclus de la CI.

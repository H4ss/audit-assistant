# Project Paladin

Assistant **local** de triage et de comparaison AppSec : transformer un volume ingérable de findings (Fortify, rapports Markdown, classeurs concurrents) en un volume gérable de **décisions vérifiables**, puis compléter fidèlement l'Excel d'audit.

Le modèle **propose**, l'analyste **valide**. L'Excel ne reçoit que des décisions validées, au texte exact.

> Spécification de référence : [`SPECS_ASSISTANT_TRIAGE_APPSEC.md`](SPECS_ASSISTANT_TRIAGE_APPSEC.md) · Architecture : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Avancement : [`docs/BACKLOG.md`](docs/BACKLOG.md) · Limites : [`docs/LIMITS.md`](docs/LIMITS.md)

## État actuel

Paliers livrés : **P0 — socle et contrats**, **P1 — imports multi-entrées et export Excel**. La revue dans l'interface (P2) et l'agent OpenCode/GLM (P3) arrivent ensuite (voir le backlog). À ce stade, les décisions existent dans le moteur et les tests, mais pas encore dans l'interface.

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
| `python -m paladin import [--tool X] [--resume]` | Importer les sources déclarées de la campagne |
| `python -m paladin inspect <fichier>` | Détecter les champs d'un rapport (xlsx, csv, md, sarif) et proposer un mapping |
| `python -m paladin profile list\|show\|validate <id>` | Valider une fois le mapping proposé d'une nouvelle source |
| `python -m paladin export [--final]` | Écrire les décisions validées (copie de travail par défaut) |

## Multi-entrées

Une source se déclare par son rôle (`findings`, `inventory`, `details`) et son type : Excel (fichier séparé ou onglet du classeur cible), CSV, Markdown (profils `heading-kv-v1`, `table-v1`), SARIF 2.1.0 ou Fortify. Pour une source inconnue, Paladin **propose** un mapping à partir des en-têtes et des valeurs (synonymes FR/EN, `chemin:ligne`, CWE, sévérités). La proposition est validée une fois, puis réutilisée pour toute source de même structure. Paladin infère aussi une **famille interne** (CWE d'abord, puis mots-clés, base toujours tracée) et une **route d'analyse** (flux de données, crypto, secret, configuration, dépendance) qui fixe les vérifications à mener. La catégorie brute de l'outil reste la seule exportée.

## Tests

```bash
python -m pip install -r requirements-dev.lock
python -m pytest -m "not real"
```

Les tests marqués `real` (OpenCode/GLM, Fortify) sont opt-in et exclus de la CI.

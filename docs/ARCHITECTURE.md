# Architecture courte

## Vue d'ensemble

```
               ┌──────────────────────────────┐
  Fortify ───▶ │ Importeurs (fortify, md,     │
  MD      ───▶ │ excel) → NormalizedFinding   │──┐
  Excel   ───▶ └──────────────────────────────┘  │
                                                  ▼
 ┌────────────┐  API agent (jeton agent)   ┌─────────────┐   UI (jeton humain)   ┌──────────┐
 │ OpenCode + │ ─ claim / context / ─────▶ │  Service    │ ◀──── revue, ──────── │ Analyste │
 │ GLM (P3)   │   submit proposal          │  Paladin    │       décisions       └──────────┘
 └────────────┘                            │  + SQLite   │
                                           └─────┬───────┘
                                                 ▼
                                       Exporteur Excel (colonnes autorisées,
                                       écriture atomique, manifeste)
```

## Modules (`src/paladin`)

| Module | Rôle | Palier |
|---|---|---|
| `contracts.py` | Valeurs figées (verdicts, `Not an issue` / `True Positive`, phrase de discussion), états, contrat Excel, schéma de proposition agent, `SheetSchemaProposal` | P0 |
| `db/` | Connexion SQLite (WAL, FK), migrations numérotées, sauvegarde avant mise à jour, migration publiée immuable | P0 |
| `config.py` | Espace de travail hors dépôt, `paladin.toml`, jetons agent / humain distincts | P0 |
| `store.py` | Campagnes, outils, dépôts, état d'interface ; transactions | P0 |
| `demo.py`, `fixtures/` | Espace de démo distinct, fixtures synthétiques, classeur généré | P0 |
| `doctor.py` | Diagnostic OK / WARN / BLOCK avec action corrective | P0 → P4 |
| `cli.py` | `init`, `demo`, `serve`, `doctor`, `status` | P0 |
| `web/` | FastAPI + Jinja2, assets locaux, boucle locale uniquement | P0 → P2 |
| `importers/` | Fortify (fixtures puis API vérifiée), MD par profil, Excel/CSV/SARIF, inférence de mapping et profils, pipeline | P1 |
| `classify.py` | Famille interne, route d'analyse, checklist | P1 |
| `excel/export.py` | Rapprochement par clé, export vérifié et atomique, manifeste | P1 |
| `review/decisions.py` | Décisions append-only, annulation, brouillons, révisions | P1 |
| `review/queue.py` | Vues, ordre stable, compteurs, données de la carte | P2 |
| `analysis.py` | Enregistrement des propositions, vérification des références, extraits de code | P2 |
| `fortify/ssc.py` | Client SSC lecture seule (jeton, TLS, proxy, pagination, erreurs) | P4 |
| `fortify/discovery.py`, `fortify/campaign.py` | Découverte groupée par préfixe, campagne par groupe | P4 |
| `fortify/check.py` | Diagnostic de l'instance et rapport sans secret | P4 |
| `agent/connect.py` | Connexion plug and play à l'OpenCode du poste | P4 |
| `readiness.py` | Checklist « Prêt pour le travail ? » | P4 |
| `campaigns.py` | Création d'une campagne réelle depuis un JSON validé | P2 |
| `agent/` | Jobs avec bail, API agent, outils OpenCode, skill | P3 |
| `matching.py` | Candidats, décisions de lien, lots, projections `Found in` / `criticality in` | P5 |
| `excel/sheets.py`, `excel/template.py` | Schéma d'onglet pour un nouvel outil, classeur neuf | P5 / P4 |
| `rules/` | Mémoire, règles, groupes et lots | P6 |

## Invariants

1. `analysis result` ne contient que `True Positive`, `Not an issue` ou une cellule vide.
2. `security appetite to be discussed` est indépendant du verdict (`discussion_required`).
3. Une proposition du modèle n'est jamais une décision. L'API agent ne peut ni valider, ni activer une règle, ni écrire dans l'Excel (autorité distincte).
4. Historique append-only : annuler = nouvel événement.
5. Toute écriture vérifie la révision attendue (double clic, réponse tardive).
6. Identifiant interne ≠ numéro de ligne Excel. Identifiant source contextualisé par outil / application / version. Collision d'empreinte exposée, jamais fusionnée.
7. Valeur absente = vide et signalée ; rien n'est inventé (ligne 0, CWE, catégorie, version).
8. Données métier et secrets hors du dépôt.

## Dépendances

`requirements.lock` fige les versions d'exécution ; toutes existent en wheels binaires pour Windows et Linux (pas de compilation native). Régénération :

```bash
python -m venv /tmp/lockenv && /tmp/lockenv/bin/python -m pip install -e . pytest
/tmp/lockenv/bin/python -m pip freeze --exclude project-paladin
# Puis vérifier les wheels Windows :
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 3.14 -r requirements.lock -d /tmp/wh
```

Seul le coordinateur modifie `requirements.lock` et les migrations.

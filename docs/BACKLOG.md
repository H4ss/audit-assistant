# Backlog durable

États : `todo` · `doing` · `done` · `blocked` (avec motif). Propriétaire : coordinateur (construction séquentielle).
Un palier se termine par un check avec l'utilisateur, puis un merge sur `main`, un tag `v0.N.0` et un push.

## P0 — Socle et contrats — `done` (v0.0.1)

Contrats, schéma SQLite et migrations, espace hors dépôt, fixtures, CLI, CI Windows/Linux (verte).

## P1 — Imports multi-entrées et Excel — `done` (v0.1.0)

Fortify (fixtures), MD, Excel/CSV, SARIF, inférence de mapping et profils, classification, rapprochement Excel+MD, identité, noyau des décisions, export vérifié.

## P2 — Revue et facilité d'usage — `done` (v0.2.0)

Carte de revue, raccourcis, brouillons, file stable, tableau de bord, import/profil/export depuis l'interface, sécurité locale, démarrage en double-clic.

## P3 — Agent OpenCode réel — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P3-0 | Norme de code : ruff (lint + format) imposé en CI, `.editorconfig`, `CONTRIBUTING.md` | done | job CI « Qualité » |
| P3-1 | Jobs avec bail + jeton : reprise après crash, ancien détenteur rejeté, 3 tentatives max | done | `test_agent.py` |
| P3-2 | API agent (jeton agent) : claim, contexte borné, lecture/recherche de code confinées, proposition validée par schéma ; aucune route de décision | done | `test_agent.py` |
| P3-3 | Plugin OpenCode V2 sans dépendance, agent `paladin-analyst` (tout refusé sauf `paladin_*`), skill `paladin-appsec-triage`, espace dédié sans toucher la config globale | done | `agent setup`, test réel |
| P3-4 | Runner `agent run` : une session par job, plafond de budget mesuré (OpenRouter + OpenCode), journal par job | done | `test_runner_*`, test réel |
| P3-5 | Traçage : modèle demandé, fournisseur, version des instructions, coût et tokens par job ; version résolue « unknown » (non fournie) | done | `test_proposal_validation_and_storage` |
| P3-6 | Sondage des accès effectifs (`agent probe`) : Code Mode neutralisé (`fetch` non bloquable), aucun outil hors `paladin_*` | done | sondage réel + `test_probe_*` |
| P3-7 | Interface : panneau Agent (connecté / attente / en cours), mise en file, bandeau « nouvelle proposition » | done | `test_web.py` |
| P3-8 | Test d'intégration réel opt-in (`-m real`) | done | `tests/test_real_agent.py` |

## P4 — Nouvel outil et diagnostic — `todo`
Validation des profils d'entrée dans l'interface ; proposition de mapping par l'agent pour les formats que l'heuristique ne couvre pas. `SheetSchemaProposal` (agent ou manuel), aperçu, validation, création idempotente d'onglet, évolution versionnée ; `doctor` Fortify complet (matrice des champs, filtres, totaux) et rapport sans secrets.

## P5 — Rapprochement inter-outils — `todo`
`ComparisonRun`, candidats bornés, vue côte à côte, liens (types/états), projections `Found in` / `criticality in`, invalidations.

## P6 — Mémoire, règles, lots — `todo`
Précédents, règles proposées/validées/révoquées, groupes avec comparaison par membre, lots figés, annulation de lot, réexamen.

## Hors de portée de ce poste (Étapes B/C)
- Diagnostic Fortify sur l'instance réelle (endpoints, champs, `release`) — PC de travail.
- Validation GLM sur le PC de travail ; pilote de 30–50 cas.

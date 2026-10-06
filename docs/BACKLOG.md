# Backlog durable

États : `todo` · `doing` · `done` · `blocked` (avec motif). Propriétaire : coordinateur (construction séquentielle).
Un palier se termine par un check avec l'utilisateur, puis un merge sur `main`, un tag `v0.N.0` et un push.

## P0 — Socle et contrats — `done` (v0.0.1)

Contrats, schéma SQLite et migrations, espace hors dépôt, fixtures, CLI, CI Windows/Linux (verte).

## P1 — Imports multi-entrées et Excel — `done` (v0.1.0)

Fortify (fixtures), MD, Excel/CSV, SARIF, inférence de mapping et profils, classification, rapprochement Excel+MD, identité, noyau des décisions, export vérifié.

## P2 — Revue et facilité d'usage — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P2-1 | Carte de revue : proposition, preuve principale, blocage d'abord ; détails, code, trace, provenance dépliables | done | `test_web.py` |
| P2-2 | Valider / Valider et rester / Passer / À investiguer / Annuler la dernière décision ; accept vs correct déterminé côté serveur | done | `test_web.py` |
| P2-3 | Deux champs analyste distincts, « Appétence à discuter » (phrase exacte, n'écrase pas un texte libre), motif interne | done | E2E navigateur |
| P2-4 | Raccourcis visibles, inactifs en saisie, flèches ignorées sur les contrôles, Entrée seule sans effet | done | E2E navigateur |
| P2-5 | Brouillons auto-enregistrés, refusés s'ils arrivent après une décision (révision) | done | `test_draft_api…`, E2E |
| P2-6 | File stable (vues : à revoir, prêtes, contexte manquant, à investiguer, réexamen, validés), suivant relatif à la position | done | `test_queue_does_not_reorder…` |
| P2-7 | Tableau de bord : reprise, compteurs factuels, « décision enregistrée » vs « Excel à jour / périmé » | done | `test_web.py` |
| P2-8 | Import, validation de profil (multi-entrées) et export depuis l'interface | done | `test_profile_validation_import_and_export_from_ui` |
| P2-9 | Sécurité locale : Host restreint, jeton d'interface + origine locale sur toute écriture, jeton agent refusé | done | `test_web.py` |
| P2-10 | Propositions simulées de démo (marquées), vérification des références de code | done | `test_card_shows…` |
| P2-11 | Facilité : `Paladin.cmd` / `paladin.sh`, `python -m paladin` = start + navigateur, `campaign create`, README court + GUIDE | done | CI (script), `test_cli.py` |

## P3 — Agent OpenCode réel — `todo`
Jobs avec bail, API agent (jeton agent, sans validation), outils OpenCode, agent + skill, validation JSON/références, traçage modèle. **Estimation du coût OpenRouter/GLM présentée avant tout appel réel.**

## P4 — Nouvel outil et diagnostic — `todo`
Validation des profils d'entrée dans l'interface ; proposition de mapping par l'agent pour les formats que l'heuristique ne couvre pas. `SheetSchemaProposal` (agent ou manuel), aperçu, validation, création idempotente d'onglet, évolution versionnée ; `doctor` Fortify complet (matrice des champs, filtres, totaux) et rapport sans secrets.

## P5 — Rapprochement inter-outils — `todo`
`ComparisonRun`, candidats bornés, vue côte à côte, liens (types/états), projections `Found in` / `criticality in`, invalidations.

## P6 — Mémoire, règles, lots — `todo`
Précédents, règles proposées/validées/révoquées, groupes avec comparaison par membre, lots figés, annulation de lot, réexamen.

## Hors de portée de ce poste (Étapes B/C)
- Diagnostic Fortify sur l'instance réelle (endpoints, champs, `release`) — PC de travail.
- Validation GLM sur le PC de travail ; pilote de 30–50 cas.

# Backlog durable

États : `todo` · `doing` · `done` · `blocked` (avec motif). Propriétaire : coordinateur (construction séquentielle).
Un palier se termine par un check avec l'utilisateur, puis un merge sur `main`, un tag `v0.N.0` et un push.

## P0 — Socle et contrats — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P0-1 | `pyproject`, `requirements.lock` (wheels Windows vérifiés), `.gitignore` données/secrets | done | install propre |
| P0-2 | Contrats : verdicts, valeurs Excel exactes, discussion, états, colonnes §21.1, `AgentProposal`, `SheetSchemaProposal` | done | `tests/test_contracts.py` |
| P0-3 | Schéma SQLite complet (§7, §22.6) + migrations, sauvegarde avant mise à jour, migration immuable | done | `tests/test_db.py` |
| P0-4 | Espace de travail hors dépôt, jetons agent/humain distincts, refus d'un dossier dans le dépôt | done | `tests/test_cli.py` |
| P0-5 | Fixtures : 2 dépôts fictifs, Fortify paginé (`release`, `dev`, absente, ambiguë, doublon), ToolB Excel+MD, ToolC MD (injection, ligne mal formée), classeur généré | done | `tests/test_fixtures.py` |
| P0-6 | CLI `init`/`demo`/`serve`/`doctor`/`status`, port occupé, boucle locale | done | `tests/test_cli.py` |
| P0-7 | CI GitHub Actions Windows/Linux | done | premier run après push |

## P1 — Imports et Excel — `todo`

| ID | Tâche | Dépend | Recette |
|---|---|---|---|
| P1-1 | Importeur Fortify sur fixtures : sélection stricte `release` (absente/ambiguë = blocage), pagination, doublons, totaux, manifeste + réponses brutes horodatées, reprise après page échouée | P0 | §15 : multi-pages, jeton expiré, release absente |
| P1-2 | Importeur MD par profil déclaré (`heading-kv-v1`, `table-v1`), offsets/sections, sections non reconnues, import partiel signalé | P0 | §15 : MD partiellement reconnu |
| P1-3 | Lecteur Excel par mapping d'onglet (en-têtes réels ↔ clés), clés stables, collisions bloquantes ligne par ligne | P0 | — |
| P1-4 | Rapprochement intra-outil Excel+MD : 3 compteurs, divergences conservées avec provenance par champ | P1-2, P1-3 | §15 : concurrent en désaccord |
| P1-5 | Identité : id source contextualisé, empreinte documentée, collisions exposées, réimport idempotent | P1-1..4 | §15 : réimporter deux fois |
| P1-6 | Export atomique : colonnes autorisées, texte non-formule, préservation formules/hors périmètre, sauvegarde, réouverture-vérification, manifeste, fichier verrouillé, conflit de modification externe | P1-3 | §15 : XLSX qualifié, classeur réordonné, Excel verrouillé |
| P1-7 | `paladin import` + démo importée | P1-1..5 | démo peuplée |

## P2 — Revue — `todo`
Carte de revue, Accepter/Corriger/À investiguer/Passer/Annuler, raccourcis, brouillons, révisions, file stable, reprise, décision enregistrée vs Excel à jour, propositions simulées de démo.

## P3 — Agent OpenCode réel — `todo`
Jobs avec bail, API agent (jeton agent, sans validation), outils OpenCode, agent + skill, validation JSON/références, traçage modèle. **Estimation du coût OpenRouter/GLM présentée avant tout appel réel.**

## P4 — Nouvel outil et diagnostic — `todo`
`SheetSchemaProposal` (agent ou manuel), aperçu, validation, création idempotente d'onglet, évolution versionnée ; `doctor` Fortify complet (matrice des champs, filtres, totaux) et rapport sans secrets.

## P5 — Rapprochement inter-outils — `todo`
`ComparisonRun`, candidats bornés, vue côte à côte, liens (types/états), projections `Found in` / `criticality in`, invalidations.

## P6 — Mémoire, règles, lots — `todo`
Précédents, règles proposées/validées/révoquées, groupes avec comparaison par membre, lots figés, annulation de lot, réexamen.

## Hors de portée de ce poste (Étapes B/C)
- Diagnostic Fortify sur l'instance réelle (endpoints, champs, `release`) — PC de travail.
- Validation GLM sur le PC de travail ; pilote de 30–50 cas.

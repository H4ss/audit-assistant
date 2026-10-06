# Backlog durable

États : `todo` · `doing` · `done` · `blocked` (avec motif). Propriétaire : coordinateur (construction séquentielle).
Un palier se termine par un check avec l'utilisateur, puis un merge sur `main`, un tag `v0.N.0` et un push.

## P0 — Socle et contrats — `done` (v0.0.1)

Contrats, schéma SQLite et migrations, espace hors dépôt, fixtures, CLI, CI Windows/Linux (verte).

## P1 — Imports multi-entrées et Excel — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P1-1 | Fortify sur fixtures : `release` stricte (absente/ambiguë = blocage), pagination, doublons, totaux, manifeste + réponses brutes, reprise, jeton expiré | done | `test_importers.py` (Fortify) |
| P1-2 | MD par profil (`heading-kv-v1`, `table-v1`), offsets, sections non reconnues → partiel | done | `test_importers.py` (Markdown) |
| P1-3 | Lecteurs génériques Excel (fichier ou onglet, détection de l'en-tête) et CSV ; SARIF 2.1.0 | done | idem |
| P1-4 | **Multi-entrées** : inférence de mapping (noms FR/EN + valeurs), profils proposés → validés → réutilisés ; colonnes cibles jamais prises pour des sources | done | `test_french_csv_mapping_inference`, CLI `inspect` |
| P1-5 | Classification interne (famille, base, route d'analyse, checklist) | done | `test_classification_basis_is_traceable` |
| P1-6 | Rapprochement Excel+MD : 3 compteurs, divergences conservées avec provenance par champ | done | `test_excel_md_counters_and_divergence` |
| P1-7 | Identité : id contextualisé, empreinte documentée, collisions exposées, réimport idempotent, réexamen si la source change | done | idem |
| P1-8 | Noyau des décisions (avancé depuis P2) : journal append-only, révisions, annulation, brouillons | done | `test_decisions.py` |
| P1-9 | Export : colonnes autorisées, texte non-formule, valeurs humaines protégées, clé à chaque export, qualification du classeur, verrou, vérification par réouverture, sauvegarde, remplacement atomique, manifeste, périmé | done | `test_export.py` |
| P1-10 | CLI `import`, `inspect`, `profile`, `export` ; démo importée | done | `test_cli.py` |

## P2 — Revue — `todo`
(Le noyau des décisions est déjà livré en P1.) Carte de revue, Accepter/Corriger/À investiguer/Passer/Annuler, raccourcis, brouillons, révisions, file stable, reprise, décision enregistrée vs Excel à jour, propositions simulées de démo.

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

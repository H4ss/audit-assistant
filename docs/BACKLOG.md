# Backlog durable

États : `todo` · `doing` · `done` · `blocked` (avec motif). Propriétaire : coordinateur (construction séquentielle).
Un palier se termine par un check avec l'utilisateur, puis un merge sur `main`, un tag `v0.N.0` et un push.

## P0 — Socle et contrats — `done` (v0.0.1)

Contrats, schéma SQLite et migrations, espace hors dépôt, fixtures, CLI, CI Windows/Linux (verte).

## P1 — Imports multi-entrées et Excel — `done` (v0.1.0)

Fortify (fixtures), MD, Excel/CSV, SARIF, inférence de mapping et profils, classification, rapprochement Excel+MD, identité, noyau des décisions, export vérifié.

## P2 — Revue et facilité d'usage — `done` (v0.2.0)

Carte de revue, raccourcis, brouillons, file stable, tableau de bord, import/profil/export depuis l'interface, sécurité locale, démarrage en double-clic.

## P3 — Agent OpenCode réel — `done` (v0.3.0)

Jobs à bail, API agent, plugin OpenCode V2, runner avec budget mesuré, sondage des accès, chaîne réelle GLM 5.3 vérifiée.

## P4 — Prêt pour le PC de travail — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P4-1 | Connexion plug and play de l'agent : détection des modèles de l'OpenCode du poste, test d'une ligne, erreurs traduites, enregistrement (`agent connect`, page « Agent ») ; aucun bloc fournisseur imposé, clé facultative | done | `test_connect.py`, test réel |
| P4-2 | Client SSC lecture seule : jeton (bascule d'encodage), certificat d'entreprise, proxy, pagination, erreurs → actions | done | `test_fortify_ssc.py` |
| P4-3 | Diagnostic `fortify check` : endpoints vérifiés sur l'instance, release, matrice des champs, rapport sans secret | done | idem |
| P4-4 | Découverte groupée par préfixe (`APP.*` = une entrée), release et nombre de findings par sous-application | done | idem + page « Applications SSC » |
| P4-5 | Campagne par groupe : plusieurs versions release agrégées en une entrée, sous-applications exclues listées, classeur généré si absent | done | `test_group_becomes_one_input…` |
| P4-6 | Déduction automatique des racines du scanner (refus en cas d'ambiguïté) | done | idem |
| P4-7 | Checklist vivante « Prêt pour le travail ? » + `docs/PC_DE_TRAVAIL.md` | done | `test_readiness…`, `test_web_travail.py` |
| P4-8 | SSC fictif pour la démo et les tests | done | — |

## P5 — Nouvel outil et rapprochement inter-outils — `todo`
`SheetSchemaProposal` pour un outil sans onglet (ToolC) : proposition, aperçu, validation, création idempotente ; proposition de mapping d'entrée par l'agent pour les formats atypiques. Puis `ComparisonRun`, candidats bornés, vue côte à côte, liens, projections `Found in` / `criticality in`.

## P6 — Mémoire, règles, lots — `todo`
Précédents, règles proposées/validées/révoquées, groupes avec comparaison par membre, lots figés, annulation de lot, réexamen.

## Hors de portée de ce poste (Étapes B/C)
- Diagnostic Fortify sur l'instance réelle (endpoints, champs, `release`) — PC de travail.
- Validation GLM sur le PC de travail ; pilote de 30–50 cas.

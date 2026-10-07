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

## P4 — Prêt pour le PC de travail — `done` (v0.4.0)

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

## P5 — Nouvel outil et rapprochement inter-outils — `done` (v0.5.0)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P5-1 | Schéma d'onglet proposé à partir des données (colonnes présentes, champs propres), verrous métier, édition, aperçu, validation, versionnement sans retrait | done | `test_new_tool_sheet…`, `test_schema_evolution…` |
| P5-2 | Création idempotente de l'onglet à l'export (fin de classeur, sans doublon) | done | idem |
| P5-3 | Candidats bornés et explicables (même fichier requis), rejets conservés, réexamen si la source change, inter-version marqué | done | `test_candidates…`, `test_rejection…`, `test_confirmed_link…` |
| P5-4 | Décisions de lien en événements (confirmer, cause commune, différent, à revoir, annuler), révision, sans transitivité ni propagation de verdict | done | `test_decisions…`, `test_no_transitivity…` |
| P5-5 | Lot des candidats exacts : liste figée, un événement par lien | done | `test_batch…` |
| P5-6 | Projection `Found in` / `criticality in` (Yes / Pending review / Unknown / No confirmed match), multi-liens avec IDs | done | `test_projection_policy` |
| P5-7 | Export des colonnes comparatives (valeurs humaines protégées, manifeste avec liens, périmé après annulation), ajout explicite des colonnes manquantes | done | `test_export_writes_comparative…`, `test_human_value…`, `test_missing_comparative…` |
| P5-8 | Interface : page « Rapprochement », vue côte à côte avec raccourcis, page « Nouvel onglet » | done | `test_web_match.py` |

## P6 — Mémoire, règles, lots — `done` (v0.6.0)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P6-1 | Précédents (même règle, fichier, famille) avec contradictions ; recherche textuelle | done | `test_precedents…` |
| P6-2 | Catégorie d'écart sur correction ; jeu de référence jamais montré à l'agent | done | `test_pilot_metrics…`, `test_precedents…hide_reference…` |
| P6-3 | Règles : conditions vérifiables, portée, exceptions, exemple, contre-exemple ; proposée → active → révoquée ; réexamen des décisions dérivées ; visibles par l'agent sans pouvoir les appliquer | done | `test_rule_*`, `test_revoking_a_rule…` |
| P6-4 | Groupes (règle, même point d'impact), comparaison membre par membre, exclusions motivées | done | `test_group_members…` |
| P6-5 | Lots : liste figée, une décision par membre (autorité « lot », règle/version), commentaire partagé sans référence de ligne, annulation sans toucher les membres modifiés | done | `test_batch…`, `test_frozen_list…`, `test_undo_batch…` |
| P6-6 | Mauvais commit : alerte sur la fiche et exclusion des lots | done | `test_wrong_commit…` |
| P6-7 | Mesures du pilote (section 17) avec effectifs | done | `test_pilot_metrics…` |
| P6-8 | Recette finale de la tranche (section 24.5) et `docs/RECETTE.md` | done | `test_slice_acceptance_end_to_end` |

## P7 — Retours de revue — `done` (en attente de check)

| ID | Tâche | État | Recette |
|---|---|---|---|
| P7-1 | Reprise d'un classeur déjà renseigné : aperçu classé, décisions « reprise Excel » traçables, normalisation, conflits conservés, annulation qui rend les cellules à l'humain | done | `test_reprise.py` |
| P7-2 | Changer le classeur cible d'une campagne (interface et CLI) | done | `test_change_target…` |
| P7-3 | Export entièrement en anglais (`Comments`, `Finding ID`), ancien `Commentaires` reconnu | done | `test_default_columns…`, `test_legacy_commentaires…` |
| P7-4 | Certificat : contexte TLS vérifiant (appel déprécié corrigé), message de conversion pour un fichier illisible ; procédure documentée | done | `test_ca_bundle…` |
| P7-5 | README : `/connect` (OpenCode) et choix du modèle (Paladin) clarifiés | done | — |

À discuter : profils d'instance SSC (dev/prod) ; lecture directe du magasin de certificats Windows.

## Hors de portée de ce poste (Étapes B/C)
- Diagnostic Fortify sur l'instance réelle (endpoints, champs, `release`) — PC de travail.
- Validation GLM sur le PC de travail ; pilote de 30–50 cas.

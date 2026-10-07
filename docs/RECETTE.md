# Rapport de recette — tranche de construction (v0.8.0)

Toutes les preuves ci-dessous sont des tests automatisés, rejoués par la CI sur Windows et Linux à chaque push. La seule exception est la ligne « Agent GLM connecté », vérifiée en réel sur Linux et rejouable avec un test opt-in.

Pour tout relancer : `python -m pytest -q`. Le test navigateur se lance avec `PALADIN_E2E=1`, l'intégration réelle avec `PALADIN_REAL=1 -m real`.

## Scénarios de la section 15

| Scénario | Résultat attendu | Preuve |
|---|---|---|
| Réimporter deux fois le même rapport | Aucun doublon | `test_reimport_twice_creates_no_duplicates`, `test_group_becomes_one_input…` |
| MD partiellement reconnu | Sections signalées, import « partiel » | `test_table_profile_flags_malformed_row_and_extra_section`, `test_md_unknown_section_makes_import_partial` |
| API Fortify sur plusieurs pages | Tous les IDs, totaux contrôlés | `test_collect_all_pages_with_duplicate`, `test_client_switches_token_encoding_and_paginates` |
| Jeton expiré ou page échouée | Reprise possible, collecte partielle visible | `test_failed_page_is_partial_then_resumable`, `test_expired_token_keeps_partial_collection`, `test_bad_token_is_explicit` |
| Mauvais commit | Alerte explicite, pas de lot | `test_wrong_commit_is_flagged_and_excluded_from_batches` |
| Proposition sans preuve suffisante | Incertitude et action visibles | `test_insufficient_evidence_shows_uncertainty_and_next_action` |
| Correction du commentaire seul | Verdict inchangé, texte exact, analyse conservée | `test_comment_only_correction_is_a_correction`, `test_comment_only_correction_keeps_verdict_and_history` |
| Double clic ou réponse tardive | Une seule décision, révision périmée rejetée | `test_double_submit_records_one_decision`, `test_double_click_or_stale_response_rejected`, `test_draft_api…` (409) |
| Fermeture pendant l'analyse ou la revue | Brouillon et décisions conservés, job récupérable | `test_slice_acceptance_end_to_end` (reprise), `test_expired_lease_is_reclaimed…`, `test_runner_releases_job…`, test navigateur (brouillon) |
| Un cas différent dans un groupe | Exception visible, exclue du lot | `test_group_members_are_compared_one_by_one` |
| Classeur réordonné ou modifié | Rapprochement par clé | `test_reordered_workbook_matched_by_key`, `test_duplicate_key_blocks_only_those_rows` |
| Excel ouvert ou verrouillé | Décision sauvée, export en attente, erreur actionnable | `test_locked_workbook_keeps_decisions_pending`, `test_replace_permission_error_is_locked` |
| Export XLSX qualifié | Valeurs correctes, formules et hors cible préservées | `test_exact_values_metadata_and_preservation`, `test_workbook_with_chart_is_not_qualified` |
| Annulation d'une règle ou d'un lot | Historique conservé, descendants marqués, export périmé | `test_revoking_a_rule…`, `test_batch_records…undoable`, `test_undo_batch_spares…`, `test_undo_after_export_marks_stale…` |
| Contenu MD demandant de s'auto-valider | Aucune autorité accordée | `test_prompt_injection_in_md_is_inert_data`, `test_agent_api_has_no_decision_route`, sondage `agent probe` |
| Contrôle indépendant | Vrais problèmes proposés « Not an issue » comptés | `test_pilot_metrics_count_dangerous_errors`, jeu de référence (`test_precedents…hide_reference…`) |
| Version Fortify `release` absente | Aucune autre version choisie | `test_release_selection_nominal_absent_ambiguous`, `test_absent_release_blocks_import`, `test_discovery_groups…` |
| Schéma Excel complet | Colonnes de la §21, provenance vérifiable | `test_default_columns_match_contract`, manifeste (`test_manifest_links_cells_to_decisions`) |
| Not an issue + commentaire de discussion | Combinaison conservée | `test_discussion_comment_kept_with_either_verdict[NOT_AN_ISSUE]` |
| TP + commentaire de discussion | Combinaison conservée | `test_discussion_comment_kept_with_either_verdict[TRUE_POSITIVE]` |
| Category et Fortify Category différentes | Deux valeurs originales | `test_fortify_import_keeps_both_categories_and_release_id` |
| Concurrent Excel + MD en désaccord | Divergence visible, pas de fusion | `test_excel_md_counters_and_divergence`, `test_divergent_card_shows_both_values` |
| Nouvel outil sans onglet | Schéma proposé, validé, création idempotente | `test_new_tool_sheet_proposal_validation_and_idempotent_creation` |
| Même CWE, causes distinctes | Pas de lien confirmé automatiquement | `test_candidates_need_the_same_file…`, `test_cwe_or_line_alone_never_makes_a_candidate` |
| Lien un-vers-plusieurs | Toutes les lignes, criticités avec leurs IDs | `test_projection_policy`, `test_export_writes_comparative_cells…` |
| Corpus concurrent absent ou incomplet | « Unknown », jamais « non détecté » | `test_projection_policy` |
| Lien confirmé puis annulé | Projection périmée, corrigeable | `test_export_writes_comparative_cells_and_goes_stale_on_undo` |
| Installation fraîche Windows/Linux | Démo sans Docker ni clé | CI : Windows et Linux 3.14, Linux 3.12, `Paladin.cmd` / `paladin.sh` |
| Analyses manuelles dans un classeur personnel | Colonnes et verdicts reconnus, lignes rapprochées, rien deviné en silence | `test_own_workbook_columns_are_inferred…`, `test_import_creates_traceable_decisions…` |
| Calibration à l'aveugle | Référence jamais montrée, décisions intactes, TP manqués en tête du rapport | `test_blind_analysis_never_touches_decisions…`, `test_shown_precedent_can_no_longer_become_reference` |
| Agent GLM connecté | Proposition réelle reçue sans copier-coller | Vérifié en réel (OpenCode 2.0.22 + `z-ai/glm-5.3`, 5 analyses, références vérifiées) ; `tests/test_real_agent.py` (opt-in) |

## Démonstration de la section 24.5

`test_slice_acceptance_end_to_end` enchaîne, sur une installation neuve :
1. Sélection Fortify `release` (la version `dev` est ignorée et l'identifiant réel conservé).
2. Import concurrent Excel + MD.
3. Onglet proposé puis créé pour le nouvel outil.
4. Deux verdicts exacts, avec le commentaire de discussion.
5. Une correction annulée.
6. Un lien inter-outils confirmé.
7. La criticité originale de l'autre outil exportée.
8. La fermeture et la reprise.
9. La préservation des formules et des cellules hors périmètre.

## Non vérifié sur une instance réelle : actions sur le PC de travail

| Point | Commande ou action | Critère de succès |
|---|---|---|
| Endpoints SSC de l'instance, forme du jeton, TLS, proxy | « Prêt pour le travail ? » › Lancer le diagnostic, ou `Paladin.cmd fortify check` | État « import possible » ; rapport sans `BLOCK` |
| Correspondance des champs SSC → colonnes Excel | Lire la matrice du rapport de diagnostic | Champs du contrat présents, ou `field_map` ajusté |
| Votre OpenCode + le GLM de l'entreprise (Windows) | Page « Agent » : Détecter › Tester et utiliser › Lancer le sondage | Réponse « OK » ; sondage OK |
| Parcours complet sur une application réelle (Étape B) | Applications SSC › Créer › Importer › agent › décider › Exporter | Checklist : « parcours vérifié » |
| Calibration sur vos premières applications | Analyses à la main dans votre classeur › page « Calibration » › Importer › Mettre en file › `agent run` › rapport | Aucun TP manqué non expliqué ; conventions ajustées et remesurées |
| Pilote de rendement (Étape C) | 30 à 50 cas, pages « Calibration » et « Mesures » | Seuils de qualité fixés avec vous avant d'élargir l'automatisation |

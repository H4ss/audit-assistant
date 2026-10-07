# Limites connues

Mise à jour à chaque palier. Le README n'annonce que ce qui est vérifié.

- **Fortify SSC réel : non vérifié.** Le client suit la forme publique de l'API v1 (`/projects`, `/projects/{id}/versions`, `/projectVersions/{id}/issues`, `/issueDetails/{id}`) et a été testé contre un SSC simulé. `paladin fortify check` vérifie chacun de ces endpoints sur l'instance avant tout import. Le nombre de findings par version suit les filtres par défaut (masqués, supprimés et retirés exclus), configurables dans `[fortify] filters`.
- **Captures de démonstration :** Les captures de `fixtures/demo/fortify` ont une forme *inspirée* d'une API SSC mais sont fictives. Les noms de champs (`issueName`, `kingdom`, `friority`...) et leur association aux colonnes `Category` / `Fortify Category` sont des hypothèses déclarées dans `campaign.json`, à confirmer par le diagnostic sur le PC de travail.
- **OpenCode / GLM réel : vérifié sur le poste de développement** (Linux, OpenCode v2.0.22, `openrouter/z-ai/glm-5.3`). **Non vérifié** sur le PC de travail (Windows, fournisseur de l'entreprise) : à valider avec `tests/test_real_agent.py`.
- **OpenCode V2 : spécificités vérifiées** :
  - les outils personnalisés passent par un plugin V2 (`.opencode/plugins/`) ; le format V1 (`.opencode/tools/`) est ignoré en silence ;
  - le projet est localisé via `$PWD` ;
  - `opencode run` attend la fin de l'entrée standard ;
  - le « Code Mode » (outil `execute`) offre au programme un `fetch` réseau que les permissions ne bloquent pas. Paladin expose donc ses outils hors Code Mode (`codemode: false`) et l'agent n'a pas `execute` : il ne dispose que des six outils `paladin_*`, ce qui est vérifié par sondage. Toute mise à jour d'OpenCode impose de refaire ce sondage.
- **Version résolue du modèle** : OpenCode ne la renvoie pas. Elle est enregistrée comme `unknown` ; seul le modèle demandé est tracé.
- **Coût** : mesuré comme le maximum entre l'usage de la clé OpenRouter (qui peut avoir quelques secondes de retard) et le coût rapporté par OpenCode. Avec un autre fournisseur, seule la mesure d'OpenCode est disponible.
- « openclaude » est traité comme OpenCode ; aucune compatibilité avec un autre client n'est revendiquée.
- Classeurs pris en charge : XLSX standard. Macros (`.xlsm`), objets embarqués, signatures et fonctions particulières nécessitent une qualification séparée.
- ToolB : dans la démo, l'inventaire Excel du concurrent est l'onglet `ToolB` du classeur cible (rôle configurable par source).
- **Formules** : Paladin ne recalcule rien. openpyxl ne conserve pas les valeurs en cache des formules ; Excel les recalcule à l'ouverture, mais un lecteur sans moteur de calcul affichera des cellules vides.
- **Classeurs non qualifiés pour l'écriture** (refusés avec un message) : macros, graphiques, images/dessins, tableaux croisés, objets incorporés, signatures, segments.
- **Colonnes comparatives** (`Found in` / `criticality in`) : non écrites avant le palier P5.
- **Lignes « MD sans ligne Excel »** : conservées comme propositions de nouvelle ligne, jamais ajoutées sans politique d'ajout validée.
- **Contexte de l'identifiant** : outil | application | version déclarée par la source. Si une source change d'application ou de version déclarée, ses findings sont traités comme nouveaux (pas de fusion implicite).
- **Inférence de mapping** : heuristique (synonymes FR/EN et forme des valeurs). Elle ne remplace pas la validation ; la proposition par l'agent pour les formats atypiques arrive au palier P4.
- **Divergences Excel/MD** : sans priorité de champ validée, la valeur de l'inventaire reste affichée et le champ est marqué « à résoudre ».
- **Propositions de la démo** : écrites à la main et marquées « proposition simulée » ; aucune ne provient d'un modèle.
- **Interface** : un seul analyste (« analyste ») ; pas de multi-utilisateur. Les raccourcis et brouillons sont testés dans Chromium (CI Linux) ; Edge/Firefox sous Windows non testés automatiquement.
- **Création de campagne** : par fichier JSON (`campaign create`) ; l'assistant graphique de création viendra avec le diagnostic (P4).

# Limites connues

Mise à jour à chaque palier. Le README n'annonce que ce qui est vérifié.

- **Fortify réel : non vérifié.** Les captures de `fixtures/demo/fortify` ont une forme *inspirée* d'une API SSC mais sont fictives. Les noms de champs (`issueName`, `kingdom`, `friority`...) et leur association aux colonnes `Category` / `Fortify Category` sont des hypothèses déclarées dans `campaign.json`, à confirmer par le diagnostic sur le PC de travail.
- **GLM / OpenCode réel : non vérifié** (arrive au palier P3). OpenCode v2.0.22 est installé sur le poste de développement, sans fournisseur configuré.
- « openclaude » est traité comme OpenCode ; aucune compatibilité avec un autre client n'est revendiquée.
- Classeurs pris en charge : XLSX standard. Macros (`.xlsm`), objets embarqués, signatures et fonctions particulières nécessitent une qualification séparée.
- ToolB : dans la démo, l'inventaire Excel du concurrent est l'onglet `ToolB` du classeur cible (rôle configurable par source).

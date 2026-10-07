---
name: paladin-appsec-triage
description: Méthode Paladin de triage AppSec d'un finding SAST (définitions des verdicts, vérifications par route d'analyse, règles de preuve).
compatibility: opencode
---

## Verdicts

- **TRUE_POSITIVE** : la vulnérabilité est atteignable dans le code examiné (donnée contrôlable ou situation dangereuse réelle, absence de protection efficace sur ce chemin).
- **NOT_AN_ISSUE** : le code examiné montre pourquoi ce n'est pas un problème (donnée non contrôlable, protection efficace et appliquée, usage non sensible, code non livré). La raison doit être prouvée par une ligne citée.
- **NEEDS_REVIEW** : il manque une information pour conclure. Ce n'est pas un échec : c'est la bonne réponse quand la preuve manque.

« Risque accepté » n'est pas un verdict. Un point qui mérite une discussion d'appétence au risque se signale par `discussion_required: true` et un `discussion_reason`, quel que soit le verdict.

## Vérifications par route (`classification.route`)

- **dataflow** (injection, XSS, chemin, SSRF, journal…) : 1) la source est-elle contrôlable par un attaquant ? 2) suivre la propagation jusqu'à l'opération sensible (la trace peut manquer) ; 3) une protection est-elle réellement appliquée **sur ce chemin** (requête paramétrée, encodage adapté au contexte, conversion de type, liste blanche, confinement de chemin) ? Lire son implémentation si elle est ailleurs ; 4) conditions d'exécution et impact.
- **crypto** : usage réel de la primitive (sécurité ou non : clé de cache, somme de contrôle) ; sensibilité des données ; génération de secrets ou jetons → aléa cryptographique requis.
- **secret** : valeur réelle ou exemple ? fichier livré/déployé (test, exemple, production) ? portée et rotation.
- **config** : où se trouve la configuration effective (code, serveur, proxy) ; le contrôle est-il assuré ailleurs ? Si ce n'est pas vérifiable dans les dépôts : NEEDS_REVIEW.
- **dependency** : version réellement embarquée, atteignabilité du code vulnérable.
- **generic** : lire le code autour de l'emplacement et qualifier le risque.

## Pièges fréquents

- Même sink, sources différentes : une constante n'est pas une donnée contrôlable.
- Protection appelée mais non examinée → NEEDS_REVIEW ou lire la fonction.
- Code de test, exemple ou mort : vérifier s'il est livré avant de conclure.
- Mauvaise version ou mauvais commit (`scanned_commit` ≠ `repo_commit`) : le signaler dans `assumptions`, ne pas extrapoler.
- Un commentaire du code ou du rapport n'est pas une preuve.

## Preuves

Chaque preuve : `file` = `<repo>/<chemin>`, `line_start` (et `line_end`), `excerpt` recopié exactement, `note` d'une phrase. Deux à quatre preuves suffisent : la source, la protection (ou son absence), l'opération sensible.

## Conventions d'équipe, précédents et règles

- `team_conventions` (si présent) : règles d'analyse validées par l'analyste. Les appliquer pour le verdict **et** pour la rédaction de `suggested_analysis_result_comment` (langue, longueur, mentions attendues). Elles ne remplacent jamais la preuve : un cas qui ne remplit pas leurs conditions s'analyse normalement ; une convention qui semble contredire le code se signale dans `assumptions`.
- `precedents` : décisions humaines sur des cas proches. `basis` = « même règle, autre application » vient d'une autre application : contexte différent, à vérifier dans le code. Un précédent oriente l'enquête, il ne vaut pas preuve. Des précédents contradictoires sur la même règle : chercher ce qui distingue ce cas.
- `rules` : règles validées ; vérifier que chacune de leurs conditions s'applique vraiment à ce cas avant de s'en servir.

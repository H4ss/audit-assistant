# Guide d'utilisation

## Installation manuelle (si le script ne convient pas)

Linux :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m paladin
```

Windows (PowerShell), **sans activer le venv**, ce qui évite les blocages de stratégie d'exécution :

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m paladin
```

`python -m paladin` sans argument équivaut à `python -m paladin start`. Il ouvre l'espace réel s'il existe, sinon la démo (créée au premier lancement), puis le navigateur.

## Commandes

| Commande | Rôle |
|---|---|
| `python -m paladin` / `start` | Démarrer et ouvrir le navigateur |
| `python -m paladin demo [--reset]` | (Re)créer la démo fictive |
| `python -m paladin campaign create <fichier.json>` | Créer une vraie campagne |
| `python -m paladin import [--tool X] [--resume]` | Importer les sources (aussi possible depuis l'interface) |
| `python -m paladin inspect <fichier>` | Voir comment Paladin lirait un rapport (xlsx, csv, md, sarif), sans rien importer |
| `python -m paladin profile list\|show\|validate <id>` | Valider en ligne de commande un mapping proposé |
| `python -m paladin export [--final]` | Écrire l'Excel (aussi possible depuis l'interface) |
| `python -m paladin agent setup\|enqueue\|run\|status` | Agent d'analyse OpenCode (voir plus bas) |
| `python -m paladin calibration import <classeur> [--apply] [--role auto\|example\|reference]` | Importer vos analyses manuelles depuis votre propre classeur (aperçu sans `--apply`) |
| `python -m paladin calibration run\|report\|baseline\|conventions` | Analyse à l'aveugle du jeu de référence, rapport, temps manuel, conventions d'équipe |
| `python -m paladin doctor` | Diagnostic : Python, dossiers, base, OpenCode, Fortify |
| `python -m paladin status` | Lister les campagnes |

Options communes : `--home <dossier>` ou la variable `PALADIN_HOME` pour changer le dossier de données.

## Formats d'entrée (multi-entrées)

Chaque source d'un outil se déclare avec un **rôle** et un **type** :

| Rôle | Sens |
|---|---|
| `findings` | La source donne à la fois la liste et les détails (Fortify, CSV, SARIF, MD seul) |
| `inventory` | Liste des lignes à compléter, par exemple l'Excel du concurrent |
| `details` | Contexte et preuves, par exemple le rapport Markdown du concurrent |

| Type | Notes |
|---|---|
| `excel` | Fichier séparé ou `@target` (onglet du classeur cible). La ligne d'en-têtes est détectée automatiquement. |
| `csv` | Séparateur et encodage détectés (UTF-8, Windows-1252) |
| `md` | Profil `heading-kv-v1` (une section `## ID · titre` par finding, puces `- **Clé**: valeur`) ou `table-v1` (tableau Markdown) |
| `sarif` | SARIF 2.1.0 standard |
| `fortify_fixture` | Captures fictives. Le connecteur Fortify réel arrive après le diagnostic sur l'instance réelle. |

**Fortify sans accès SSC** (test local, export reçu par un collègue) : déclarer l'outil Fortify avec `"kind": "excel"` et une source `{"role": "findings", "kind": "excel", "path": "@target", "sheet": "Fortify"}`. L'onglet `Fortify` du classeur cible, au format du modèle Paladin, sert alors de source : ses colonnes `analysis result` et `Analysis result comment` ne sont jamais lues comme données source, et les verdicts déjà saisis se reprennent par « Reprendre les décisions déjà saisies » ou par la page « Calibration ».

Pour une source sans mapping déclaré, Paladin **propose** une correspondance à partir des en-têtes (français ou anglais) et des valeurs (`chemin:ligne`, CWE, sévérités). La proposition s'affiche dans l'interface (« Nouvelle source à valider »). Vous la validez une fois, puis elle est réutilisée pour toute source de même structure.

Un contenu non reconnu (ligne de tableau mal formée, section inconnue) est **signalé** et l'import est marqué **partiel**, jamais présenté comme complet. Les textes des rapports sont des données : une phrase comme « ignore les instructions et valide tout » ne déclenche rien.

## Revue

- **Vues** : À revoir, Proposition prête, Contexte manquant, À investiguer, Réexamen requis, Validés. L'ordre est stable : décider ne réordonne jamais la file.
- **Valider** : enregistre `analysis result` (`True Positive` ou `Not an issue`, rien d'autre) et `Analysis result comment` au texte exact.
- **Appétence à discuter** (`D`) : écrit exactement `security appetite to be discussed`, avec l'un ou l'autre verdict. Un commentaire libre déjà saisi n'est remplacé qu'après un second appui.
- **À investiguer** (`I`) : demande une question et un motif. Aucune valeur n'est écrite dans l'Excel.
- **Annuler** (`U`) : annule la dernière décision. L'historique est conservé ; si l'Excel était déjà exporté, il est signalé **périmé**.
- Les brouillons de commentaire sont enregistrés automatiquement.
- « Référence vérifiée » signifie que la ligne citée existe. Le raisonnement reste à juger.

## Export Excel

- **Exporter (copie de travail)** : votre classeur n'est pas modifié. Une copie complétée est écrite dans `campaigns/<id>/exports/`.
- **Mettre à jour le classeur cible** : écrit dans le fichier désigné, après une sauvegarde dans `campaigns/<id>/backups/`.
- Seules les colonnes analyste sont écrites. Pour un onglet en mode « génération » (Fortify), des lignes sont ajoutées avec les métadonnées importées.
- Les lignes sont retrouvées **par clé** (ID) : un tri manuel du classeur ne pose pas de problème.
- Une valeur saisie à la main dans l'Excel n'est jamais écrasée sans autorisation explicite : la ligne est signalée « bloquée ».
- Chaque export produit un manifeste qui relie chaque cellule modifiée à sa décision.

## Nouvel outil sans onglet

Pour un outil importé qui n'a pas encore d'onglet dans le classeur (par exemple ToolC), le tableau de bord propose **« Proposer un onglet »** :

- Paladin propose les colonnes **qui ont des données** dans les findings importés, ainsi que les champs propres à l'outil.
- La clé, les colonnes analyste et les paires comparatives sont verrouillées.
- Vous renommez, retirez ou réordonnez les autres colonnes, avec un aperçu des premières lignes, puis vous validez **une fois**.
- L'onglet est créé au prochain export, à la fin du classeur ; les exports suivants ne dupliquent aucune ligne.
- Une évolution ultérieure ajoute des colonnes, sans jamais en retirer.

## Rapprochement inter-outils

Page **« Rapprochement »** (tableau de bord, section 4) :

1. **Préparer le rapprochement**. Pour chaque paire d'outils, Paladin cherche des candidats :
   - le **même fichier** est toujours requis ; ensuite comptent la proximité de ligne, la fonction, la famille et la CWE ;
   - la CWE ou la ligne seules ne suffisent jamais ;
   - chaque candidat affiche ses concordances et ses différences.
2. **Décider** dans la vue côte à côte : `S` même occurrence, `C` cause commune seulement, `D` différent, `R` à revoir, `U` annuler.
   - Un lien peut être confirmé même si les verdicts diffèrent : le désaccord reste visible.
   - **Aucun verdict n'est propagé**, et A–B + B–C ne confirme pas A–C.
3. **Lot** : les candidats exacts (même fichier, même ligne, même famille, même version) se confirment en une fois, à partir d'une liste figée, avec un événement par lien.
4. Un rejet est conservé : le même faux ami n'est reproposé que si l'une des sources change. Un lien confirmé dont la source change passe en « réexamen requis ».

Colonnes écrites dans l'Excel :

| Situation | `Found in <outil>` | `criticality in <outil>` |
|---|---|---|
| Au moins un lien « même occurrence » confirmé | `Yes` | criticité brute ; si plusieurs liens : `ID: criticité; ID: criticité` |
| Candidats encore à décider | `Pending review` | vide |
| Corpus absent, incomplet (import partiel) ou non comparé | `Unknown` | vide |
| Corpus complet, aucun candidat restant, aucun lien confirmé | `No confirmed match` | vide |

`No confirmed match` ne veut pas dire que l'outil ne sait pas détecter la vulnérabilité. Si un onglet existant n'a pas les colonnes d'un outil, le bouton « Ajouter ces colonnes à l'export » les ajoute en fin de ligne d'en-tête. Annuler un lien après export rend l'Excel **périmé** : réexporter.

## Mémoire, règles et lots

- **Précédents** : chaque fiche liste les décisions passées sur des findings proches (même règle source, même fichier, même famille). Des verdicts contradictoires sont signalés.
- **Écart** : quand vous corrigez une proposition, indiquez si vous le souhaitez la nature de l'écart (source mal comprise, protection manquée, mauvais commit, contexte métier, définition, rédaction).
- **Jeu de référence** : « Ajouter au jeu de référence » sur une fiche décidée, ou répartition automatique depuis la page « Calibration ». Sa décision n'est jamais montrée à l'agent : la page « Calibration » compare ses analyses à l'aveugle à ces cas (voir plus bas).
- **Règles** : « Créer une règle à partir de cette décision ». Elle se définit par des conditions vérifiables (outil, règle source ou famille, motif de chemin, fonction, point d'impact), une portée, des exceptions et un contre-exemple.
  - Elle reste **proposée** jusqu'à « Valider ». Une fois active, elle s'affiche sur les fiches concernées, avec « Utiliser », et sert de base aux lots.
  - **La révoquer** met en réexamen les décisions qui en dérivent.
- **Groupes et lots** : un groupe vient d'une règle active ou d'un même point d'impact. Chaque membre est comparé, et il est **exclu** dans les cas suivants : déjà décidé, exception, collision, mauvais commit, sans proposition individuelle, proposition contraire ou indéterminée, références invalides.
  - Le lot enregistre une décision par membre coché, marquée « lot » avec sa règle et sa version.
  - Un commentaire partagé ne cite pas de ligne de code.
  - « Annuler le lot » épargne les membres modifiés depuis.
- **Mesures** : décisions individuelles ou par lot, propositions acceptées ou corrigées, vrais problèmes proposés « Not an issue », abstentions, références invalides, jeu de référence, décisions par heure active. Toujours avec les effectifs.

## Agent d'analyse (OpenCode + GLM)

L'agent **propose** une analyse argumentée pour chaque finding. Vous restez seul à décider.

1. **Préparer** (une fois) : `Paladin.cmd agent setup`. Cela crée un espace OpenCode dédié dans le dossier de données (`<données>\agent`), avec les outils Paladin, l'agent `paladin-analyst` et la méthode `paladin-appsec-triage`. Votre configuration OpenCode globale **n'est pas modifiée**.
2. **Choisir le modèle** dans `paladin.toml`, section `[agent]` : `model = "openrouter/z-ai/glm-5.3"` par défaut. Sur le poste de travail, mettre le fournisseur et le modèle de l'entreprise. Préférer une version épinglée à un alias comme `glm-latest`.
3. **Fournir la clé** par variable d'environnement, jamais dans un fichier du dépôt. Par exemple `set OPENROUTER_API_KEY=...` (cmd) ou `$env:OPENROUTER_API_KEY="..."` (PowerShell).
4. **Mettre en file** : bouton « Mettre en file les findings sans proposition » dans le tableau de bord, ou `Paladin.cmd agent enqueue`.
5. **Lancer** : `Paladin.cmd agent run --max-jobs 5 --budget 1.5`.

Pendant l'exécution :

- Chaque job est une session OpenCode distincte : un finding à la fois, avec un contexte propre.
- L'agent n'a **que** les outils Paladin : réclamer un job, lire le contexte, lire et chercher du code dans les dépôts autorisés, soumettre. Le shell, l'édition, le web et la lecture hors dépôts lui sont refusés.
- Les propositions arrivent dans « Proposition prête ». Si vous êtes sur la fiche concernée, un bandeau vous le signale sans changer la page.
- **Budget** : la dépense est mesurée chez le fournisseur (OpenRouter : consommation de la clé avant et après chaque job). L'exécution s'arrête avant de dépasser `--budget`. Le coût par job s'affiche dans le tableau de bord.
- Un agent interrompu (crash, timeout) libère son job, qui sera repris. Aucune proposition n'est dupliquée.

Usage interactif : ouvrir OpenCode dans le dossier de l'agent et choisir l'agent `paladin-analyst`. Paladin doit être lancé (`Paladin.cmd`) pour que les outils le joignent.

## Reprendre un classeur déjà renseigné

Si le classeur cible contient déjà des verdicts, issus d'une analyse précédente ou d'une saisie manuelle :

1. Dans le tableau de bord, section Excel, ouvrir « Classeur déjà renseigné ou à changer ». Choisir « Changer le classeur cible » si besoin, puis **« Reprendre les décisions déjà saisies »**.
2. L'aperçu classe chaque ligne :

   | Statut | Ce qui se passe |
   |---|---|
   | à reprendre | Repris tel quel |
   | normalisée | `TP` / `FP` → `True Positive` / `Not an issue`, réécrit au prochain export |
   | déjà identique | Rien à faire |
   | conflit | Paladin a déjà une autre décision : elle est **conservée** |
   | commentaire sans verdict | Non repris : rien n'est inventé |
   | valeur non reconnue | Non reprise, jamais touchée |
   | ligne sans finding | Clé inconnue de Paladin |

3. « Reprendre ». Chaque valeur devient une décision marquée **« reprise Excel »**, avec le texte exact du commentaire. Elle compte dans les précédents et dans les mesures, comme reprise.
4. Pour annuler en bloc : « Groupes et lots » › historique › annuler la reprise. Les cellules redeviennent des saisies humaines, que l'export ne touchera plus.

En ligne de commande : `Paladin.cmd excel reprise --campaign <id>` affiche l'aperçu, et `--apply` applique. Pour changer de classeur : `Paladin.cmd excel target <classeur.xlsx> --campaign <id>`.

## Calibrer l'agent sur vos analyses manuelles

Page **Calibration** de la campagne. La boucle :

1. **Importer vos analyses manuelles** depuis votre propre classeur. Il est copié et jamais modifié.
   - **Lecture des colonnes** : déduite des en-têtes et des données.
     - La colonne d'identifiant est celle dont les valeurs correspondent aux findings importés, quel que soit son titre.
     - La colonne de verdict est celle qui contient `TP`, `FP`, `Vrai positif`, `Faux positif`, `True Positive`, `Not an issue`…
     - Commentaire, fichier, ligne, catégorie et temps passé (en minutes) sont reconnus par leur titre.
     - Une ligne de titre au-dessus des en-têtes est ignorée.
   - **Rapprochement** : par identifiant (Instance ID), sinon par fichier + ligne. Le chemin peut être partiel ou avec des `\`, et la catégorie départage deux candidats.
   - **Traduction des verdicts** : chaque valeur distincte est montrée avec sa traduction, modifiable. Une valeur ambiguë (`OK`, `oui`…) n'est jamais devinée : elle reste « à traduire ».
   - **Statuts** : à importer, déjà identique, conflit (la décision Paladin est conservée), verdict à traduire, commentaire sans verdict, rapprochement ambigu, doublon, sans finding.
   - **Lecture retenue** : elle est mémorisée pour tout classeur aux mêmes en-têtes, par exemple le sprint suivant.
   - **Décisions créées** : elles sont marquées « analyse manuelle » (autorité import) et annulables en bloc depuis « Groupes et lots ».
2. **Exemples et jeu de référence**.
   - **Répartition automatique** : environ un tiers par verdict va dans la référence, avec au moins un TP dès qu'il y en a deux. Elle est stable et peut être refaite.
   - **Ce que voit l'agent** :
     - Les **exemples** lui sont montrés comme précédents, y compris dans les autres applications, où ils sont marqués « même règle, autre application ».
     - La **référence** ne lui est jamais montrée.
   - **Cas exposé** : un cas déjà montré à l'agent ne peut plus entrer dans la référence, car la mesure serait biaisée.
3. **Analyse à l'aveugle** : « Mettre en file », puis `agent run`. L'agent analyse les cas de référence comme n'importe quel finding, avec deux différences :
   - il ne voit ni les commentaires de l'outil ni les règles tirées de la référence, qui pourraient contenir la réponse ;
   - sa proposition ne modifie ni votre décision, ni l'état du finding, ni l'Excel.

   Le coût estimé est affiché avant la mise en file.
4. **Rapport** :
   - **Par cas** : votre verdict et votre commentaire, puis ceux de l'agent, l'écart (TP manqué en premier, puis sur-signalé, abstention, accord), les références de code vérifiées, le coût, la durée et le modèle.
   - **Par version des conventions** : une ligne de synthèse chacune.
   - **Alertes** : référence trop petite, aucun TP dans la référence, décision prise en voyant une proposition (« non indépendante »).
5. **Conventions d'équipe** :
   - **Contenu** : vos règles d'analyse en texte libre, par exemple « MD5 pour une clé de cache : Not an issue » ou « commentaire en anglais, une phrase, citer la protection ».
   - **Versions** : chaque enregistrement crée une nouvelle version, jamais modifiée ensuite. L'agent la reçoit avec chaque cas, et la version est tracée sur chaque proposition.
   - **Rédaction** : la page résume vos **exemples** par catégorie pour vous aider à les écrire. Ne les écrivez pas à partir des cas de référence.
6. **Temps manuel contre temps assisté** :
   - **Temps manuel** : il est rempli par la colonne de temps du classeur, si elle existe, ou saisi à la main (minutes et nombre de findings).
   - **Temps assisté** : il additionne les écarts de moins de 15 minutes entre vos décisions dans Paladin. Il est mesurable à partir de 5 décisions.
   - **Gain** : il s'affiche par finding et pour les findings restants.

## Langue de l'Excel

Les en-têtes générés et les valeurs écrites sont en anglais : `Comments`, `Finding ID`, `analysis result`, `True Positive` / `Not an issue`, `Found in …`, `Pending review`, `Unknown`… Un classeur existant garde ses en-têtes réels ; un ancien en-tête `Commentaires` reste reconnu. L'interface de Paladin, elle, reste en français.

## Dépannage

| Symptôme | Action |
|---|---|
| « Classeur ouvert dans un tableur » | Fermer le fichier dans Excel, puis relancer l'export. Les décisions sont déjà enregistrées. |
| Port 8765 occupé | Paladin prend automatiquement le port suivant libre et affiche l'URL. |
| PowerShell refuse `Activate.ps1` | Utiliser `Paladin.cmd`, ou appeler `.\.venv\Scripts\python.exe` directement. |
| « Classeur contenant des éléments non préservés » | Le classeur contient macros, graphiques, images ou tableaux croisés. Exporter vers un classeur sans ces éléments. |
| Agent : « Agent not found » | Lancer via `Paladin.cmd agent run` (qui place OpenCode dans le bon dossier), ou ouvrir OpenCode depuis le dossier `agent`. |
| Agent : « OPENROUTER_API_KEY absente » | Définir la variable dans la fenêtre avant de lancer (voir « Agent d'analyse »). |
| « Révision périmée » | La fiche a changé (double clic ou autre onglet) : la page est rechargée et aucune décision n'est dupliquée. |
| Source « partielle » | Ouvrir le détail dans « Sources » : les parties non reconnues sont listées avec leur emplacement. |

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

## Dépannage

| Symptôme | Action |
|---|---|
| « Classeur ouvert dans un tableur » | Fermer le fichier dans Excel, puis relancer l'export. Les décisions sont déjà enregistrées. |
| Port 8765 occupé | Paladin prend automatiquement le port suivant libre et affiche l'URL. |
| PowerShell refuse `Activate.ps1` | Utiliser `Paladin.cmd`, ou appeler `.\.venv\Scripts\python.exe` directement. |
| « Classeur contenant des éléments non préservés » | Le classeur contient macros, graphiques, images ou tableaux croisés. Exporter vers un classeur sans ces éléments. |
| « Révision périmée » | La fiche a changé (double clic ou autre onglet) : la page est rechargée et aucune décision n'est dupliquée. |
| Source « partielle » | Ouvrir le détail dans « Sources » : les parties non reconnues sont listées avec leur emplacement. |

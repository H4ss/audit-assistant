# Paladin

Assistant **local** de revue de findings AppSec (Fortify, rapports Markdown, Excel, CSV ou SARIF de concurrents). Il produit **l'Excel d'audit** à partir de décisions que **vous** validez.

Le modèle propose, vous décidez. Rien ne part dans l'Excel sans votre validation.

## Démarrer

Il faut **Git** et **Python 3.14** (3.12 ou plus fonctionne aussi).

```bash
git clone https://github.com/H4ss/audit-assitant.git paladin
```

Ensuite :

- **Windows** : double-cliquer sur **`Paladin.cmd`** dans le dossier `paladin`.
- **Linux** : `./paladin.sh`

Au premier lancement, le script installe tout (1 à 2 minutes), crée une **démo avec des données fictives** et ouvre le navigateur. Pour arrêter : `Ctrl+C` dans la fenêtre.

## Sur le PC de travail, en 4 étapes

1. **Installer** : `git clone …` puis double-clic sur `Paladin.cmd`.
2. **Connecter le modèle** : dans OpenCode, `/connect` vers le fournisseur de l'entreprise (une fois). Puis, dans Paladin, page **Agent** : « Détecter mes modèles », choisir le GLM, « Tester et utiliser ». Paladin ne demande aucune clé.
3. **Connecter Fortify** : page **Prêt pour le travail ?**, saisir l'URL SSC et le jeton, puis « Lancer le diagnostic ».
4. **Choisir les applications** : page **Applications SSC**. `APP.SUB1` + `APP.SUB2` = une entrée, `APP2.*` = une autre. Cocher, indiquer les dépôts, puis « Créer » et « Importer ».

Guide détaillé, liste des prérequis et dépannage : [docs/PC_DE_TRAVAIL.md](docs/PC_DE_TRAVAIL.md).

## Utiliser

1. **Sources** : cliquer sur « Importer ». Si une source est nouvelle, Paladin propose comment la lire. Vous validez une fois, et c'est retenu pour la suite.
2. **Revue** : cliquer sur « Commencer la revue ». Pour chaque finding : `T` ou `N` pour le verdict, `A` pour valider et passer au suivant. `D` donne « security appetite to be discussed », `I` met « À investiguer », `U` annule. Appuyer sur `?` affiche tous les raccourcis.
3. **Excel** : cliquer sur « Exporter ». Vos décisions sont enregistrées tout de suite ; l'Excel est mis à jour à l'export. Si Excel est ouvert, rien n'est perdu : fermez-le et relancez l'export.

## Votre propre campagne

Copier [`examples/campaign.example.json`](examples/campaign.example.json), y mettre vos chemins, puis :

```bash
Paladin.cmd campaign create ma-campagne.json        # Windows
./paladin.sh campaign create ma-campagne.json       # Linux
```

Relancer ensuite `Paladin.cmd` : il ouvre votre campagne au lieu de la démo. Vos données restent **hors du dépôt**, dans `%LOCALAPPDATA%\Paladin` sous Windows et `~/.local/share/paladin` sous Linux.

## En savoir plus

- [Guide complet](docs/GUIDE.md) : commandes, formats d'entrée, export, dépannage.
- [Rapport de recette](docs/RECETTE.md) · [Limites connues](docs/LIMITS.md) · [Avancement](docs/BACKLOG.md) · [Architecture](docs/ARCHITECTURE.md) · [Spécification](SPECS_ASSISTANT_TRIAGE_APPSEC.md)

**État** : revue, imports, export et agent d'analyse fonctionnent. La chaîne réelle OpenCode + GLM 5.3 (via OpenRouter) a été **vérifiée sur Linux**. Elle reste **à vérifier sur le PC de travail** (Windows, fournisseur de l'entreprise), tout comme la connexion Fortify réelle. La démo affiche des propositions **simulées**, signalées comme telles.

# Paladin sur le PC de travail

Tout se fait depuis l'interface. La page **« Prêt pour le travail ? »** (lien en haut à droite) montre l'état de chaque étape et l'action suivante.

## À obtenir avant

| Quoi | Pourquoi | Où l'obtenir |
|---|---|---|
| Git et Python 3.14 | Installer et lancer Paladin | Catalogue logiciel de l'entreprise, ou python.org |
| OpenCode **déjà connecté** au fournisseur GLM de l'entreprise | L'agent d'analyse | Dans OpenCode : `/connect`, ou `opencode auth login` |
| URL de SSC (souvent `https://…/ssc`) | Lire les findings Fortify | Équipe Fortify |
| Un compte SSC **en lecture** sur les applications visées | Voir les applications et leurs findings | Équipe Fortify |
| Un **jeton SSC** de type `UnifiedLoginToken` ou `CIToken` | Authentifier Paladin, sans mot de passe | SSC › Administration › Gestion des jetons |
| Le proxy d'entreprise (`HTTPS_PROXY`) et, en cas d'erreur TLS, le **certificat .pem** de l'autorité interne | Joindre SSC et le fournisseur du modèle | Poste de travail ou équipe réseau |
| La liste des groupes d'applications à auditer (`APP.*`) | Une entrée par groupe | Vous |
| Une version nommée exactement **`release`** dans chaque sous-application | Paladin ne choisit jamais une autre version | Équipe Fortify |
| Les **dépôts de code** clonés au commit de la release | L'agent lit le code | Git |
| Le classeur d'audit avec un onglet « Fortify » (facultatif) | Classeur cible | Vous ; sinon Paladin en génère un |

## Étape 1 — Installer

```bat
git clone https://github.com/H4ss/audit-assistant.git paladin
```

Double-cliquer ensuite sur `paladin\Paladin.cmd`. La première fois, l'installation prend 1 à 2 minutes, puis le navigateur s'ouvre.

## Étape 2 — Connecter OpenCode et votre modèle (plug and play)

Paladin **ne demande aucune clé de modèle**. Il utilise l'OpenCode du poste, avec les fournisseurs que vous y avez déjà connectés.

1. Une seule fois, **dans OpenCode** : `/connect`, choisir le fournisseur de l'entreprise, suivre l'assistant.
2. **Dans Paladin**, page « Agent » :
   - **Détecter mes modèles** : la liste vient de votre OpenCode, avec les GLM en premier.
   - Choisir le GLM, puis **Tester et utiliser**. Paladin pose une question d'une ligne : la réponse et son coût s'affichent, et le modèle est enregistré.
   - **Lancer le sondage** : Paladin vérifie que l'agent n'a accès qu'à ses outils (pas de shell, pas de fichiers, pas de réseau).

Équivalent en ligne de commande : `Paladin.cmd agent connect`, qui donne la liste numérotée, le test et le sondage.

Ce que fait Paladin de son côté :
- il prépare un espace OpenCode **dédié** dans son dossier de données, sans toucher à votre configuration OpenCode ;
- il n'y déclare que le modèle et les permissions ; le fournisseur, l'authentification et le proxy restent ceux de votre OpenCode.

| Message | Que faire |
|---|---|
| « fournisseur non connecté dans OpenCode » | `/connect` dans OpenCode, puis « Tester et utiliser » à nouveau |
| « Modèle inconnu » | Choisir dans la liste détectée (format `fournisseur/modèle`) |
| « Fournisseur injoignable » | Proxy (`HTTPS_PROXY`) ou certificat (`NODE_EXTRA_CA_CERTS`) |
| Aucun modèle détecté | OpenCode n'a encore aucun fournisseur connecté : `/connect` |

## Étape 3 — Connecter Fortify SSC

Page « Prêt pour le travail ? », section « Connexion Fortify SSC » :

1. Saisir l'**URL SSC** et coller le **jeton**. Le jeton est stocké dans le dossier de données (`secrets/`), jamais dans le dépôt ni dans les rapports.
2. **Lancer le diagnostic**. Paladin appelle SSC **en lecture seule** et vérifie chaque point de l'API qu'il utilise. Le rapport (sans secret) contient :
   - la forme du jeton acceptée ;
   - les endpoints vérifiés ;
   - les applications et leurs versions `release` ;
   - la **matrice des champs** (ce que SSC fournit pour chaque colonne de l'Excel).
3. En cas d'erreur TLS, renseigner le certificat `.pem` de l'autorité interne. **TLS n'est jamais désactivé.**

En ligne de commande : `Paladin.cmd fortify login`, puis `Paladin.cmd fortify check`.

### Le certificat d'entreprise

Une autre application du poste parle déjà à Fortify, donc l'autorité de certification interne existe sur le poste. Paladin n'en a besoin **que si le diagnostic signale une erreur TLS**.

- **Emplacement** : aucun déplacement n'est nécessaire. Indiquez le **chemin complet** du fichier dans « Certificat de l'autorité d'entreprise », où qu'il se trouve. Il n'est jamais copié dans le dépôt.
- **Format attendu** : **PEM**, un texte qui commence par `-----BEGIN CERTIFICATE-----`. Selon ce que vous avez :

  | Ce que vous avez | Conversion |
  |---|---|
  | Fichier `.pem`, ou `.crt` texte | Rien à faire |
  | Fichier `.cer` ou `.der` binaire | `certutil -encode ac.cer ac.pem` |
  | Magasin Java (`.jks`, `cacerts`), fréquent pour les outils Fortify | `keytool -list -keystore <magasin>` pour trouver l'alias, puis `keytool -exportcert -rfc -keystore <magasin> -alias <alias> -file ac.pem` |
  | Seulement dans le magasin Windows | `certmgr.msc`, puis Autorités de certification racines de confiance › le certificat › Toutes les tâches › Exporter › « Codé à base 64 (.cer) ». Ce fichier est déjà au format PEM |

- **Côté OpenCode** (fournisseur du modèle), le même fichier PEM se déclare par la variable `NODE_EXTRA_CA_CERTS`.

Un fichier illisible ou binaire produit un message qui indique la conversion à faire. TLS n'est jamais désactivé.

## Étape 4 — Choisir les applications

Page « Applications SSC », bouton **Découvrir les applications**. Paladin regroupe par préfixe :

```text
SHOP          2 / 2 prêtes   16 findings     ← UNE entrée
  SHOP.API      release 10042   13 findings
  SHOP.BILLING  release 10052    3 findings
CRM           1 / 2 prête     7 findings     ← une AUTRE entrée
  CRM.CORE      release 20101    7 findings
  CRM.PORTAL    release absente                (exclue, jamais remplacée)
```

1. Cocher le groupe.
2. Indiquer les dossiers des dépôts de code, un par ligne. Paladin **déduit tout seul** la racine des chemins du scanner.
3. Indiquer éventuellement le classeur cible, puis cliquer **Créer**.
4. Dans la campagne, cliquer **Importer**.

En ligne de commande : `Paladin.cmd fortify discover`, puis `Paladin.cmd fortify create SHOP --repo C:\Code\shop-api`.

## Ensuite

« Mettre en file les findings sans proposition », puis `Paladin.cmd agent run --max-jobs 5`. Revoir les propositions, exporter.

Quand un premier export est réussi, la checklist passe la campagne en **« parcours vérifié »**.

## Ce qui est vérifié, et ce qui ne l'est pas encore

| Élément | État |
|---|---|
| OpenCode v2.0.22 + GLM 5.3 (via OpenRouter) | Vérifié sur Linux |
| Votre OpenCode et votre fournisseur GLM sous Windows | À vérifier avec l'étape 2 |
| Endpoints SSC | Implémentés selon la forme publique de l'API v1 et testés contre un SSC simulé. **Le diagnostic de l'étape 3 les vérifie sur votre instance** avant tout import |
| Correspondance des champs SSC → colonnes Excel | Par défaut ; la matrice du diagnostic indique ce qu'il faut ajuster |

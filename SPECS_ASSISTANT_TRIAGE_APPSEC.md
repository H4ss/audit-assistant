# Project Paladin — assistant local de triage et comparaison AppSec

Version 0.2 — 6 octobre 2026 — Spécifications de réalisation à confier à Claude Code.

**Mission : transformer un volume ingérable de findings en un volume gérable de décisions vérifiables.**

Cette version précise le contrat Excel, la version Fortify `release`, les imports concurrents Excel + MD, les nouveaux onglets, le rapprochement post-analyse et la construction parallèle. Les sections 21 à 24 détaillent ces exigences ; elles complètent les principes du MVP.

## 1. Objectif et contexte

Construire un outil personnel, local et récupérable par Git pour un ingénieur AppSec qui doit traiter environ 800 findings issus de Fortify et de rapports Markdown, puis compléter un Excel comportant un onglet par outil et des colonnes différentes selon les onglets.

Le développement peut être réalisé avec Claude Code sur des données fictives. Sur le PC de travail, OpenCode avec GLM 5.3 (ou son alias configuré `glm-latest`, dont la résolution doit être vérifiée) réalise les analyses à partir des repos et données accessibles sur cette machine. Le logiciel, les données métier et la configuration locale doivent être séparés. Le terme « openclaude » employé dans la demande est traité comme une désignation à confirmer du client souhaité : la cible connue est OpenCode. Ne pas inventer un SDK OpenClaude ni prétendre avoir validé un autre client. Le cœur de Paladin reste indépendant du client et du fournisseur de modèle.

Résultat attendu : moins de temps à chercher, recopier et reformuler ; une décision rapide mais vérifiable ; aucun contexte perdu entre deux sessions ; un Excel fidèle aux décisions réellement validées.

Le produit est un assistant de revue, pas un classificateur autonome de toute la dette. La performance est mesurée en décisions validées par heure, avec suivi des erreurs, et non en propositions générées.

## 2. Principes pour un utilisateur fatigué

1. Une action principale par écran ; verdict, raison et preuve visibles sans naviguer entre cinq vues.
2. Accepter une proposition complète en un clic ou une touche. Corriger sans ouvrir une conversation.
3. Toujours permettre « À investiguer », sans obliger à inventer un TP ou un FP.
4. Une information absente apparaît comme absente. Aucun pourcentage ne remplace une preuve.
5. Sauvegarder les brouillons, reprendre le finding courant et permettre d'annuler la dernière décision.
6. Afficher les différences d'un groupe avant sa validation, pas 300 cartes identiques.
7. Ne jamais changer la carte sous le curseur lorsqu'une analyse arrive en arrière-plan.
8. Éviter les confirmations répétitives : une acceptation individuelle est immédiatement enregistrée et annulable ; une action de lot affiche un seul récapitulatif précis.
9. Afficher la prochaine action utile en cas d'erreur : sélectionner le commit, renouveler le jeton, fermer Excel, compléter un champ.
10. Pas de score de productivité culpabilisant. Le compteur distingue décisions, investigations et propositions en attente.

## 3. Périmètre et priorités

| Priorité | Fonction |
|---|---|
| P0 | Campagne locale, données fictives, SQLite, import MD selon profil déclaré |
| P0 | Mapping Excel par onglet, rapprochement des findings et aperçu des cellules modifiées |
| P0 | Connexion réelle à OpenCode/GLM, propositions structurées, reprise après interruption |
| P0 | Revue individuelle, correction, journal, annulation et export versionné |
| P0 sur PC de travail | Diagnostic Fortify, collecte réelle des détails et validation d'un parcours jusqu'à l'Excel |
| P0 | Contrat Excel exact, champs analyste distincts, ingestion concurrent Excel + MD |
| P0 | Proposition de colonnes pour un nouvel outil et validation d’un schéma d’onglet |
| P1 obligatoire avant clôture comparative | Rapprochement inter-outils, liens confirmés et colonnes Found in / criticality in |
| P1 | Mémoire des corrections, règles explicitement validées et recherche de précédents |
| P1 | Regroupement, comparaison des différences et validation de lot avec traçabilité individuelle |
| P2 | Calibration statistique, regroupements plus avancés et connecteurs supplémentaires |

Hors MVP : fine-tuning, index vectoriel de tous les repos, multi-utilisateur, service cloud hébergé, modification du code audité, écriture dans Fortify, prise en charge universelle de n'importe quel Markdown ou classeur Excel.

Le développement peut avancer sans accès à Fortify. Une campagne Fortify réelle ne peut toutefois pas être déclarée opérationnelle avant le diagnostic de la section 5.

## 4. Architecture proposée

Choix retenu : Python, FastAPI + Uvicorn, SQLite via la bibliothèque standard, HTML rendu avec Jinja2, CSS et JavaScript simples servis localement, openpyxl pour les XLSX et une seule bibliothèque HTTP courante pour Fortify si nécessaire. Dépendances verrouillées après vérification de compatibilité. Pas de Docker, Redis, PostgreSQL, framework agent supplémentaire, serveur vectoriel ou compilation frontend. Pas de dépendances chargées depuis un CDN. Node/Bun n'est pas requis pour le cœur Paladin ; l'adaptateur utilise uniquement ce que l'installation OpenCode prise en charge exige déjà. Voir le contrat de démarrage section 23.

| Composant | Responsabilité |
|---|---|
| Application locale | File de revue, décisions utilisateur, jobs et exports |
| SQLite | État durable, historique, versions et règles |
| Importeurs | Fortify, MD et Excel vers un schéma commun |
| Adaptateur OpenCode | Réclamer un job, exposer son contexte, enregistrer une proposition |
| Agent et skill | Méthode d'analyse, lecture du code et recherche de preuves |
| Exporteur Excel | Écrire exactement les valeurs validées dans les colonnes autorisées |

L'interface écoute sur la boucle locale uniquement. La base reste sur disque local. Les repos sont lus, pas modifiés. Les appels au fournisseur de modèle peuvent transmettre les extraits nécessaires : « application locale » ne signifie pas « inférence locale ». Le diagnostic documente le fournisseur effectif et le périmètre de données autorisé par l'entreprise.

Le transport OpenCode sera un petit adaptateur d'outils personnalisés appelant le service local ou une CLI. Un MCP n'est pas requis au MVP. Les outils OpenCode peuvent être définis en TypeScript/JavaScript et appeler du Python ; valider ce raccordement avec la version effectivement installée avant d'investir dans l'interface.

L'agent analyse un job à la fois au départ, depuis une session OpenCode lancée par l'utilisateur. L'interface et l'agent partagent les états via le service. Ne pas promettre que le bouton de l'interface lancera OpenCode tant que cette intégration n'est pas implémentée. Le statut doit indiquer « agent connecté », « attente d'agent » ou « analyse en cours ».

## 5. Prérequis Fortify sur le PC de travail : jalon bloquant

Créer un assistant de configuration et un diagnostic `doctor` dont chaque contrôle retourne OK, avertissement ou bloquant, avec une action corrective. Les noms de commandes de ce document sont à implémenter, pas des commandes existantes.

### 5.1 Identifier le service

- Confirmer le produit : hypothèse initiale SSC ; ne pas confondre SSC, ScanCentral et Fortify on Demand.
- Relever URL, version, proxy, certificat d'entreprise et mécanisme d'authentification approuvé.
- Consulter la documentation API de cette instance. Aucun endpoint de détail ou d'authentification ne doit être inventé ou considéré identique entre versions.
- Utiliser un accès en lecture ; stocker les secrets hors Git et hors journaux. Ne pas désactiver la validation TLS pour contourner un certificat d'entreprise.
- Sélectionner explicitement l’application et rechercher sa version nommée `release`. Conserver son identifiant réel et son nom renvoyé par Fortify. Si cette version est absente ou ambiguë, bloquer la sélection et demander une résolution ; ne pas choisir une autre version ni écrire artificiellement `release`. Sélectionner ensuite le périmètre du scan. Si l'API ne fournit pas un instantané immutable, conserver date de collecte, métadonnées disponibles et copies des réponses ; signaler cette limite.

### 5.2 Définir et vérifier le périmètre

- Enregistrer les filtres : catégories, sévérités, statuts, supprimés/masqués et autres critères réellement disponibles.
- Gérer toutes les pages, les doublons, limites de débit, reprises et expiration du jeton.
- Comparer le total importé au total API quand disponible et au périmètre visible dans Fortify. Une collecte partielle ne doit pas être présentée comme complète.
- Conserver le manifeste de collecte et les réponses brutes, avec horodatage et empreintes, dans les données locales de la campagne.

### 5.3 Matrice de disponibilité des champs

Pour chaque champ, indiquer : présent dans la liste, disponible via détail, fourni par le repo, fourni manuellement ou indisponible.

| Famille | Informations recherchées |
|---|---|
| Identité | Identifiant du finding dans son périmètre, application/version, identifiant de scan ou équivalent |
| Détection | Catégorie/règle, CWE si disponible, sévérité, description et recommandations scanner |
| Localisation | Chemin, ligne, fonction, source/sink lorsque pertinents |
| Analyse | Trace complète disponible, étapes intermédiaires, extraits et liens vers les détails |
| Audit existant | Statut, commentaire et tags existants ; préserver leur provenance |
| Code | Repo(s), commit scanné ou preuve de correspondance, configurations utiles |
| Excel | Tous les champs exigés par le modèle cible et leurs transformations |

Une trace absente n'invalide pas nécessairement toute analyse : le critère dépend de la famille de vulnérabilité et des autres preuves accessibles. En revanche, son absence ne peut pas justifier un verdict sans investigation supplémentaire.

### 5.4 Vérifier l'Excel cible

Choisir le classeur, les onglets, les en-têtes, les clés de rapprochement et les colonnes éditables. Définir l'origine et le caractère obligatoire de chaque valeur. Distinguer deux modes : compléter des lignes existantes ou générer des lignes à partir d'un modèle. Aucun ajout de ligne implicite.

Un champ métier inconnu, tel qu'un responsable applicatif, doit être fourni ou rester signalé comme manquant ; le modèle ne l'invente pas.

### 5.5 Critère de sortie

Sur quelques findings représentatifs d'une application réelle : retrouver le même finding dans Fortify, collecter les informations nécessaires, lire le code correspondant, produire une proposition sourcée, valider une décision et générer la bonne ligne Excel sans modifier les autres colonnes.

Livrable du diagnostic : rapport local avec matrice des champs, filtres, totaux, correspondance repo/scan, mapping Excel et blocages. Pas de secrets dans ce rapport.

Trois états : « configuration bloquée », « import possible, analyse limitée » et « parcours vérifié ». Une configuration bloquée pour Fortify n'empêche pas de travailler sur une campagne MD indépendante.

## 6. Données locales et Git

Le dépôt Git contient uniquement le logiciel, les migrations, la documentation, la configuration exemple, les instructions de l'agent et les fixtures synthétiques.

Un répertoire de travail distinct contient les campagnes : entrées originales, base, captures Fortify, preuves, mapping local, sorties Excel et sauvegardes. Les repos applicatifs sont référencés par chemins configurés. Ces données ne doivent jamais être commitées par défaut, même si le dépôt logiciel est privé.

Chaque campagne définit : identifiant, sources, repo(s) autorisés, commits, racines de chemins scanner, classeur cible, mapping, profil d'analyse et configuration du modèle. Plusieurs repos ne sont accessibles pour un finding que si son périmètre l'autorise.

Le diagnostic initial vérifie aussi OS, versions Python/OpenCode, accès au fournisseur GLM, permissions sur les dossiers et installation reproductible. Prévoir des instructions Windows et Linux ; ne pas imposer WSL ou des privilèges administrateur sans nécessité identifiée.

## 7. Schéma de données minimal

| Entité | Champs essentiels |
|---|---|
| Campaign | id, nom, configuration, révision, timestamps |
| ImportRun | source, hash, périmètre, totaux, état de complétude, date |
| Finding | id interne, id source + périmètre, payload original, règle, localisation, repo/commit, empreinte |
| TargetBinding | classeur/onglet, clé de ligne, mapping, empreinte de l'entrée |
| Analysis | finding, version, proposition, justification, inconnues, preuves, modèle demandé/résolu, prompt/skill, horodatage |
| Evidence | fichier, commit, lignes, extrait/empreinte, provenance et vérification de référence |
| DecisionEvent | finding, analyse examinée, verdict/commentaire exacts, auteur, action, date, décision précédente |
| Rule | version, conditions, périmètre, exceptions, exemples, validation, état actif/révoqué |
| Group | membres explicites, différences, règle/version, contrôles par membre |
| ExportRun | décisions incluses, source, destination, empreintes, état, rapport de différences |
| Job | finding, statut, tentative, réservation temporaire, expiration, erreur |

L'identifiant interne n'est jamais un numéro de ligne Excel. Un identifiant scanner est contextualisé par son application/version/source. Sans identifiant source, générer une empreinte documentée et exposer les collisions pour résolution ; ne pas fusionner silencieusement.

Les analyses et décisions sont historisées. Annuler crée un nouvel événement ; cela ne réécrit pas l'histoire. Une décision issue d'un lot est identifiable comme telle et ne se présente pas comme une revue individuelle.

## 8. États et transitions

Séparer trois dimensions :

- Traitement : importé, en attente, en analyse, proposition prête, erreur.
- Revue : à revoir, à investiguer, validé, réexamen requis.
- Export : non exporté, exporté à telle version, export périmé ou conflit.

Les valeurs finales autorisées dans `analysis result` sont exactement `Not an issue` et `True Positive`. Les anciens libellés internes TP/FP sont normalisés vers TRUE_POSITIVE/NOT_AN_ISSUE ; ne pas exposer FP comme troisième valeur Excel. Les verdicts ne sont pas des états de job. « À investiguer » conserve une question précise et un motif. « Risque accepté » est une décision de gestion séparée, pas un FP.

Une nouvelle analyse ne remplace jamais une décision humaine validée. Un changement pertinent de code, de contexte, de règle réutilisée ou de source peut marquer le résultat « réexamen requis ». Une modification de modèle est tracée et déclenche un contrôle de référence, pas une réécriture automatique des anciens verdicts.

Chaque job possède une réservation temporaire : après un crash, il peut être repris sans créer une seconde décision. Toutes les écritures vérifient la version attendue pour prévenir les doubles clics et les réponses périmées.

## 9. Parcours utilisateur et interface

### Préparer une campagne

Sélectionner les entrées, le repo et sa version, puis le modèle Excel. L'assistant réutilise les mappings déjà validés. Montrer les compteurs d'import, les correspondances et les informations manquantes avant de lancer les analyses.

### Revoir un finding

La carte montre en premier : proposition, justification courte, preuve principale et éventuel blocage. Les détails scanner, chemin complet et précédents sont dépliables. L'extrait source est disponible dans la page, avec une action « ouvrir dans l'éditeur » lorsqu'elle est configurée.

Actions : Accepter et suivant ; Corriger ; À investiguer ; Passer ; Annuler la dernière décision. Afficher deux champs analyste distincts : `analysis result` et `Analysis result comment`. Un raccourci « Appétence à discuter » prépare le texte exact `security appetite to be discussed`, indépendamment du verdict ; un motif interne court permet de retrouver le point discutable. Ne pas écraser un commentaire libre déjà saisi. Les raccourcis sont visibles et inactifs quand l'utilisateur saisit un commentaire. Ne pas associer Entrée seule à une validation globale.

Le commentaire de l'utilisateur est sauvegardé comme brouillon avant navigation. Le modèle peut suggérer une reformulation, mais celle-ci doit être affichée puis acceptée avant de devenir la valeur finale.

La file est stable : ne pas réordonner le finding courant pendant la lecture. Proposer des vues « prêts à revoir », « contexte manquant », « groupes » et « validés ». Favoriser une file exploitable sans masquer les findings les plus risqués.

### Reprendre et exporter

Au lancement : « Reprendre le finding précédent », nombre de décisions validées non exportées, éventuels jobs interrompus. Aucun besoin de retrouver la conversation OpenCode.

Enregistrer immédiatement la décision dans la base. Un export automatique vers une copie de travail peut être activé après validation du mapping ; le fichier final désigné explicitement est mis à jour selon le mode choisi. Montrer séparément « décision enregistrée » et « Excel à jour ». Un fichier verrouillé ne doit pas faire perdre les décisions.

## 10. Contrat de l'agent OpenCode/GLM

L'agent reçoit pour chaque job un dossier de contexte borné : finding brut et normalisé, repos/versions permis, extraits et traces disponibles, règles applicables, quelques précédents pertinents et schéma de réponse.

Il doit examiner le code nécessaire à la famille de vulnérabilité : origine et contrôle des données, propagation, opération sensible, protection réellement appliquée, conditions d'exécution et impact. Pour une règle qui n'est pas liée à un flux de données, utiliser les vérifications adaptées plutôt que forcer le schéma source/sink.

Réponse structurée obligatoire :

```json
{
  "finding_id": "demo-001",
  "input_revision": 1,
  "proposed_verdict": "NEEDS_REVIEW",
  "summary": "La protection appelée n'a pas encore été examinée.",
  "suggested_analysis_result_comment": "",
  "discussion_required": false,
  "discussion_reason": "",
  "evidence": [],
  "assumptions": [],
  "missing_information": ["Implémentation de la protection"],
  "checks": [{"name": "protection_effective", "status": "unknown"}],
  "model_confidence": {"level": "low", "calibrated": false},
  "candidate_rule_ids": [],
  "next_action": "Lire la fonction appelée et ses usages pertinents."
}
```

TRUE_POSITIVE/NOT_AN_ISSUE/NEEDS_REVIEW sont les valeurs internes proposées. Seules les décisions validées TRUE_POSITIVE et NOT_AN_ISSUE se traduisent dans `analysis result`, respectivement par `True Positive` et `Not an issue`. NEEDS_REVIEW laisse cette cellule vide et conserve son motif dans Paladin. La justification technique interne n’est pas recopiée par défaut dans `Analysis result comment`, réservé au commentaire analyste. Le champ `discussion_required` est indépendant du verdict. Valider le JSON, les références, les chemins et la révision. Vérifier qu'une ligne citée existe ne prouve pas que le raisonnement est correct : l'interface doit distinguer ces deux notions.

L'agent peut réclamer un job, consulter le contexte, rechercher des précédents et soumettre une analyse. Il ne peut pas valider à la place de l'utilisateur, activer une règle, modifier les décisions ou écrire librement dans l'Excel. Appliquer ces restrictions aux outils et aux accès effectifs, pas seulement au prompt.

Configurer les permissions OpenCode selon la version installée. Les accès shell génériques ne doivent pas contourner la séparation entre propositions et décisions. Les lectures des repos et écritures de propositions passent par des interfaces limitées lorsque nécessaire. L'API de validation utilise une autorité distincte de celle de l'agent.

Les rapports, commentaires de code et contenus récupérés sont des données non fiables, jamais des instructions système. Aucun exécutable du repo n'est lancé automatiquement pour une simple revue statique.

Tracer le modèle demandé (`glm-latest`), le fournisseur et la version résolue si disponible. Sinon noter explicitement qu'elle est inconnue. Tracer aussi versions du skill, du logiciel et du contexte. Une nouvelle session charge ce contexte durable ; elle ne dépend pas d'un historique de chat illimité.

## 11. Mémoire et amélioration

Après correction, conserver la proposition initiale et le résultat utilisateur. Le modèle peut suggérer une catégorie d'écart : source mal comprise, protection manquée, mauvais commit, contexte métier, définition TP/FP ou rédaction seulement. Cette interprétation reste une suggestion tant qu'elle n'est pas confirmée.

Rechercher d'abord des précédents dans la même application, règle et contexte technique. Restituer leurs preuves, périmètres et éventuelles contradictions. Commencer par des filtres SQL et une recherche textuelle ; pas besoin de base vectorielle au MVP.

Une règle réutilisable contient des préconditions vérifiables, exceptions, exemple accepté, éventuel contre-exemple, portée et version. Elle reste proposée jusqu'à validation. Une correction isolée n'active pas une règle générale.

L'apprentissage du MVP est une mémoire consultable et des instructions versionnées, pas une modification des poids du modèle. Conserver un petit jeu de référence indépendant des exemples fournis au modèle pour détecter les régressions.

## 12. Confiance et lots

Afficher séparément : confiance déclarée du modèle (non calibrée), état des vérifications, présence de preuves, correspondance à une règle validée et fiabilité empirique lorsque mesurée. Aucun « 100 % sûr » ne doit déclencher une validation.

Distinguer : duplicata exact d'un import ; même cause racine ; cas semblables à analyser. Dédupliquer le transport ne supprime pas les lignes métier à remplir.

Un groupe candidat peut utiliser règle, sink, structure de trace et protection. Son homogénéité exige de comparer aussi contrôle de la source, chemin, contexte, version et exceptions pertinentes. La comparaison doit couvrir chaque membre : un échantillon revu ne démontre pas que les 300 cas sont équivalents.

Le bouton de lot affiche le nombre exact, les IDs, les exceptions, le verdict, le commentaire et sa règle/version. Les membres incomplets sont exclus. La validation applique uniquement à cette liste figée ; un finding importé ensuite n'est pas ajouté rétroactivement.

Enregistrer une décision par membre avec la provenance du lot. Prévoir annulation de lot et réexamen des décisions dérivées d'une règle révoquée. Un commentaire partagé ne doit pas citer une ligne de code fausse pour certains membres ; les références propres à chaque finding restent individualisées.

## 13. Import Markdown et Excel

MD : profils de formats déclarés, conservation du fichier brut et des offsets/sections source. Prévisualiser les findings extraits et les sections non reconnues. Un MD libre peut nécessiter une extraction assistée ; afficher alors le résultat pour validation avant analyse. Ne jamais prétendre supporter tous les formats sans exemple réel.

Excel : mapping par onglet, nom d'en-tête, clé stable et transformations explicites. Accepter des onglets hétérogènes. Les valeurs déjà saisies par un humain sont préservées sauf modification explicitement revue. Toute collision de clé ou absence de correspondance bloque les lignes concernées, pas silencieusement tout le lot.

Si l'Excel sert uniquement de cible et Fortify/MD fournit les findings, effectuer un rapprochement visible. Les lignes non appariées restent dans une file dédiée. Sans clé stable, créer un manifeste de correspondance validé ; après tri/modification externe ambiguë, demander un nouveau rapprochement.

## 14. Export fiable

Le moteur peut exporter les métadonnées importées de tous les findings, une ligne par finding et par outil source ; seules les décisions validées remplissent les colonnes analyste, et seuls les liens confirmés remplissent les cellules comparatives positives. La présence d’une ligne ne signifie donc pas qu’elle est analysée. Le moteur écrit uniquement dans les colonnes autorisées. Il écrit le commentaire exact accepté, sans nouvel appel LLM. Les dossiers d’investigation restent sans `analysis result`. Ne jamais exporter une troisième valeur dans cette colonne. Les détails de l’investigation restent dans Paladin.

Avant écriture : vérifier empreinte/version du classeur cible, clés de rapprochement, mapping et décision courante. En cas de modification externe, produire un conflit explicite et préserver les deux versions.

Écriture dans un fichier temporaire puis remplacement atomique lorsque le système le permet ; sauvegarde de la version précédente ; réouverture et vérification des cellules ciblées et invariants de structure. Une erreur ne marque pas les décisions comme exportées.

Conserver onglets, ordre, cellules hors périmètre, formats et formules pour les classeurs pris en charge. Définir la compatibilité par fixture : MVP XLSX standard. Macros, objets embarqués, signatures et fonctions Excel particulières exigent une qualification séparée ; ne pas promettre une préservation universelle. Ne pas recalculer les formules arbitrairement.

Les commentaires sont écrits comme texte, jamais comme formules exécutables. L'export produit un manifeste reliant chaque cellule modifiée à sa décision, et un résumé : lignes mises à jour, ignorées, bloquées, findings sans cible.

Si une décision est annulée après export, signaler immédiatement que l'Excel est périmé et produire une version corrigée ; ne pas laisser croire qu'annuler dans la base efface les fichiers déjà distribués.

## 15. Tests d'acceptation indispensables

| Scénario | Résultat attendu |
|---|---|
| Réimporter deux fois le même rapport | Aucun finding ni décision dupliqué |
| MD partiellement reconnu | Sections manquantes signalées et import non présenté comme complet |
| API Fortify sur plusieurs pages | Tous les IDs attendus, périmètre et totaux contrôlés |
| Jeton expiré ou page échouée | Reprise possible, collecte partielle visible |
| Mauvais commit | Alerte explicite, pas de verdict de lot basé sur une équivalence non démontrée |
| Proposition sans preuve suffisante | Incertitude et action d'investigation visibles |
| Correction du commentaire seul | Verdict inchangé, texte exact exporté, analyse initiale conservée |
| Double clic ou réponse tardive | Une seule décision ; révision périmée rejetée |
| Fermeture pendant analyse/revue | Brouillon et décisions conservés, job récupérable |
| Un cas différent dans un groupe | Exception visible et exclue de la propagation automatique |
| Classeur réordonné/modifié | Rapprochement par clé ou conflit, jamais mauvaise ligne silencieuse |
| Excel ouvert/verrouillé | Décision sauvée, export en attente et erreur actionnable |
| Export XLSX qualifié | Valeurs finales correctes, formules et cellules hors cible préservées |
| Annulation d'une règle ou d'un lot | Historique conservé, descendants identifiables, export périmé signalé |
| Contenu MD demandant de s'auto-valider | Aucune autorité de validation accordée à ce contenu |
| Contrôle indépendant | Vrais problèmes proposés Not an issue et justifications incorrectes comptabilisés |
| Version Fortify release absente | Aucune autre version sélectionnée silencieusement |
| Schéma Excel complet | Toutes les colonnes de la section 21 présentes, provenance vérifiable |
| Not an issue et commentaire de discussion | Combinaison conservée sans convertir le verdict |
| TP et commentaire de discussion | Combinaison conservée sans convertir le verdict |
| Catégorie et Fortify Category différentes | Deux valeurs originales conservées |
| Concurrent Excel + MD en désaccord | Divergence visible, pas de fusion arbitraire |
| Nouvel outil sans onglet | Schéma proposé, aperçu, validation unique puis création idempotente |
| Même CWE, causes distinctes | Pas de lien confirmé automatiquement |
| Lien un-vers-plusieurs | Toutes les lignes conservées et criticités liées à leurs IDs |
| Corpus concurrent absent/incomplet | Inconnu, jamais présenté comme non détecté |
| Lien confirmé puis annulé | Projection Excel périmée, correction possible |
| Installation fraîche Windows/Linux | Démo sans Docker, service externe ni clé LLM |
| Agent GLM connecté | Proposition réelle reçue sans copier/coller de JSON |

Tester en priorité ces risques réels ; éviter de consacrer le MVP à une couverture artificielle de fonctions triviales.

## 16. Plan de réalisation et portes de sortie

### Étape A — Boucle verticale sur données fictives

Créer une campagne avec un export Fortify synthétique de version `release`, un Excel concurrent enrichi par MD, un outil MD sans onglet, deux repos fictifs ou variantes contrôlées, un Excel à onglets hétérogènes, les deux verdicts finaux et des indéterminés, un cas de duplication, un rapprochement un-vers-plusieurs et un faux ami. Inclure le commentaire `security appetite to be discussed` pour chacun des deux verdicts. Implémenter le stockage, la carte de revue et l'export. Inclure le vrai raccordement OpenCode : le succès d'un modèle simulé seul ne valide pas ce raccordement.

Porte de sortie : importer → analyser → accepter/corriger → exporter → fermer → reprendre, sans copie manuelle de JSON ni perte d'état.

### Étape B — Installation PC de travail et diagnostic

Cloner le logiciel, installer les dépendances selon les contraintes du poste, configurer les chemins et OpenCode/GLM, puis exécuter le diagnostic Fortify et Excel de la section 5. Utiliser des captures locales pour adapter le connecteur sans envoyer les données professionnelles dans le dépôt de développement.

Porte de sortie : quelques findings réels d'une application parcourent toute la chaîne avec mapping et preuves vérifiés. Les limitations restantes sont nommées.

### Étape C — Pilote de rendement

Traiter environ 30 à 50 cas variés ; garder une partie des cas pour une revue indépendante de la proposition. Mesurer temps humain total, taux de corrections du verdict et du commentaire, cas non conclus, références invalides, et vrais problèmes proposés FP. Ce petit pilote estime le rendement mais ne démontre pas un taux d'erreur très faible.

Porte de sortie : gain net observable et aucune défaillance silencieuse de correspondance ou d'export. Fixer avec l'utilisateur les seuils qualité avant d'autoriser une automatisation plus large.

### Étape D — Comparaison, mémoire et validation de groupes

Implémenter la file de rapprochement de la section 22 et les colonnes comparatives ; ce volet est nécessaire pour le livrable final multi-outils. Ajouter les règles validées, comparaisons, exceptions et annulation de lots. Tester notamment les faux amis : même sink avec sources ou protections différentes.

Ne pas donner de durée ferme avant d'avoir vu un export réel, le modèle Excel, la version OpenCode et les possibilités Fortify. Le budget initial doit être plafonné à une boucle verticale fonctionnelle avant d'investir dans le regroupement avancé.

## 17. Mesure du retour sur investissement

Suivre : durée d'installation, temps de paramétrage par campagne, temps humain de revue/correction, attente effective du modèle, coûts d'inférence si disponibles et nombre de décisions valides. Séparer TP/FP/indéterminés et revues individuelles/propagées.

Gain net = temps estimé du traitement manuel comparable − temps réel de configuration, revue, corrections et reprises. Comparer des familles de complexité voisine ; 300 duplicatas ne représentent pas 300 analyses indépendantes.

Les métriques qualité incluent notamment : parmi les propositions FP revues, combien étaient réellement TP ; parmi les TP du jeu de référence, combien ont été proposés FP ; justifications fausses malgré un verdict correct ; taux d'abstention. Toujours montrer les effectifs, pas seulement les pourcentages.

## 18. Consigne de démarrage pour Claude Code

> Construis Project Paladin selon ces spécifications. Commence par une boucle verticale locale sur fixtures synthétiques, installable depuis un clone GitHub avec Python et pip, sans Docker ni compilation frontend. Vérifie les versions et définis d’abord les contrats partagés : données, statuts, Excel exact, liens inter-outils et API de propositions. Tu peux ensuite déléguer en parallèle à une petite équipe avec des périmètres de fichiers distincts, selon la section 24. Le coordinateur possède les migrations et l’intégration. Implémente l’import concurrent Excel + MD, la proposition de schéma pour un outil sans onglet, la revue, les deux valeurs exactes de verdict et le commentaire de discussion indépendant. Intègre OpenCode avec le fournisseur GLM configuré ; n’invente pas de compatibilité OpenClaude. Prépare Fortify avec fixtures et diagnostic, puis raccorde uniquement des endpoints vérifiés sur l’instance réelle ; la version cible est release. Les propositions du modèle ne sont jamais des validations humaines. Le rapprochement inter-outils conserve chaque finding et ne propage pas de verdict. Exécute une boucle bornée tâche → implémentation → tests utiles → intégration → mise à jour du backlog. Continue sur les tâches indépendantes si Fortify ou un accès réel manque, documente le blocage, ne simule pas une réussite. Livre un README de démarrage, une démo reproductible sans clé, le connecteur réel vérifiable séparément et une CI Windows/Linux. Ne commite ni données métier ni secrets. Termine lorsque les critères de la tranche sont remplis ou qu’un blocage externe rend les tâches restantes impossibles, sans ajouter de fonctionnalités hors périmètre.

## 19. Informations à renseigner plus tard, sans bloquer les specs

- OS et contraintes d'installation du PC de travail.
- Version OpenCode, confirmation du nom « openclaude » si un autre client est visé, fournisseur et identifiant GLM 5.3 réellement disponibles.
- Produit/version Fortify, documentation API interne, droits et périmètre d'une application pilote.
- Exemple réel ou anonymisé de MD et de classeur cible : orthographe exacte des en-têtes déjà présents, clés, mode ajout/complétion et formats de criticité. Les champs requis et les deux valeurs de verdict sont déjà fixés en section 21.
- Correspondance entre versions scannées et commits des repos.
- Définition métier de Not an issue / True Positive, portée du commentaire de discussion, critères de validation de lot et périmètres comparables entre scans.

## 20. Références et statut des choix

Les architectures, schémas, noms d'outils et commandes proposés ci-dessus sont des spécifications à implémenter. Les compatibilités exactes sont à vérifier sur le PC de travail ; aucune connexion à l'instance Fortify de l'utilisateur n'a été testée dans la préparation de ce document.

- OpenCode — outils personnalisés : https://opencode.ai/docs/custom-tools/
- OpenCode — skills : https://opencode.ai/docs/skills/
- OpenCode — agents et permissions : https://opencode.ai/docs/agents/
- Fortify — client REST SSC officiel, fondé sur Swagger : https://github.com/fortify/ssc-restapi-client

- Claude Code — modèles : https://code.claude.com/docs/en/model-config
- Claude Code — sous-agents : https://code.claude.com/docs/en/sub-agents

Ces références décrivent les capacités générales. La documentation API de l'instance Fortify et la version d'OpenCode installée font autorité pour l'intégration concrète.

## 21. Contrat Excel métier de Project Paladin

### 21.1 Une ligne par finding, un onglet par outil

Chaque finding source garde sa ligne dans l'onglet de son outil. Une correspondance inter-outils ne fusionne pas les lignes. Un regroupement de revue ne supprime pas non plus les occurrences. Un réimport identique actualise la provenance sans créer une nouvelle occurrence.

Les libellés ci-dessous sont les en-têtes par défaut d'un classeur neuf. Dans un modèle existant, conserver les noms et l'ordre réels et les associer aux clés internes par mapping. Les deux valeurs de `analysis result` et la phrase de discussion sont, elles, fixées exactement.

| Colonne Excel | Clé interne | Source et règle |
|---|---|---|
| Application name | application_name | Nom de l'application renvoyé par Fortify ou déclaré pour le corpus concurrent ; aucune inférence depuis le nom du dossier |
| Version name | version_name | Pour Fortify, version sélectionnée nommée `release` et son identifiant réel conservé en base ; pour les autres outils, leur version réelle si disponible |
| Category | category | Catégorie originale de la finding ; conserver la distinction avec Fortify Category |
| Primary location | primary_location | Valeur d'affichage fournie par la source ou construction explicitement documentée si absente ; ne pas l'assimiler silencieusement au chemin complet |
| Line number | line_number | Ligne principale, entier si disponible ; cellule vide si absente, pas de 0 inventé |
| Full filename | full_filename | Chemin complet fourni par l'outil ; chemin normalisé pour comparaison conservé séparément en base |
| Criticality | criticality_raw | Niveau original de l'outil, sans réévaluation silencieuse ni remplacement par une criticité harmonisée |
| Commentaires | source_comments | Commentaires scanner/rapport/audit préexistants, avec provenance ; distincts du commentaire de l'analyste Paladin |
| Analyzer | analyzer_type | Type d'Analyzer renvoyé par la source, par exemple le type technique si disponible ; ne pas le remplacer par le nom du produit |
| Primary rule ID | primary_rule_id | Identifiant de règle source exact, conservé comme texte |
| Instance ID | instance_id | Identifiant d'occurrence exact, conservé comme texte, contextualisé en base par outil/application/version |
| Fortify Category | fortify_category | Valeur originale du champ Fortify correspondant ; ne pas copier Category sans mapping vérifié |
| CWE | cwe_ids | Valeur(s) source, liste interne normalisée, export stable tel que CWE-79; CWE-89 ; aucune CWE devinée comme donnée source |
| analysis result | analyst_result | Vide tant que non validé ; puis exactement Not an issue ou True Positive |
| Analysis result comment | analyst_comment | Texte exact validé par l'analyste, pouvant être security appetite to be discussed pour chacun des deux verdicts |
| Found in <outil> | relation_projection | Résultat de rapprochement avec l'outil nommé, selon la section 22 |
| criticality in <outil> | related_criticalities | Criticité originale des findings liés et confirmés dans cet outil |

Les paires comparatives sont répétées pour chaque autre outil sélectionné. Le nom de l'outil est un libellé canonique configurable, pas une chaîne réinventée à chaque export. Par exemple, l'onglet Fortify peut avoir `Found in ToolB` et `criticality in ToolB`, et l'onglet ToolB les colonnes réciproques pour Fortify.

Ne pas inventer un champ absent dans l'API. La structure de l'Excel doit offrir toutes les colonnes demandées pour Fortify ; la matrice du diagnostic indique les valeurs indisponibles et leur importance. Identité ambiguë ou association à la mauvaise application/version : blocage. Une métadonnée facultative absente reste vide et signalée, sauf exigence obligatoire du modèle cible. Une preuve technique manquante affecte séparément l'analyse.

Ne pas forcer des champs purement Fortify dans tous les onglets concurrents. Le noyau concurrent commun comporte identité application/version lorsqu'elle existe, catégorie/règle, localisation, criticité, provenance, champs analyste et paires comparatives ; les champs spécifiques dépendent du schéma validé.

### 21.2 Trois informations à ne pas mélanger

- `Commentaires` : contenu hérité du scanner ou de l'import. Une cellule existante dont l'origine est inconnue est préservée jusqu'au mapping explicite.
- Justification technique Paladin : preuves et raisonnement synthétique stockés en base et visibles dans la fiche.
- `Analysis result comment` : commentaire final destiné au lecteur de l'Excel, sous contrôle de l'analyste.

Le commentaire `security appetite to be discussed` signifie qu'un point mérite une discussion avec une personne compétente. Il n'est ni une acceptation du risque, ni un verdict indéterminé, ni une conversion automatique vers TP. Conserver en interne `discussion_required`, le motif et l'état de discussion, indépendamment de `analyst_result`.

Exemples de résultats autorisés :

| analysis result | Analysis result comment | Interprétation |
|---|---|---|
| Not an issue | security appetite to be discussed | Classification validée, point de discussion conservé |
| True Positive | security appetite to be discussed | Problème réel validé, décision de traitement à discuter |
| True Positive | texte libre validé | Verdict et commentaire exacts de l'analyste |
| cellule vide | cellule vide | Pas encore de verdict final ; investigation accessible dans Paladin |

La suggestion LLM de commentaire reste distincte de la valeur finale. Le champ commentaire peut rester vide après validation ; une phrase générique ne doit pas être ajoutée systématiquement.

### 21.3 Concurrents : Excel d'inventaire + Markdown de détails

Prendre en charge conjointement les deux entrées. Par défaut, l'Excel fournit l'inventaire et les lignes à compléter ; le MD apporte contexte, détails et preuves. Ce rôle doit être visible et configurable par source, pas deviné silencieusement.

Pipeline : lire les deux sources → normaliser séparément → rapprocher les entrées du même outil → afficher les anomalies → enrichir le dossier de chaque finding → analyser → écrire la ligne cible.

Rapprochement intra-outil : ID commun d'abord ; sinon règle + fichier + localisation + application/version, puis confirmation des cas ambigus. Le rapprochement Excel/MD n'est pas encore la comparaison Fortify/concurrent de la section 22.

Conserver pour chaque valeur retenue sa source précise : fichier, hash, onglet/clé ou section MD. Si les deux entrées divergent sur criticité, ligne ou catégorie, conserver les deux valeurs et demander résolution ou appliquer une priorité de champ préalablement validée. Ne jamais écraser une décision analyste avec le texte du MD.

Montrer trois compteurs : appariés, Excel sans détail MD, MD sans ligne Excel. Les findings Excel sans MD peuvent avancer si le contexte est suffisant ; sinon ils passent en investigation. Un finding uniquement MD devient une proposition de nouvelle ligne ; il n'est ni perdu ni ajouté sans la politique d'import validée.

### 21.4 Nouvel outil sans onglet : proposer un schéma

Paladin transmet via l'adaptateur OpenCode un échantillon de la source et l'inventaire des champs détectés. Le modèle propose un objet `SheetSchemaProposal` : outil, onglet, colonnes ordonnées, clé interne, type, provenance/exemple, disponibilité, caractère obligatoire et transformation éventuelle. Aucun code généré n'est exécuté pour appliquer ce schéma.

L'interface présente une prévisualisation de quelques lignes, le nombre de champs non couverts et les colonnes analyste verrouillées dans leur sens métier. L'utilisateur peut renommer, retirer ou réordonner les colonnes non obligatoires, puis valider une fois le schéma. Après validation, l'exporteur crée l'onglet et les lignes de façon déterministe. Le schéma est réutilisé aux imports suivants.

Respecter les contraintes de nommage Excel et détecter les collisions d'onglets. Un nouvel import avec champs supplémentaires propose une évolution versionnée, sans supprimer de colonne existante ni effacer les valeurs analyste. Si le modèle n'est pas connecté, permettre le mapping manuel ; ne pas bloquer le reste de la campagne.

Critère de recette : importer un rapport d'un outil fictif jamais vu, proposer le schéma, vérifier l'aperçu, créer l'onglet, réimporter sans doublon, puis compléter un verdict et un lien comparatif.

## 22. Post-analyse : rapprochement inter-outils

### 22.1 Objectif et distinctions

Répondre à « ce finding est-il également signalé par cet autre outil, et avec quelle criticité ? ». Ne pas transformer cette phase en une deuxième analyse complète de chaque vulnérabilité.

Distinguer quatre opérations : déduplication d'import, enrichissement Excel/MD du même outil, groupement pour revue, et correspondance inter-outils. Chacune a son propre statut et sa propre justification.

Les liens peuvent être proposés avant la fin du triage ; leur confirmation se fait dans une file dédiée. Ils ne propagent ni verdict, ni commentaire, ni criticité : deux scanners peuvent produire des alertes proches avec des assertions différentes.

### 22.2 Préparer des candidats sans explosion du travail

1. Définir les corpus comparables : même application, repo/version ou correspondance documentée, périmètres de scan et filtres connus.
2. Normaliser en interne les chemins et préfixes scanner, séparateurs, symboles et catégories ; conserver les valeurs brutes pour l'Excel. Ne pas supprimer arbitrairement la casse sur un système sensible à celle-ci.
3. Générer les candidats par fichier/symbole, opération sensible ou chemin, famille de règle/CWE et proximité de localisation. La CWE ou le numéro de ligne seuls ne prouvent pas une correspondance.
4. Comparer les candidats les plus pertinents. Le modèle explique concordances, différences et contexte manquant. Il ne compare pas aveuglément tous les findings deux à deux.
5. Présenter une shortlist bornée et les éventuels candidats supplémentaires ; une limite de shortlist ne doit jamais devenir une preuve d'absence.

Les changements de commit peuvent décaler les lignes. Un rapprochement inter-version doit être explicitement marqué, justifié et exclu par défaut d'une affirmation de couverture identique.

### 22.3 Types et états des liens

Entité `FindingRelation` : deux findings, type proposé, état, preuves, différences, version du comparateur, auteur/date de validation, contexte comparé et historique.

Types : `same_occurrence` (même problème au même emplacement/chemin pertinent), `same_root_cause` (cause partagée mais occurrences distinctes), `related` (ressemblance utile), `different` (candidat rejeté). États : proposé, confirmé, rejeté, réexamen requis.

Seul `same_occurrence` confirmé alimente par défaut `Found in <outil>`. Une cause racine partagée reste visible sans devenir automatiquement « trouvé par l'autre outil ». Si la politique métier choisit une autre portée, la versionner et la rendre explicite dans la campagne.

Supporter les liens un-vers-plusieurs et plusieurs-vers-plusieurs. Ne pas fermer les relations par transitivité : confirmer A–B et B–C ne confirme pas A–C. Ne pas fusionner les lignes ni considérer le verdict d'un outil comme vérité de l'autre.

### 22.4 Interface de rapprochement

Carte latérale côte à côte : fichier/fonction, lignes, catégorie/CWE, source/sink si pertinent, trace courte, criticité originale, verdict actuel et différences soulignées. Actions : « Même occurrence », « Cause commune seulement », « Différent », « À revoir ».

Pour un groupe de propositions réellement homogènes, permettre une validation de lot avec liste précise et exceptions ; conserver un événement par lien. Un lien peut être confirmé même si les verdicts diffèrent ; ce désaccord reste visible et n'est pas corrigé automatiquement.

Prioriser les candidats explicables et les désaccords utiles. Une liste « à revoir » permet de différer les cas coûteux. Conserver les rejets pour ne pas reproposer sans changement le même faux ami à chaque session.

### 22.5 Projection des colonnes comparatives

Politique par défaut d'un nouveau classeur, adaptable à un modèle existant via mapping validé :

| État réel | Found in ToolB | criticality in ToolB |
|---|---|---|
| Une ou plusieurs correspondances confirmées | Yes | Criticité brute ; plusieurs valeurs accompagnées de leurs IDs si nécessaire |
| Des candidats restent à revoir | Pending review | vide |
| Corpus absent, incomplet ou non comparable | Unknown | vide |
| Recherche revue, corpus complet et comparable, aucun lien confirmé | No confirmed match | vide |

`No confirmed match` ne signifie pas que l'outil ne sait pas détecter la vulnérabilité. Une non-détection prouvée ne se déduit pas seulement d'un export. Si le classeur exige Yes/No, mapper `No` seulement à la condition explicitement validée, garder inconnu/en attente vides et documenter la convention.

Pour plusieurs liens : conserver toutes les criticités et leurs correspondances, par exemple `B-17: High; B-29: Medium`. Ne pas choisir silencieusement le maximum. La base et la vue de détails conservent les IDs même si le format cible impose une représentation plus courte. Chaque projection positive est traçable et réciproque pour les onglets inclus dans l'export.

Les criticités source restent brutes. Une échelle harmonisée peut être ajoutée pour les filtres internes seulement avec un mapping validé par outil. Ne pas comparer numériquement deux échelles dont le sens ou l'ordre n'a pas été défini.

### 22.6 Réduction concrète de la charge

Préparer les candidats pendant l'analyse et réutiliser le contexte déjà collecté. Ne demander à l'analyste que la décision de rapprochement et la résolution des ambiguïtés. Afficher : liens confirmés, candidats restants, corpus manquants et groupes comparables sans lien confirmé.

Ajouter à la base `ComparisonRun` (corpus, filtres, complétude, révisions), `FindingRelation`, `SheetSchemaProposal` et la provenance par champ. Une réimportation, modification de version ou annulation de lien invalide les projections concernées sans effacer leur historique. Prévoir un export des décisions analyste même si la comparaison n'est pas terminée ; afficher explicitement les cellules comparatives en attente.

## 23. Contrat « clone GitHub et démarrage simple »

« Out of the box » signifie : sur une machine avec Git et une version Python prise en charge, le dépôt s'installe et sa démo fonctionne selon le README, sans compte payant ni données professionnelles. La connexion Fortify et le modèle réel requièrent ensuite les accès du poste de travail. Il ne s'agit pas d'héberger Paladin sur GitHub Pages ni d'exécuter les données métier dans GitHub Actions.

### 23.1 Parcours d'installation cible

Livrer `pyproject.toml`, dépendances résolues de façon reproductible pour Windows/Linux, migrations automatiques avec sauvegarde avant mise à jour, fixtures et points d'entrée CLI. Les commandes suivantes sont un contrat à implémenter :

```text
git clone <URL_DU_DEPOT>
cd project-paladin
python -m venv .venv
# Activer le venv selon Windows ou Linux, instructions exactes dans le README.
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m paladin demo
python -m paladin serve
```

Le README doit fournir les commandes complètes pour les deux OS, y compris une méthode appelant directement le Python du venv si l'activation PowerShell est restreinte. Ni `uv`, ni Poetry, ni Conda ne sont imposés. Un script de démarrage peut simplifier ce parcours mais ne doit pas masquer les erreurs ou installer un composant système sans l'expliquer.

La démo peuple un espace distinct avec données fictives et propositions clairement simulées ; elle ne prétend pas démontrer la connexion GLM. Un second parcours `doctor` puis un test réel vérifie séparément OpenCode/GLM et Fortify.

### 23.2 Distribution et configuration

- Fournir une configuration exemple et un assistant local ; ne pas demander de modifier du Python pour choisir un dossier, une URL ou un modèle.
- Tout asset UI est inclus. Pas de CDN, télémétrie ou service distant obligatoire pour démarrer la revue locale.
- Définir une version Python de référence et une matrice réduite réellement testée. Éviter les packages nécessitant une compilation native sur les OS cibles.
- Gérer chemins avec espaces, caractères accentués, séparateurs Windows et port déjà occupé.
- Les secrets et données locales sont exclus du suivi Git ; une mise à jour du logiciel ne remplace pas le dossier des campagnes.
- Le lancement doit afficher clairement l'URL locale, le dossier de données et l'état des connecteurs. Un mode sans LLM permet encore consultation, décisions manuelles et export.
- Livrer un exemple OpenCode, son adaptateur et une procédure de connexion sans copier des réponses JSON à la main. Respecter la configuration existante et fournir un aperçu des ajouts, sans écraser les autres providers/outils.
- GLM 5.3 est une configuration, pas une dépendance codée en dur. Ne pas ajouter une bibliothèque Z.ai spécifique si le client OpenCode assure déjà le transport.
- La compatibilité avec un autre client éventuellement nommé « openclaude » reste une extension tant que son identité et son interface ne sont pas connues.

### 23.3 Définition de « prêt sur GitHub »

Une CI GitHub Actions Windows/Linux installe depuis un checkout propre, initialise la démo, vérifie le démarrage/arrêt du service et exécute le parcours import → revue → export → reprise. Elle teste les connecteurs par fixtures et simule pagination/erreurs ; elle ne réclame aucun jeton métier. Ajouter un test d'intégration réel opt-in, explicitement distinct des tests CI.

Le dépôt livre README, spécifications, architecture courte, backlog, tests, exemples et limites connues. Le README annonce uniquement les combinaisons réellement vérifiées. Le projet n'est pas déclaré compatible Fortify réel ou GLM réel sur la seule réussite de mocks.

## 24. Construction parallèle avec Claude Code

### 24.1 Séparer construction et exploitation

La mini-équipe sert à construire le logiciel. Elle n'implique pas de faire analyser chaque vulnérabilité par plusieurs modèles ni d'exécuter plusieurs agents de production en parallèle dès le MVP.

Le coordinateur commence par figer les interfaces minimales et les fixtures partagées : schéma des findings, valeurs de verdict, commentaire indépendant, contrat Excel, relations et API agent/UI. Le code de contrats, les migrations et le fichier de dépendances ont un propriétaire unique. Cela permet ensuite de travailler en parallèle sans inventer trois modèles de données incompatibles.

### 24.2 Répartition conseillée

| Rôle | Périmètre | Livrable vérifiable |
|---|---|---|
| Coordinateur/intégrateur | Contrats, stockage, migrations, CLI et arbitrages | Boucle verticale et intégration de chaque contribution |
| Agent imports/Excel | Lecteurs, provenance, mapping, schémas d'onglets et export | Round-trip Excel, imports Excel + MD et connecteur Fortify à fixtures |
| Agent interface | Pages, revue, brouillons, annulation et rapprochement visuel | Parcours manuel cohérent avec les contrats |
| Agent intégration/qualité | Adaptateur OpenCode, jobs, doctor, recette propre | Proposition structurée réelle si accès disponible, démo et tests de reprise |

Maximum initial : coordinateur + trois agents. Si budget ou interfaces insuffisantes, passer à deux agents ou au séquentiel. Les modules de rapprochement peuvent être attribués dans une seconde vague après intégration des imports et de la revue. Éviter de construire simultanément toutes les fonctionnalités sur des contrats instables.

Utiliser des worktrees/branches isolés si le runner les supporte, ou des périmètres de fichiers exclusifs. Chaque agent déclare fichiers possédés, dépendances, tests et modifications de contrat demandées. Le coordinateur intègre par petites unités et lance la recette globale ; les agents ne modifient pas simultanément les migrations ou le verrou de dépendances.

### 24.3 Boucle autonome bornée

Conserver un backlog durable avec état, propriétaire, dépendances, critère de recette et blocage éventuel. Le coordinateur choisit les tâches indépendantes prêtes, délègue, inspecte les résultats, intègre, teste et actualise le backlog. Il ne s'arrête pas après un simple plan si une tâche autorisée et réalisable reste disponible.

Fixer au lancement une limite de concurrence et un budget de session ou de cycles. Après deux tentatives infructueuses sur le même blocage, changer de diagnostic ou consigner le blocage ; ne pas relancer indéfiniment la même opération. Un accès Fortify absent ne justifie ni un faux succès ni l'arrêt des tâches indépendantes restantes.

Terminer la tranche sur un livrable exécutable et un rapport de recette, ou un blocage externe précis. Conserver les permissions normales du runner ; aucune option de contournement global des contrôles n'est requise. La mise à disposition du dépôt et les opérations Git distantes suivent les autorisations du projet.

### 24.4 Choix des modèles pour construire

Recommandation de répartition, pas benchmark démontré pour Paladin :

| Travail | Choix de départ |
|---|---|
| Architecture, contrats, intégration complexe et revue des invariants | Claude Opus disponible dans le compte, alias `opus`, puis version résolue enregistrée |
| Développement de modules bien spécifiés et tests ciblés | Claude Sonnet disponible, alias `sonnet`, version enregistrée |
| Budget limité / orchestration multi-modèle indisponible | Un seul Sonnet et tâches séquentielles ; escalade ponctuelle sur un problème concret |
| Exploitation AppSec sur le poste | GLM 5.3 via OpenCode, évalué sur les cas de référence |

Les alias et possibilités de configuration par sous-agent sont documentés par Claude Code ; les versions exactes et accès dépendent du fournisseur et du compte. Vérifier le modèle effectif au lancement et épingler une version pour les campagnes de développement reproductibles. Ne pas prétendre qu'un modèle « sait mieux » les verdicts Paladin sans mesure sur le pilote.

Préférer les sous-agents standards disponibles ; ne pas rendre le dépôt dépendant d'une fonctionnalité expérimentale d'équipes. Si le runner ne permet pas de choisir des modèles différents, garder le modèle de session plutôt que bricoler un mécanisme opaque.

### 24.5 Recette finale de la tranche

Le coordinateur doit démontrer, avec une installation neuve et les fixtures : sélection Fortify `release`, import concurrent Excel + MD, proposition d'onglet pour un nouvel outil, deux verdicts exacts avec commentaire de discussion indépendant, correction annulable, lien inter-outils confirmé, criticités originales exportées, fermeture/reprise et préservation des cellules hors périmètre. Les points non vérifiés sur une instance réelle sont listés séparément avec la commande ou action nécessaire au PC de travail.

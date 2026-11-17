# Griot Secure : « Dites-le-nous une fois »

Les pièces circulent entre administrations, à la place des usagers qui vont d'un guichet à l'autre.
Le service qui traite un dossier reçoit seulement la réponse utile, signée par l'administration qui détient la
donnée (par exemple « burkinabè : oui »), jamais le document entier. L'usager voit avant ce qui va partir.
Il peut vérifier après qui a consulté ses données.

Équipe Griot Secure (Burkina Institute of Technology), finale du Hackathon 226, sujet 02.
Toutes les données et tous les comptes sont **fictifs**.

## Concept

<!-- à rédiger par Enock -->

## Scénario

<!-- à rédiger par Enock. Scène principale : le passeport ordinaire (voir docs/SCENARIO_PASSEPORT.md) -->

## Les couches du socle

Le sujet demande un socle en couches. Le détail de chacune : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Couche | En une phrase |
|---|---|
| 1. **Registres** | État civil, nationalité, casier : chacun garde ses données et répond « oui » ou « non », signé avec sa clé (registres simulés, en attendant le contrat commun du jury) |
| 2. **Passerelle d'échange** | Fait circuler questions et réponses, en parallèle, avec un délai maximal ; vérifie chaque signature ; ne peut ni lire ni fabriquer une réponse |
| 3. **Consentement et minimisation** | Un catalogue fixe à l'avance ce que chaque démarche peut demander, pourquoi et sur quelle base ; l'usager confirme avant l'envoi |
| 4. **Journal de traçabilité** | Chaque consultation est notée (le fait, jamais la valeur), dans un journal chaîné ; l'usager reçoit un reçu |
| 5. **Espace usager** | Téléphone simple (`*226#`) et portail web : voir avant, confirmer ou refuser, voir qui a consulté |
| Bonus : **Guichet** | Écran de l'agent (mot de passe + code TOTP), qui revérifie les signatures ; page Contrôle en lecture seule |
| Bonus : **Résilience** | Registre coupé, lent ou falsifié : refus clair, « rien n'a été deviné » ; tout marche sans Internet |

## Les 3 épreuves du sujet, et où les voir

| Épreuve | Couches | Où le voir dans la démo ([docs/test-manuel.md](docs/test-manuel.md)) |
|---|---|---|
| **Ne transmettre que l'utile** | 1, 3 | Scène 1 (passeport) : l'ONI reçoit « burkinabè : oui » et « interdiction de sortie du territoire : non », rien d'autre. Scène 1 bis : l'outil de preuve cherche les données de la personne partout hors des registres et ne les trouve pas |
| **Montrer à l'usager qui a consulté ses données** | 4, 5 | Scène 3 : « Qui a consulté mes données » et le reçu. Scène 3 bis : la même chose sur le portail web. Scène 8 : une ligne du journal modifiée est détectée |
| **Tenir quand un registre tombe en panne** | 2, résilience | Scène 1 ter (un registre sur trois en panne), scène 6 (registre coupé, lent, falsifié), scène 9 (wifi coupé) |

## Installation pas à pas (Windows, PowerShell)

**Prérequis** : Docker Desktop lancé, avec `docker compose` ; git ; Python 3 (les images utilisent Python 3.13) ;
ports 80 et 443 libres. **Après l'installation, aucun accès à Internet n'est nécessaire.**

Les commandes exactes (avec les chemins des fichiers) sont dans [docs/OU_TROUVER_QUOI.md](docs/OU_TROUVER_QUOI.md),
section « Commandes ».

1. Récupérer le code et créer le fichier des secrets :
   ```powershell
   git clone https://github.com/wangredelwende-spec/griot-dites-le-nous-une-fois.git
   cd griot-dites-le-nous-une-fois
   Copy-Item .env.example .env
   ```
   Les valeurs de `.env.example` suffisent pour la démo. En déploiement réel, il faut changer **chaque** valeur.
2. Ajouter les noms des sites au fichier hosts (`C:\Windows\System32\drivers\etc\hosts`, Bloc-notes lancé en
   administrateur) :
   `127.0.0.1 guichet.griot.test usager.griot.test auth.griot.test`
3. Démarrer : `docker compose up -d --wait`. Il y a 10 services : PostgreSQL, Keycloak, 3 registres, passerelle,
   guichet, USSD, portail web et Caddy. `docker compose ps` doit les montrer « healthy ».
4. Faire confiance au HTTPS local : copier le certificat de l'autorité interne de Caddy (commande dans « Où trouver
   quoi »), double-cliquer dessus, Installer le certificat, Utilisateur actuel, « Autorités de certification
   racines de confiance ». Ce fichier n'est jamais commité.
5. Pour les scripts et les tests : créer l'environnement Python et lancer les tests (commandes dans « Où trouver
   quoi »).
6. Ouvrir <https://guichet.griot.test> (agents) et <https://usager.griot.test> (téléphone simulé ; portail web
   sur `/portail`). À la première connexion, chaque agent enregistre son code à 6 chiffres (TOTP) en scannant un
   QR code avec une application libre comme FreeOTP ou Aegis.

Avant une démo : remise à zéro des données de démo (le journal est archivé, jamais effacé). Sans réseau : les
images se sauvegardent et se rechargent. Détail : [docs/test-manuel.md](docs/test-manuel.md).

## Comptes de démonstration (fictifs)

Agents (guichet) : mot de passe **et** code TOTP.

| Compte | Mot de passe | Service | Rôle dans la démo |
|---|---|---|---|
| `moussa.kone` | `Agent-Demo-2026!` | Service des passeports – ONI | Passeport ordinaire (scène principale) |
| `issa.sawadogo` | `Agent-Demo-2026!` | Direction des concours | Concours direct, Vérifier la majorité |
| `awa.ouedraogo` | `Agent-Demo-2026!` | Service des bourses | Bourse nationale, Vérifier la majorité |
| `mariam.kabore` | `Agent-Demo-2026!` | Mairie | Vérifier la majorité |
| `agent.curieux` | `Agent-Demo-2026!` | Service des bourses | Montre le blocage d'un agent qui consulte trop de personnes |
| `controle.cil` | `Controle-Demo-2026!` | Contrôle (lecture seule) | Page <https://guichet.griot.test/controle> |

`agent.banc` et `agent.banc.bourses` servent aux tests automatiques : ne pas les utiliser en démo.

Usagers (`*226#` ou portail web) : numéro + code PIN. Exemple : `70000001`, PIN `1234` (Aminata Kaboré,
`BF-0001`). La liste complète est dans [docs/test-manuel.md](docs/test-manuel.md).
En production, l'usager se connecterait avec l'identifiant unique électronique (voir [LIMITES.md](LIMITES.md)).

## Licence

Le code est sous **AGPL-3.0** ([LICENSE](LICENSE)) : chacun peut l'utiliser, le modifier et le redistribuer.
Une version modifiée, même proposée seulement en ligne, doit publier son code sous la même licence.
Les composants utilisés et leurs licences : [docs/DEPENDANCES.md](docs/DEPENDANCES.md).

## Documentation

| Document | Pour qui | Contenu |
|---|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | jury, informaticiens | Les couches une par une, trajet d'une demande, qui voit quoi, choix techniques |
| [docs/OU_TROUVER_QUOI.md](docs/OU_TROUVER_QUOI.md) | informaticiens | Tous les chemins des fichiers et toutes les commandes, par couche |
| [docs/SCENARIO_PASSEPORT.md](docs/SCENARIO_PASSEPORT.md) | tous | L'histoire de l'usager, avant et après |
| [docs/REGLES_DU_SOCLE.md](docs/REGLES_DU_SOCLE.md) | administrations | Les 10 règles, adoptables même sans notre logiciel |
| [docs/test-manuel.md](docs/test-manuel.md) | équipe, jury | Démo pas à pas, scène par scène |
| [docs/fiche-oral.md](docs/fiche-oral.md) | équipe | Réponses aux questions du jury |
| [docs/AJOUTER_UNE_DEMARCHE.md](docs/AJOUTER_UNE_DEMARCHE.md) | administrations | Ajouter une démarche avec un fichier YAML, sans code |
| [docs/JOUR_J_DONNEES_JURY.md](docs/JOUR_J_DONNEES_JURY.md) | équipe | Brancher les données du jury (configuration seulement) |
| [docs/API.md](docs/API.md) | intégrateurs | API de la passerelle, côté administration |
| [docs/API_USAGER.md](docs/API_USAGER.md) | intégrateurs | API côté usager (USSD, portail web) |
| [docs/DEPENDANCES.md](docs/DEPENDANCES.md) | tous | Composants, versions, licences |
| [LIMITES.md](LIMITES.md) | jury | Ce qui est simulé, ce qui n'est pas protégé |
| [FEUILLE_DE_ROUTE.md](FEUILLE_DE_ROUTE.md) | jury | Ce qui viendrait ensuite |
| [PROVENANCE.md](PROVENANCE.md) | jury | Code repris du sprint, code écrit pendant la finale |

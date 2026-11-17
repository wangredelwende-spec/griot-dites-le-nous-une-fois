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

## Les 3 épreuves du sujet, et où les voir

| Épreuve | Ce que fait le système | Où le voir dans la démo |
|---|---|---|
| **Ne transmettre que l'utile** | Chaque registre calcule la réponse chez lui et la **signe**. Il ne renvoie jamais la fiche : seulement « oui » ou « non » à la question posée. Exemple : pour le passeport, l'ONI reçoit « burkinabè : oui » et « interdiction de sortie du territoire : non ». Rien d'autre | [test-manuel](docs/test-manuel.md), scène 1 (passeport). Scène 1 bis : `python scripts/preuve_minimisation.py BF-0008` cherche les données de la personne partout hors des registres et ne les trouve pas |
| **Montrer à l'usager qui a consulté ses données** | Sur le téléphone (`*226#`), menu « Qui a consulté mes données » : qui, quand, pourquoi, sur quelle base, jamais la valeur. Chaque consultation donne un **reçu** de 16 caractères, qu'on retrouve dans un journal infalsifiable | [test-manuel](docs/test-manuel.md), scènes 3 et 8 |
| **Tenir quand un registre tombe en panne** | Registre coupé, lent ou qui répond une réponse falsifiée : refus clair, « rien n'a été deviné ». Une réponse partielle n'est jamais présentée comme un « oui » complet | [test-manuel](docs/test-manuel.md), scènes 1 ter, 6 et 9 ; `python scripts/panne.py` |

## Installation pas à pas (Windows, PowerShell)

**Prérequis** : Docker Desktop lancé, avec `docker compose` ; git ; Python 3 (les images utilisent Python 3.13) ;
ports 80 et 443 libres sur l'ordinateur. **Après l'installation, aucun accès à Internet n'est nécessaire.**

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
3. Démarrer : `docker compose up -d --wait`. Il y a 9 services : PostgreSQL, Keycloak, 3 registres, médiateur,
   guichet, USSD et Caddy. `docker compose ps` doit les montrer « healthy ».
4. Faire confiance au HTTPS local, qui est signé par l'autorité interne de Caddy :
   `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt caddy-racine.crt`, double-cliquer sur
   le fichier, Installer le certificat, Utilisateur actuel, « Autorités de certification racines de confiance ».
   Ce fichier n'est jamais commité.
5. Pour les scripts et les tests, créer un environnement Python :
   ```powershell
   python -m venv .venv
   .venv\Scripts\pip install -r mediateur\requirements.txt -r registres_sim\requirements.txt -r ussd_sim\requirements.txt -r tests\requirements.txt
   .venv\Scripts\python -m pytest tests
   ```
6. Ouvrir <https://guichet.griot.test> (agents) et <https://usager.griot.test> (téléphone simulé de l'usager).
   À la première connexion, chaque agent enregistre son code à 6 chiffres (TOTP) en scannant un QR code avec une
   application libre comme FreeOTP ou Aegis.

Avant une démo : remise à zéro des données (`python scripts\remise_a_zero.py --oui`, le journal est archivé,
jamais effacé). Sans réseau : `scripts\sauvegarder_hors_ligne.py` puis `scripts\charger_hors_ligne.py`.
Tout le détail est dans [docs/test-manuel.md](docs/test-manuel.md).

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

Usagers (téléphone simulé `*226#`) : numéro + code PIN. Exemple : `70000001`, PIN `1234` (Aminata Kaboré,
`BF-0001`). La liste complète est dans `ussd_sim/abonnes.yaml` et dans [docs/test-manuel.md](docs/test-manuel.md).
En production, l'usager se connecterait avec l'identifiant unique électronique (voir [LIMITES.md](LIMITES.md)).

## Licence

Le code est sous **AGPL-3.0** ([LICENSE](LICENSE)) : chacun peut l'utiliser, le modifier et le redistribuer.
Une version modifiée, même proposée seulement en ligne, doit publier son code sous la même licence.
Les composants utilisés et leurs licences : [docs/DEPENDANCES.md](docs/DEPENDANCES.md).

## Documentation

| Document | Pour qui | Contenu |
|---|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | jury, informaticiens | Composants, trajet d'une demande, qui voit quoi, pannes, choix techniques |
| [docs/SCENARIO_PASSEPORT.md](docs/SCENARIO_PASSEPORT.md) | tous | L'histoire de l'usager, avant et après |
| [docs/REGLES_DU_SOCLE.md](docs/REGLES_DU_SOCLE.md) | administrations | Les 10 règles, adoptables même sans notre logiciel |
| [docs/test-manuel.md](docs/test-manuel.md) | équipe, jury | Démo pas à pas, scène par scène |
| [docs/fiche-oral.md](docs/fiche-oral.md) | équipe | Réponses aux questions du jury |
| [docs/AJOUTER_UNE_DEMARCHE.md](docs/AJOUTER_UNE_DEMARCHE.md) | administrations | Ajouter une démarche avec un fichier YAML, sans code |
| [docs/JOUR_J_DONNEES_JURY.md](docs/JOUR_J_DONNEES_JURY.md) | équipe | Brancher les données du jury (configuration seulement) |
| [docs/API.md](docs/API.md) | intégrateurs | API du médiateur côté administration |
| [docs/API_USAGER.md](docs/API_USAGER.md) | intégrateurs | API côté usager (USSD, futur portail) |
| [docs/DEPENDANCES.md](docs/DEPENDANCES.md) | tous | Composants, versions, licences |
| [LIMITES.md](LIMITES.md) | jury | Ce qui est simulé, ce qui n'est pas protégé |
| [FEUILLE_DE_ROUTE.md](FEUILLE_DE_ROUTE.md) | jury | Ce qui viendrait ensuite |
| [PROVENANCE.md](PROVENANCE.md) | jury | Code repris du sprint, code écrit pendant la finale |

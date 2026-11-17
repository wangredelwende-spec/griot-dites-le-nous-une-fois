# Où trouver quoi

**Seule page qui contient les chemins des fichiers et les commandes.** Les autres documents parlent de couches et
d'outils, et renvoient ici.

> ⚠️ **Chemins provisoires** : relevés sur `main` au commit `2e2b4e4` (17/11/2026). L'arborescence va être
> réorganisée en **un dossier par couche**, comme le demande le sujet. Quand elle change, on met à jour cette
> page, et seulement elle.

Les commandes se tapent dans PowerShell, à la racine du dépôt.

## Socle commun

| Élément | Chemin actuel |
|---|---|
| Lancement de tous les services, réseaux sans Internet, volumes, secrets | `docker-compose.yml` |
| Modèle du fichier des secrets (à copier en `.env`) | `.env.example` |
| Entrée HTTPS (Caddy, autorité interne, en-têtes de sécurité) | `caddy/Caddyfile` |
| Base de données de Keycloak | `postgres/init-bases.sh` |
| Licence | `LICENSE` |
| Tests automatiques | `tests/` |
| Dépendances Python pour les tests et les scripts | `mediateur/requirements.txt`, `registres_sim/requirements.txt`, `ussd_sim/requirements.txt`, `tests/requirements.txt` |

## Couche 1 : Registres

> ⚠️ Le jury publiera un **contrat OpenAPI commun** pour les 3 registres. Ce qui suit décrit nos registres
> **simulés** actuels. Rien n'est définitif sur l'API des registres.

| Élément | Chemin actuel |
|---|---|
| Code du registre simulé (un seul code, trois instances) | `registres_sim/app/main.py` |
| Lecture d'un registre à partir d'un fichier YAML (identité, calcul, cas à refuser) | `registres_sim/app/adaptateur.py` |
| Formats de données lus (CSV, Excel, JSON, SQLite, SQL, PDF texte, API) | `registres_sim/app/sources.py` |
| Description de chaque registre (« adaptateur ») | `adaptateurs/etat-civil.yaml`, `adaptateurs/nationalite.yaml`, `adaptateurs/casier.yaml` |
| Données fictives et leur description | `registres_sim/donnees_fictives/` (voir `LISEZMOI.md`) |
| Lecture d'un PDF scanné (OCR, sans réseau) | `ocr/` |
| Relais vers l'API du jury (seul conteneur qui sort) | `relais_api_jury/` |
| Outils pour brancher les données du jury | `scripts/inspecter_donnees.py`, `scripts/tester_adaptateur.py`, `scripts/exporter_api_jury.py` |
| Procédure du jour J | `docs/JOUR_J_DONNEES_JURY.md`, `docs/A_TRANCHER_DONNEES_JURY.md` |

## Couche 2 : Passerelle d'échange

| Élément | Chemin actuel |
|---|---|
| Médiateur : réception des demandes, appel des registres en parallèle, remise | `mediateur/app/main.py` |
| Appel d'un registre (délai maximal) et vérification de sa réponse signée | `mediateur/app/registres.py` |
| Vérification du jeton de l'agent (Keycloak) | `mediateur/app/agents.py` |
| Réglages (adresses, délais) | `mediateur/app/config.py` ; valeurs dans `docker-compose.yml` (service `mediateur`) |
| Annuaire : services demandeurs et registres | `catalogue/annuaire.yaml` |
| API pour les administrations | `docs/API.md` |

## Couche 3 : Consentement et minimisation

| Élément | Chemin actuel |
|---|---|
| Catalogue des démarches (qui demande quoi, pourquoi, sur quelle base) | `catalogue/demarches.yaml` |
| Validation du catalogue et rechargement sans redémarrage | `mediateur/app/catalogue.py` |
| Attente de l'accord, confirmation, refus, retrait, expiration | `mediateur/app/main.py` |
| Double clé : services, paramètres et mode acceptés par chaque registre | `adaptateurs/*.yaml` (blocs `services`, `bases`) |
| Preuve que rien ne fuit | `scripts/preuve_minimisation.py` |
| Ajouter une démarche | `docs/AJOUTER_UNE_DEMARCHE.md`, exemples `docs/demarche_a_coller.yaml`, `docs/demarche_refusee.yaml` |
| Les 10 règles du socle | `docs/REGLES_DU_SOCLE.md` |

## Couche 4 : Journal de traçabilité

| Élément | Chemin actuel |
|---|---|
| Journal chaîné (SQLite, ajout seul) | `mediateur/app/journal.py` |
| Vérificateur : chaîne, reçu, double trace | `journal/verifier.py` |
| Double trace tenue par chaque registre | `registres_sim/app/main.py` (partie « trace ») |
| Démonstration d'une falsification | `scripts/falsifier_journal.py` |
| Archivage du journal avant une démo (jamais d'effacement) | `scripts/remise_a_zero.py` |

## Couche 5 : Espace usager

| Élément | Chemin actuel |
|---|---|
| Téléphone simulé `*226#` (USSD) | `ussd_sim/` |
| Portail web (`/portail`) | `portail_usager/` |
| Numéros et PIN de démonstration | `ussd_sim/abonnes.yaml` ; pour les données du jury : `scripts/annuaire_ussd.py` |
| API usager du médiateur (en attente, confirmer, refuser, retirer, historique) | `mediateur/app/main.py` ; contrat : `docs/API_USAGER.md` |
| Textes de l'USSD et du portail (français, mooré) | `traduction-moore/phrases-ussd.csv`, `traduction-moore/phrases-portail.csv` |
| Traduction mooré en cours (branche `docs-claude`) | `traduction-moore/A_TRADUIRE_MALKIRAM.xlsx`, `traduction-moore/A_RELIRE.md` |

## Bonus : Guichet

| Élément | Chemin actuel |
|---|---|
| Écran de l'agent et page Contrôle | `guichet/` |
| Comptes, groupes, rôles, mot de passe + TOTP | `keycloak/realm-griot.json` |
| Thème de la page de connexion (français, mooré) | `keycloak/themes/griot/`, `traduction-moore/phrases.csv`, `traduction-moore/integrer.py` |
| Demande en ligne de commande par un vrai agent | `scripts/demande.py` (avec `scripts/client_guichet.py`) |

## Bonus : Résilience

| Élément | Chemin actuel |
|---|---|
| Interrupteur de panne d'un registre | `scripts/panne.py` |
| Banc de pannes automatique | `scripts/banc_de_pannes.py` |
| Comptes de test du banc (activés seulement si `OUTILS_TEST=1`) | `scripts/outils_test.py` |
| Sauvegarde et rechargement des images sans réseau | `scripts/sauvegarder_hors_ligne.py`, `scripts/charger_hors_ligne.py` |
| Délais, limites de débit, durée de l'accord | `docker-compose.yml` (service `mediateur`) |

## Commandes

| Pour… | Commande actuelle |
|---|---|
| Démarrer | `docker compose up -d --wait` |
| Créer l'environnement Python | `python -m venv .venv` puis `.venv\Scripts\pip install -r mediateur\requirements.txt -r registres_sim\requirements.txt -r ussd_sim\requirements.txt -r tests\requirements.txt` |
| Lancer les tests | `.venv\Scripts\python -m pytest tests` |
| Faire confiance au HTTPS local | `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt caddy-racine.crt` |
| Remettre les données de démo à zéro | `python scripts\remise_a_zero.py --oui` |
| Voir l'état des registres | `python scripts\panne.py` |
| Mettre un registre en panne | `python scripts\panne.py <etat-civil\|nationalite\|casier> <coupe\|lent\|corrompu>` |
| Remettre un registre en état normal | `python scripts\panne.py <registre> normal` |
| Prouver la minimisation | `python scripts\preuve_minimisation.py BF-0008` |
| Vérifier le journal | `docker compose exec mediateur python /journal/verifier.py` |
| Vérifier un reçu | `docker compose exec mediateur python /journal/verifier.py --recu "9035 47b3 1c2e 9f04"` |
| Comparer le journal à la double trace | `docker compose exec mediateur python /journal/verifier.py --registres` |
| Falsifier une copie du journal (démo) | `python scripts\falsifier_journal.py` (ou `--cacher`) |
| Banc de pannes (avant la démo) | `python scripts\banc_de_pannes.py` |
| Sauvegarder les images | `python scripts\sauvegarder_hors_ligne.py` |
| Recharger les images sans réseau | `python scripts\charger_hors_ligne.py hors_ligne\griot-images-<date>.tar` |

## Adresses (fichier hosts → 127.0.0.1)

| Adresse | Pour |
|---|---|
| `https://guichet.griot.test` | agents ; page Contrôle : `/controle` |
| `https://usager.griot.test` | téléphone simulé `*226#` ; portail web : `/portail` |
| `https://auth.griot.test` | connexion Keycloak |

## Documents

| Document | Chemin |
|---|---|
| Architecture par couche | `docs/ARCHITECTURE.md` |
| Scénario du passeport | `docs/SCENARIO_PASSEPORT.md` |
| Démo pas à pas | `docs/test-manuel.md` |
| Réponses au jury | `docs/fiche-oral.md` |
| Dépendances et licences | `docs/DEPENDANCES.md` |
| Limites, feuille de route, provenance | `LIMITES.md`, `FEUILLE_DE_ROUTE.md`, `PROVENANCE.md` |

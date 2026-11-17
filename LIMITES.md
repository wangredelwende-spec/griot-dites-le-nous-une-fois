# Limites (faits bruts, complétés au fil de la finale)

## Ce qui est simulé

- **Registres** : `registres/`, données fictives (`registres/donnees_fictives/`), en attendant les données du jury.
- **Connexion des usagers** : USSD simulé, numéro + PIN fictifs (`espace-usager/ussd/abonnes.yaml` ; jour J : `donnees_jury/abonnes.yaml` produit par `scripts/annuaire_ussd.py` pour chaque citoyen), PIN de démo en clair, non hachés.
  En production : connexion par l'identifiant unique électronique.
- **Textes de loi** des démarches : références à faire valider (voir `consentement-minimisation/catalogue/`).

- **Portail web usager** (`/portail`) : même connexion que l'USSD (numéro + PIN de démo). Le compteur de PIN faux
  est tenu par chaque écran, en mémoire : 3 essais sur l'USSD et 3 sur le portail par période de 5 minutes, remis
  à zéro si l'écran redémarre. En production : PIN (ou identifiant unique électronique) géré par le fournisseur
  d'identité, compteur unique. Portail en français seulement : les noms des services et des attributs viennent du
  catalogue, écrit en français (`traduction-moore/phrases-portail.csv` est prêt, colonne mooré vide).

## Règles de données à confirmer

- **Personne absente du casier** : le vrai casier ne contient que les condamnations ; une personne jamais condamnée
  n'y figure pas. Réglable dans `registres/adaptateurs/casier.yaml` :
  - `absence: refus` (par défaut) : absent → « réponse impossible » (on ne devine pas) ;
  - `absence: vierge` : absent → « casier vierge », **après** vérification par le médiateur, à l'état civil, que la
    personne existe (une seule fiche, vivante). Sinon : « identité non confirmée ». État civil en panne : « identité non
    vérifiable, rien n'a été deviné ».
  Limite de `vierge` : on suppose que l'identifiant du casier est le même que celui de l'état civil.
- **Double nationalité** : la façon dont le registre de la nationalité l'écrit est inconnue (voir `docs/A_TRANCHER_DONNEES_JURY.md`).

## Fonctions désactivées (conservées dans le code, non supprimées)

Décision du 17/11 : la remise suit le cadre de la finale ; ce qui suit existe encore mais ne fait pas partie de la démonstration.

| Fonction | État | Pour la réactiver |
|---|---|---|
| Quota 5 demandes / 24 h par service et par personne | désactivé (0) | `LIMITE_PAR_CITOYEN: "5"` |
| Conversion OCR / PDF / Excel des données du jury | profil docker `ocr`, jamais démarré | `docker compose --profile ocr up` |
| Relais vers l'API du jury (`relais-api-jury`) | profil docker `api-jury`, jamais démarré | `--profile api-jury` |
| Mooré | non proposé : aucune langue complète (colonnes vides dans `traduction-moore/`), l'écran reste en français | traduire, puis `integrer.py` |
| Signature Ed25519 des réponses des registres + double clé côté registre | **à désactiver à l'adaptation des registres au contrat du jury** (le contrat ne prévoit pas de signature) | — |
| Double trace des registres (`verifier.py --registres`) | idem, liée à la signature | — |

## Appels aux registres et clés API (17/11)

- Délai de 2 s par essai (`DELAI_REGISTRE`) et **un seul réessai**, seulement si le registre ne répond pas à temps ou est
  injoignable. Un 404 n'est jamais réessayé.
- Codes de la passerelle : **503** `REGISTRE_INDISPONIBLE` (démarche « en attente », rien n'est deviné), **404**
  `CITOYEN_INCONNU`, **403** `HORS_CATALOGUE` (démarche, attributs ou finalité non prévus). Le corps contient toujours la
  demande et son motif.
- Une clé API par administration (en-tête `X-Cle-Api`), empreinte SHA-256 dans `annuaire.yaml`. Les clés du dépôt
  (`cle-demo-…`) sont des **clés de démonstration publiques**. Une demande par clé API n'a **pas de jeton Keycloak** : les
  registres actuels, qui exigent ce jeton (double clé), la refusent tant qu'ils ne sont pas adaptés au contrat du jury.
- Clé API d'un registre : `en_tete_cle` + `cle_secret` dans `annuaire.yaml` (nom de l'en-tête, fichier dans `/run/secrets`).
  Aucun registre n'en déclare pour l'instant : l'en-tête attendu dépend du contrat du jury.

## Limites de débit (démonstration)

- Quota « 5 demandes par service et par personne en 24 h » (`LIMITE_PAR_CITOYEN`) : **désactivé** (valeur 0),
  il bloquerait l'épreuve en direct. Le code est conservé : mettre `LIMITE_PAR_CITOYEN: "5"` dans `docker-compose.yml`
  pour le réactiver (refus + alerte dans l'historique du citoyen).
- Limite « trop de citoyens différents par agent et par heure » (`LIMITE_SUJETS`) : **désactivée** (0). Le banc de pannes
  l'active (5) seulement pour le scénario « agent curieux », en écrivant `/donnees/limite_sujets`, puis la retire.
- Les comptes des tests de bout en bout (`agent.banc`, `agent.banc.cefore`) en sont exemptés (`LIMITE_EXEMPTES` dans
  `docker-compose.yml`) **seulement si `OUTILS_TEST=1`** (mode test) : ils interrogent des dizaines de fois les mêmes
  citoyens fictifs. Avec `OUTILS_TEST=0` (démonstration), ils suivent les limites comme tout le monde.
  **En production : aucune exemption.**

## Comptes de test

- `outil-test-concours`, `outil-test-cefore`, `outil-test-curieux` : comptes de service Keycloak (secret client, sans
  humain ni TOTP) pour le banc de pannes et `scripts/demande.py`. Ils n'existent que si `OUTILS_TEST=1` dans `.env`
  (`scripts/outils_test.py`) ; sinon le médiateur ET les registres refusent leurs jetons. Mêmes règles que les agents.
  Leur nom (« service-account-outil-test-… ») les signale dans le journal. Désactivés pendant la démonstration.

## Confiance entre composants

- Chaque registre vérifie lui-même le jeton Keycloak de l'agent (signature, expiration, rôle, groupe). Il fait donc
  confiance à **Keycloak** (ses clés publiques, lues sur le réseau interne `cles-agents`). Un Keycloak compromis
  pourrait fabriquer de faux agents : c'est le point de confiance commun.
- Le jeton présenté au registre est celui émis pour le médiateur (audience `mediateur`) : un jeton par registre
  (échange de jeton) serait plus strict (voir FEUILLE_DE_ROUTE).
- Le médiateur lit les adaptateurs des registres (lecture seule) pour valider le catalogue ; en production, chaque
  registre publierait sa description signée.

- **Le registre ne peut pas vérifier que l'usager a vraiment confirmé.** Il répond (et signe) AVANT l'accord : la
  réponse est gardée en attente par le médiateur, qui ne la remet qu'après la confirmation. C'est donc le médiateur
  qui fait respecter le consentement. Un médiateur compromis qui remettrait une réponse sans accord ne passerait
  pas inaperçu : (1) la consultation apparaît dans l'historique de l'usager (« Qui a consulté mes données »), qui
  voit « transmis » ou « accordé » sans avoir rien confirmé et n'a aucun reçu pour cette ligne ; (2) le registre
  garde SA propre trace des réponses qu'il a signées (double trace, hors de portée du médiateur) : une consultation
  effacée du journal du médiateur y reste visible (`verifier.py --registres`). Feuille de route : accord signé par
  l'usager lui-même (clé sur son téléphone), vérifiable par le registre.

## Ce que voit le médiateur

- La réponse minimale signée (ex. « nationalité burkinabè : oui »), gardée en attente jusqu'au consentement, puis effacée.
- Jamais la fiche, jamais la date de naissance, jamais le détail du casier.

## Ce qui n'est pas protégé

- « Registre indisponible » n'est pas signé (par définition, le registre n'a pas répondu).
- Supprimer des lignes puis recalculer toute la chaîne n'est pas détectable par la chaîne seule. C'est détecté par :
  les reçus déjà remis aux usagers, et la **double trace** (`verifier.py --registres`) pour toute consultation
  qui a atteint un registre. Une demande refusée par le médiateur avant tout registre (ex. mauvaise finalité)
  n'a pas de seconde trace : seul le reçu, ou une ancre externe (feuille de route), la protège.
- La trace d'un registre est exportée signée sur le réseau interne `registres`, sans authentification du lecteur : elle
  ne contient ni citoyen ni valeur (numéro de demande, jti, date, service, attribut, ok/refus).

## Mineurs

- **Le consentement d'un mineur par son représentant légal n'est pas traité.** Dans la démo, l'usager mineur
  confirme lui-même sur son téléphone. Le passeport ne demande pas l'âge (l'ONI le connaît déjà par
  l'enrôlement de la CNIB) : l'autorisation parentale d'un mineur reste traitée hors du système. La loi n°001-2021
  confie ce consentement au représentant légal : voir `FEUILLE_DE_ROUTE.md`.

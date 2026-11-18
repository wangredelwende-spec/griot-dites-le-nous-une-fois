# Limites (faits bruts, complétés au fil de la finale)

## Ce qui est simulé

- **Registres** : `registres/`, registres simulés selon notre contrat (`registres/contrat/contrat-registres.yaml`),
  données fictives (`registres/donnees/citoyens-fictifs.yaml`). Aucun contrat commun n'est imposé (confirmé oralement par les organisateurs le 17 novembre 2026).
- **Connexion des usagers** : USSD simulé, numéro + PIN fictifs (`espace-usager/ussd/abonnes.yaml`), PIN de démo en clair, non hachés.
  En production : connexion par l'identifiant unique électronique.
- **Textes de loi** des démarches : aucun texte non vérifié n'est cité ; la base légale du concours est décrite sans
  numéro de loi, à confirmer par l'administration du concours. Seuil d'âge : seuil configurable (18 ans par défaut).

## Limites reconnues (audit du 18/11)

- **Journal** : toute modification ou suppression d'une ligne est détectée (chaînage SHA-256, `verifier.py`,
  `/journal/verification`). En revanche, **une réécriture complète de la chaîne** (toutes les empreintes recalculées par
  quelqu'un qui a accès au fichier SQLite) **n'est pas détectée** sans ancrage externe (publication régulière de la
  dernière empreinte hors du serveur). Les reçus remis aux usagers et la double trace des registres (désactivée) ne
  couvrent qu'une partie des cas.
- **Lecture avant l'accord** : pour le CEFORE et le certificat de nationalité, la passerelle **lit les registres avant
  l'accord** de l'usager, pour lui montrer l'aperçu exact ; la réponse minimisée attend dans la base du médiateur, puis
  est effacée à la remise, au refus ou à l'expiration. **L'accord porte sur la TRANSMISSION**, pas sur la lecture. La
  lecture figure dans l'historique de l'usager, même s'il refuse.
- **Registre externe** : pour être branché par configuration seule, le registre d'une autre équipe doit renvoyer une
  fiche **JSON à plat** (un champ = une valeur), en **GET**, avec **l'identifiant du citoyen dans l'adresse**, le même
  identifiant que le nôtre, et une **date de naissance AAAA-MM-JJ**. Une valeur de nationalité absente des
  `correspondances` de `attributs.yaml` donne un refus. Un registre qui renvoie déjà un oui/non (ex. « majeur : true »),
  une fiche imbriquée, un POST ou un autre format de date demande du code.
- **Pseudonymisation** : le citoyen est pseudonymisé dans le journal (HMAC de son identifiant), mais **la clé est sur le
  même serveur** que le journal : l'administrateur du serveur peut ré-identifier. En production : clé dans un coffre
  séparé, accès journalisé.

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
- **Double nationalité** : non représentée (un seul champ `nationalite` dans notre contrat).

## Fonctions désactivées (conservées dans le code, non supprimées)

Décision du 17/11 : la remise suit le cadre de la finale ; ce qui suit existe encore mais ne fait pas partie de la démonstration.

| Fonction | État | Pour la réactiver |
|---|---|---|
| Quota 5 demandes / 24 h par service et par personne | désactivé (0) | `LIMITE_PAR_CITOYEN: "5"` |
| Conversion OCR / PDF / Excel des données du jury | profil docker `ocr`, jamais démarré | `docker compose --profile ocr up` |
| Relais vers l'API du jury (`relais-api-jury`) | profil docker `api-jury`, jamais démarré | `--profile api-jury` |
| Mooré | non proposé : aucune langue complète (colonnes vides dans `traduction-moore/`), l'écran reste en français | traduire, puis `integrer.py` |
| Démarches passeport, bourse nationale, vérification de la majorité (+ services bourses, mairie, passeport, attribut « interdiction de sortie du territoire ») | retirées du catalogue actif le 17/11 : `consentement-minimisation/catalogue/demarches-inactives.yaml` (non chargé) ; les services sont retirés de `annuaire.yaml`, les groupes Keycloak de `realm-griot.json` | recopier le bloc dans `demarches.yaml`, ré-ajouter le service |
| Signature Ed25519 des réponses des registres, jeton Keycloak vérifié par chaque registre, double clé côté registre | **désactivés le 17/11** : les registres suivent le contrat (fiche JSON, 404) ; `registres/app/ancien_main.py`, `adaptateur.py`, `sources.py` et `registres/adaptateurs/*.yaml` sont conservés, plus utilisés par la pile ; `passerelle/app/registres.py` garde `appeler()` / `verifier()` ; le guichet garde `verifier_volet()` | rebrancher `ancien_main` dans le Dockerfile des registres |
| Double trace des registres (`verifier.py --registres`) | désactivée avec la signature : les registres ne tiennent plus de trace ; le code de comparaison reste testé | idem |

## Registres selon notre contrat (17/11)

- Chaque équipe définit ses registres. Les nôtres : `registres/contrat/contrat-registres.yaml` (une route par registre,
  404 si le citoyen est inconnu) et `registres/donnees/citoyens-fictifs.yaml` (10 citoyens fictifs).
  `correspondance.yaml` relie leurs noms de champs à la passerelle.
- Registre d'une autre équipe : `annuaire.yaml` (adresse, route, son contrat copié dans `catalogue/contrats/`) +
  `correspondance.yaml`, relus à chaud (`docs/brancher-un-registre.md`). Limites : fiche JSON « à plat », identifiant
  dans la route, même identifiant de citoyen des deux côtés.
- **Réseau** : la passerelle seule est reliée à `sortie-registres`, un réseau AVEC sortie, pour joindre le registre
  d'une autre équipe sur le réseau local. Elle n'appelle que les adresses de `annuaire.yaml`, mais rien ne l'empêche
  techniquement de joindre Internet : en production, un pare-feu limiterait cette sortie aux registres déclarés.
- **Nos registres publiés** (ports 8101, 8102, 8103 sur toutes les interfaces de la machine) par `vitrine-registres`,
  GET seulement, **sans authentification** ni chiffrement (HTTP) : données fictives uniquement. Les registres eux-mêmes
  restent sans sortie. En production : clé API ou TLS mutuel par administration, jamais de publication ouverte.
- La passerelle appelle chaque registre en GET, valide la réponse contre le contrat (`jsonschema`, MIT), puis calcule
  l'attribut permis (`regles_attributs/minimisation.py`) : la fiche brute ne sort pas de la passerelle. Réponse non
  conforme : rejetée, ligne d'alerte « réponse corrompue : non conforme au contrat ». Citoyen inconnu : 404.
  Décédé ou donnée insuffisante (« né vers 1990 » pour une naissance exacte) : refus au motif générique.
- **Plus de confidentialité côté registre** : un registre répond à qui l'appelle ; seule la passerelle (réseau Docker
  « registres », sans Internet) y accède. La signature, le jeton de l'agent et les doubles clés du registre ne protègent plus.
  La passerelle garde ses propres contrôles : service autorisé par attribut (`attributs.yaml`), finalité, base, accord.
- Le « casier vierge » d'un citoyen absent du casier n'existe plus : un 404 du casier est un refus « citoyen inconnu ».
- Panne par variable d'environnement `PANNE` (normal, lent, eteint, non_conforme) ; `resilience/panne.py`.
- Le banc de pannes (`resilience/banc_de_pannes.py`, 13 situations) et `tests/e2e/` suivent les registres selon le
  contrat (18/11). Ancien banc signé : `resilience/ancien/`, non utilisé. Tests de l'ancien code des registres conservés
  (`registres/tests/`, via `ancien_main`).
- `/journal/verification` (public) ne donne ni le nombre de lignes ni aucune donnée : seulement intègre / première
  ligne modifiée.

## Catalogue du cadre, accords et minimisation (17/11)

- Trois démarches actives : concours direct (base légale : majeur, nationalité, casier vierge), entreprise individuelle au
  CEFORE (consentement 7 jours : identité, casier vierge), certificat de nationalité (consentement 24 h : naissance et
  filiation, pour le tribunal). **Les durées (168 h et 24 h) sont des choix de l'équipe, à confirmer.** Le concours est en
  base légale : pas d'accord à donner, la consultation figure dans l'historique avec son texte.
- Accord par démarche : donné quand l'usager confirme, enregistré (table `accords`, sans valeur), valable
  `duree_accord_heures`, retirable. Accord valide : la même démarche pour le même service est remise immédiatement
  (ligne `accord-valide` au journal). Retrait, expiration : l'usager est de nouveau consulté.
- Identité et naissance/filiation sont des **valeurs précises** (pas un oui/non) : le registre simulé les renvoie par la
  règle `champs` (exactement les cases déclarées), l'usager les voit mot pour mot dans l'aperçu avant l'envoi.
- `catalogue/correspondance.yaml` : seul fichier où les noms de champs des registres sont écrits.
  `regles_attributs/minimisation.py` calcule majeur, nationalité, casier, identité, naissance et filiation depuis la
  fiche brute, dans la passerelle.
- Keycloak : `realm-griot.json` décrit les nouveaux groupes et comptes (CEFORE, tribunal), mais une pile **déjà
  installée** ne les a pas : à ajouter dans la console Keycloak (ou réimporter le realm) avant de tester le guichet.
- Textes mooré : `phrases-ussd.csv` a reçu des lignes françaises pour les nouveaux services et attributs ; les colonnes
  mooré restent vides (rien n'est inventé). Les anciennes lignes (bourses, passeport…) sont conservées.
- Le banc de pannes joue les 3 démarches par clé API ; `tests/e2e` joue le concours au guichet (mot de passe + TOTP) et
  CEFORE au portail et à l'USSD. Le certificat de nationalité n'a pas de compte de test au guichet : il est joué par le banc.

## Appels aux registres et clés API (17/11)

- Délai de 2 s par essai (`DELAI_REGISTRE`) et **un seul réessai**, seulement si le registre ne répond pas à temps ou est
  injoignable. Un 404 n'est jamais réessayé.
- Codes de la passerelle : **503** `REGISTRE_INDISPONIBLE` (démarche « en attente », rien n'est deviné), **404**
  `CITOYEN_INCONNU`, **403** `HORS_CATALOGUE` (démarche, attributs ou finalité non prévus). Le corps contient toujours la
  demande et son motif.
- Une clé API par administration (en-tête `X-Cle-Api`), empreinte SHA-256 dans `annuaire.yaml`. Les clés du dépôt
  (`cle-demo-…`) sont des **clés de démonstration publiques**. Une demande par clé API n'a **pas de jeton Keycloak** : les
  registres selon notre contrat ne vérifient pas de jeton (voir « Fonctions désactivées »).
- Clé API d'un registre : `en_tete_cle` + `cle_secret` dans `annuaire.yaml` (nom de l'en-tête, fichier dans `/run/secrets`).
  Aucun de nos registres n'en déclare ; à remplir si le registre d'une autre équipe en exige une.

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
  l'enrôlement de la CNIB) : l'autorisation parentale d'un mineur reste traitée hors du système. La loi sur la protection des données personnelles (texte à vérifier) confie ce consentement au représentant légal : voir `FEUILLE_DE_ROUTE.md`.

# Limites (faits bruts, complétés au fil de la finale)

## Ce qui est simulé

- **Registres** : `registres_sim/`, données fictives (`registres_sim/donnees_fictives/`), en attendant les données du jury.
- **Connexion des usagers** : USSD simulé, numéro + PIN fictifs (`ussd_sim/abonnes.yaml`, PIN en clair pour la démo).
  En production : connexion par l'identifiant unique électronique.
- **Textes de loi** des démarches : références à faire valider (voir `catalogue/`).

## Règles de données à confirmer

- **Personne absente du casier** : le vrai casier ne contient que les condamnations ; une personne jamais condamnée
  n'y figure pas. Réglable dans `adaptateurs/casier.yaml` :
  - `absence: refus` (par défaut) : absent → « réponse impossible » (on ne devine pas) ;
  - `absence: vierge` : absent → « casier vierge », **après** vérification par le médiateur, à l'état civil, que la
    personne existe (une seule fiche, vivante). Sinon : « identité non confirmée ». État civil en panne : « identité non
    vérifiable, rien n'a été deviné ».
  Limite de `vierge` : on suppose que l'identifiant du casier est le même que celui de l'état civil.
- **Double nationalité** : la façon dont le registre de la nationalité l'écrit est inconnue (voir `docs/A_TRANCHER_DONNEES_JURY.md`).

## Limites de débit (démonstration)

- Un même service ne peut pas faire plus de 5 demandes sur une même personne en 24 h (`LIMITE_PAR_CITOYEN`) :
  au-delà, refus + alerte dans l'historique du citoyen.
- Les comptes des tests automatiques (`agent.banc`, `agent.banc.bourses`) en sont exemptés (`LIMITE_EXEMPTES` dans
  `docker-compose.yml`) : ils interrogent des dizaines de fois les mêmes citoyens fictifs. **En production : aucune exemption.**

## Confiance entre composants

- Chaque registre vérifie lui-même le jeton Keycloak de l'agent (signature, expiration, rôle, groupe). Il fait donc
  confiance à **Keycloak** (ses clés publiques, lues sur le réseau interne `cles-agents`). Un Keycloak compromis
  pourrait fabriquer de faux agents : c'est le point de confiance commun.
- Le jeton présenté au registre est celui émis pour le médiateur (audience `mediateur`) : un jeton par registre
  (échange de jeton) serait plus strict (voir FEUILLE_DE_ROUTE).
- Le médiateur lit les adaptateurs des registres (lecture seule) pour valider le catalogue ; en production, chaque
  registre publierait sa description signée.

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

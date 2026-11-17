# Couche « registres »

**Rôle** : détenir la donnée des citoyens (registres SIMULÉS, données fictives) et la servir **selon le contrat
commun** des trois registres : état civil, nationalité, casier judiciaire.

Contrat : `contrat/contrat-registres.yaml` (le nôtre ; pas de contrat commun imposé). Une route par registre :
`GET /etat-civil/{id}`, `GET /nationalite/{id}`, `GET /casier/{id}` → la fiche du citoyen (exactement les champs du
schéma de la réponse 200), ou **404** s'il est inconnu. Citoyens fictifs : `donnees/citoyens-fictifs.yaml`.

Un seul code (`app/main.py`), trois instances (docker-compose.yml) ; tout vient de la configuration :
`GRIOT_CONTRAT` (le contrat), `GRIOT_CITOYENS` (la liste), `REGISTRE_CHEMIN` (la route de cette instance),
`PANNE` (normal | lent | eteint | non_conforme, lue à chaque appel ; `resilience/panne.py`).

Le registre ne calcule rien : c'est la **passerelle** qui valide la réponse contre le contrat puis ne garde que l'utile
(couche consentement-minimisation). Joignable seulement par la passerelle (réseau Docker `registres`, sans Internet) ;
**aucune authentification côté registre** (LIMITES.md).

## Désactivé (conservé, plus utilisé par la pile)

L'ancien registre « signé » : `app/ancien_main.py` (signature Ed25519, jeton Keycloak, double clé, double trace),
`app/adaptateur.py`, `app/sources.py` (CSV, JSON, SQL, Excel, PDF, API), `adaptateurs/`, `donnees_fictives/`, `import/ocr/`,
`requirements-ancien.txt`. Leurs tests restent dans `tests/` (test_adaptateur, test_registre, test_formats).

## Contrat et tests

`openapi.yaml` = le contrat des registres (généré depuis `contrat/contrat-registres.yaml`). Tests :
`tests/test_registre_contrat.py` (chaque citoyen conforme au contrat, 404, champs exposés, pannes) et
`tests/test_schemathesis.py` (tests générés depuis le contrat de `GRIOT_CONTRAT`).

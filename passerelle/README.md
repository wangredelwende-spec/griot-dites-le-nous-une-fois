# Couche « passerelle d'échange »

**Rôle** : faire circuler les pièces entre administrations plutôt que les usagers entre les guichets.
Service Docker `mediateur` (nom inchangé), réseau interne seulement, jamais publié par Caddy.

## Parcours d'une demande

1. Le guichet envoie `POST /demandes` avec le jeton Keycloak de l'agent. Le service demandeur vient du **groupe
   de l'agent dans son jeton**, jamais du formulaire.
2. Contrôles : démarche autorisée pour ce service, attributs et finalité exactement ceux du catalogue, limites
   de débit (trop de citoyens différents, trop de demandes sur la même personne : blocage et alerte).
3. Un appel par attribut, **en parallèle**, chacun à son registre, avec un délai total de 3 s. Le jeton de l'agent
   est transmis : le registre le vérifie lui-même (double clé).
4. Chaque réponse est vérifiée : signature Ed25519 avec la clé publique du registre (volume en lecture seule),
   `iss`, `aud`, `exp`, numéro de demande, `jti` jamais vu, forme exacte. Un écart : refus et ligne d'alerte.
5. Base légale : remise immédiate. Consentement : la réponse attend l'usager (couche consentement et
   minimisation), puis elle est remise une fois et **effacée**.

Registre en panne ou trop lent : « indisponible, rien n'a été deviné », pour lui seul ; jamais de « oui » global
partiel.

## Ce que contient la couche

| Fichier | Rôle |
|---|---|
| `app/main.py` | routes du guichet et du contrôleur, appel des registres, limites de débit |
| `app/registres.py` | appel HTTP avec délai et vérification complète de la réponse signée |
| `app/agents.py` | vérification du jeton Keycloak (agent, contrôleur) |
| `sortie/relais.py` | relais vers l'API du jury, seulement si elle est imposée en direct (profil `api-jury`) |

Un seul processus fait tourner trois couches : la passerelle, `consentement-minimisation/consentement/` et
`journal/tracabilite/` (copiées dans l'image, voir `Dockerfile`). Chaque route porte l'étiquette de sa couche.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : `POST /demandes`, `GET /demandes/{id}`,
`GET /catalogue`, `GET /controle` (rôle `controleur`, lecture seule). Exemples : `docs/API.md`.

## Tests

`passerelle/tests/` : signature valide ou fausse, délai dépassé, rejeu, finalité, limites, casier absent,
relais. `.venv\Scripts\python -m pytest passerelle\tests`.

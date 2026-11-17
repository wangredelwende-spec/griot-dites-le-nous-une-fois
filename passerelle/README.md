# Couche « passerelle d'échange »

**Rôle** : faire circuler les pièces entre administrations plutôt que les usagers entre les guichets.
Service Docker `mediateur` (nom inchangé), réseau interne seulement, jamais publié par Caddy.

## Parcours d'une demande

1. Une administration envoie `POST /demandes` : par le guichet (jeton Keycloak de l'agent, service = son groupe) ou
   directement avec **sa clé API** (`X-Cle-Api`, empreinte dans `annuaire.yaml`). Jamais le service du formulaire.
2. Contrôles : démarche autorisée pour ce service, attributs et finalité exactement ceux du catalogue → sinon **403**.
3. Un appel par registre utile, **en parallèle** : `GET {url}{chemin}` (annuaire.yaml), 2 s par essai, **1 réessai**.
4. Chaque réponse est **validée contre le contrat** (`GRIOT_CONTRAT`, `app/contrat.py`, jsonschema) : non conforme →
   rejetée, ligne d'alerte. 404 → citoyen inconnu (**404**). Injoignable ou trop lent → **503** `REGISTRE_INDISPONIBLE`,
   démarche « en attente », rien n'a été deviné.
5. Minimisation (`regles_attributs/minimisation.py`, `correspondance.yaml`) : seuls les attributs permis sortent
   (« majeur : oui »), jamais la fiche brute. Base légale : remise immédiate ; consentement : accord de l'usager
   (ou accord encore valable), puis remise une fois et **effacée**.

Tout passe au journal ; une erreur imprévue donne un 503 propre, jamais un plantage.

## Ce que contient la couche

| Fichier | Rôle |
|---|---|
| `app/main.py` | routes, appel des registres en parallèle, minimisation, limites de débit, contrôle |
| `app/registres.py` | appel HTTP (délai, réessai, 404) ; `appeler()`/`verifier()` = ancien flux signé, désactivé |
| `app/contrat.py` | validation d'une réponse contre le contrat configuré |
| `app/agents.py` | jeton Keycloak (agent, contrôleur) ou clé API d'une administration |
| `sortie/relais.py` | relais vers une API du jury (profil `api-jury`, désactivé) |

Un seul processus fait tourner trois couches : la passerelle, `consentement-minimisation/` et `journal/tracabilite/`.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : `POST /demandes`, `GET /demandes/{id}`,
`GET /catalogue`, `GET /controle` (rôle `controleur`, lecture seule) ; codes 403 / 404 / 503. Exemples : `docs/API.md`.

## Tests

`passerelle/tests/` : signature valide ou fausse, délai dépassé, rejeu, finalité, limites, casier absent,
relais. `.venv\Scripts\python -m pytest passerelle\tests`.

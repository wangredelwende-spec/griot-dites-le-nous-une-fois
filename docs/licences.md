# Briques réutilisées et licences

Code de Griot : **AGPL-3.0** (`LICENSE`). Toutes les briques ci-dessous sont libres.

Relevé du 18/11/2026 sur `main` : versions lues dans les `requirements.txt` et `docker-compose.yml`, licences lues dans
les **métadonnées des paquets installés** (`License-Expression`, sinon classifieur « License :: ») et dans les
**étiquettes des images Docker** (`org.opencontainers.image.licenses`). Quand l'image ne porte pas d'étiquette, c'est
indiqué.

## Paquets Python de la pile (images construites)

| Paquet | Version | Licence (métadonnées) | Utilisé par |
|---|---|---|---|
| fastapi | 0.163.1 | MIT | passerelle, registres, guichet-agent, portail, USSD |
| uvicorn | 0.54.0 | BSD-3-Clause | passerelle, registres, guichet-agent, portail, USSD |
| pyyaml | 6.0.3 | MIT | passerelle, registres, guichet-agent, portail, USSD |
| httpx | 0.28.1 | BSD-3-Clause | passerelle, guichet-agent, portail, USSD |
| jsonschema | 4.23.0 | MIT | passerelle (validation des réponses des registres contre le contrat) |
| pyjwt[crypto] | 2.15.1 | MIT | passerelle, guichet-agent (jetons Keycloak) |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | passerelle, guichet-agent |
| authlib | 1.9.8 | BSD-3-Clause | guichet-agent (connexion OpenID Connect) |
| jinja2 | 3.1.6 | BSD (classifieur « BSD License ») | guichet-agent, portail, USSD (pages HTML) |
| itsdangerous | 2.2.0 | BSD (classifieur « BSD License ») | guichet-agent, portail, USSD (sessions signées) |
| python-multipart | 0.0.34 | Apache-2.0 | guichet-agent, portail, USSD (formulaires) |

## Outils de test et de démonstration (`tests/requirements.txt`, jamais dans les images)

| Paquet | Version | Licence (métadonnées) | Usage |
|---|---|---|---|
| pytest | 8.4.2 | MIT | suite de tests |
| respx | 0.23.1 | BSD-3-Clause | registres simulés dans les tests |
| schemathesis | 3.39.16 | MIT | tests générés depuis le contrat des registres |
| pyotp | 2.12.0 | MIT | code TOTP des comptes de test (e2e) |
| playwright | 1.58.0 | Apache-2.0 | `scripts/video_demo.py` (clics de la vidéo, avec Edge déjà installé) |
| openpyxl | 3.1.5 | MIT | tests de l'ancien import (désactivé) |
| pdfplumber | 0.11.10 | MIT | tests de l'ancien import (désactivé) |

## Images Docker

| Image | Rôle | Licence |
|---|---|---|
| `python:3.13.5-slim-bookworm` | base de nos 5 images (passerelle, registres, guichet, portail, USSD) | pas d'étiquette dans l'image ; Python : PSF License ; Debian : paquets libres (licences diverses) |
| `quay.io/keycloak/keycloak:26.8.1` | authentification des agents (mot de passe + TOTP) | Apache-2.0 (étiquette de l'image) |
| `postgres:17.11-alpine` | base de Keycloak | pas d'étiquette dans l'image ; PostgreSQL License |
| `caddy:2.11.7-alpine` | HTTPS interne et vitrine de nos registres | Apache-2.0 (étiquette de l'image) |

Logiciels utilisés sans être redistribués : Docker Engine / Docker Compose (Apache-2.0), SQLite (domaine public,
inclus dans Python).

Profils désactivés, jamais démarrés pendant la démonstration (`ocr`, `api-jury`) : non relevés ici.

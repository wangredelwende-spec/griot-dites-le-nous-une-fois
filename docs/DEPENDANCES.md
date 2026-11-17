# Dépendances : versions, licences, rôles

Notre code est sous **AGPL-3.0** ([LICENSE](../LICENSE)). Cette page liste tout ce qu'il utilise.

**D'où viennent les informations (relevé du 17/11/2026, `main` au commit `053d043`)**

- **Versions** : lues dans les fichiers du projet (`*/requirements.txt`, `docker-compose.yml`, `*/Dockerfile`).
  Toutes sont épinglées : jamais « latest ».
- **Licences des bibliothèques Python** : lues dans les métadonnées officielles de chaque paquet, à la version
  exacte (fichiers `.whl` téléchargés depuis PyPI, sans rien installer).
- **Licences des images Docker et des outils** : elles ne figurent pas dans les fichiers du dépôt. Nous indiquons
  celle que publie chaque projet ; elle est marquée « (amont) ».

## 1. Bibliothèques Python, épinglées par le projet

| Bibliothèque | Version | Licence | Rôle | Utilisée par |
|---|---|---|---|---|
| FastAPI | 0.163.1 | MIT | Serveur web (API et pages) | guichet, médiateur, registres, USSD |
| Uvicorn | 0.54.0 | BSD-3-Clause | Lance le serveur web | guichet, médiateur, registres, USSD |
| Jinja2 | 3.1.6 | BSD-3-Clause | Pages HTML rendues par le serveur | guichet, USSD |
| python-multipart | 0.0.34 | Apache-2.0 | Lecture des formulaires | guichet, USSD |
| itsdangerous | 2.2.0 | BSD-3-Clause | Cookie de session signé | guichet, USSD |
| HTTPX | 0.28.1 | BSD-3-Clause | Appels HTTP avec délai maximal | guichet, médiateur, USSD, scripts |
| Authlib | 1.9.8 | BSD-3-Clause | Connexion des agents par Keycloak (OpenID Connect) | guichet |
| PyJWT (extra `crypto`) | 2.15.1 | MIT | **Signature** et vérification des réponses (EdDSA / Ed25519) | guichet, médiateur, registres |
| cryptography | 50.0.2 | Apache-2.0 OU BSD-3-Clause | Clés Ed25519, utilisées par PyJWT | guichet, médiateur, registres |
| PyYAML | 6.0.3 | MIT | Lecture du catalogue et des adaptateurs | guichet, médiateur, registres, USSD, scripts |
| openpyxl | 3.1.5 | MIT | Lecture de données Excel (.xlsx) | registres, tests |
| pdfplumber | 0.11.10 | MIT | Lecture de données PDF (texte) | registres, tests |

Outils de test (`tests/requirements.txt`) :

| Bibliothèque | Version | Licence | Rôle |
|---|---|---|---|
| pytest | 9.2.0 | MIT | Lance les tests |
| respx | 0.23.1 | BSD-3-Clause | Simule les registres dans les tests (panne, lenteur, fausse signature) |
| PyOTP | 2.12.0 | MIT | Calcule le code TOTP des comptes de test (scripts du banc) |

La bibliothèque standard de Python fournit le reste : `hashlib` (SHA-256 du journal), `hmac` (pseudonymes),
`sqlite3` (journal et demandes en attente). **Aucune primitive cryptographique n'a été écrite par l'équipe.**

## 2. Bibliothèques Python installées automatiquement

Ces paquets ne sont pas épinglés par le projet : pip les choisit à la construction des images. Versions relevées
le 17/11/2026 avec les fichiers du projet ; une image construite un autre jour peut en avoir une autre.

| Paquet | Version relevée | Licence | Tiré par |
|---|---|---|---|
| starlette | 1.10.0 | BSD-3-Clause | FastAPI |
| pydantic / pydantic_core | 2.14.3 / 2.50.4 | MIT | FastAPI |
| annotated-types, annotated-doc, typing-inspection | 0.8.0, 0.0.6, 0.4.5 | MIT | FastAPI, pydantic |
| typing_extensions | 4.16.0 | PSF-2.0 | FastAPI, pydantic |
| anyio | 4.16.0 | MIT | Starlette, HTTPX |
| h11 | 0.16.0 | MIT | Uvicorn, HTTPX |
| httpcore | 1.0.9 | BSD-3-Clause | HTTPX |
| idna | 3.20 | BSD-3-Clause | HTTPX |
| certifi | 2026.10.23 | MPL-2.0 | HTTPX |
| click | 8.5.1 | BSD-3-Clause | Uvicorn |
| colorama | 0.4.6 | BSD (classificateur) | pytest, sous Windows seulement (absent des images Linux) |
| MarkupSafe | 3.0.4 | BSD-3-Clause | Jinja2 |
| joserfc | 1.8.0 | BSD-3-Clause | Authlib |
| opentelemetry-api | 1.45.2 | Apache-2.0 | FastAPI |
| cffi / pycparser | 2.1.1 / 3.12 | MIT-0 / BSD-3-Clause | cryptography |
| et_xmlfile | 2.0.0 | MIT | openpyxl |
| pdfminer.six | 20260107 | MIT | pdfplumber |
| pypdfium2 | 5.15.2 | BSD-3-Clause, Apache-2.0 (+ licences de ses dépendances) | pdfplumber |
| pillow | 12.2.0 | MIT-CMU | pdfplumber |
| charset-normalizer | 3.5.2 | MIT | pdfminer.six |
| iniconfig, pluggy | 2.3.1, 1.7.0 | MIT | pytest |
| packaging | 26.3 | Apache-2.0 OU BSD-2-Clause | pytest |
| Pygments | 2.21.0 | BSD-2-Clause | pytest |

## 3. Images Docker

| Image | Version | Licence (amont) | Rôle |
|---|---|---|---|
| `postgres` | 17.11-alpine | PostgreSQL License | Base de données de Keycloak **uniquement** |
| `quay.io/keycloak/keycloak` | 26.8.1 | Apache-2.0 | Comptes des agents, mot de passe + TOTP, rôles et groupes |
| `caddy` | 2.11.7-alpine | Apache-2.0 | HTTPS (autorité interne), seul point d'entrée |
| `python` | 3.13.5-slim-bookworm | PSF-2.0 pour Python ; paquets Debian sous leurs propres licences libres | Base des 6 images construites par le projet : guichet, médiateur, registres, USSD, OCR, relais |

Paquets Debian ajoutés **seulement** dans l'image `ocr` (`ocr/Dockerfile`), lancée à part, sans réseau :

| Paquet | Licence (amont) | Rôle |
|---|---|---|
| `tesseract-ocr`, `tesseract-ocr-fra` | Apache-2.0 | Lire un PDF scanné (reconnaissance de caractères) |
| `poppler-utils` (`pdftoppm`) | GPL-2.0 (indiquée dans `ocr/Dockerfile`) | Transformer les pages du PDF en images |

## 4. Outils de développement et de démonstration

Ils ne font **pas** partie du logiciel livré : ils servent à l'écrire, à le lancer ou à le montrer.

| Outil | Licence (amont) | Rôle |
|---|---|---|
| Git | GPL-2.0 | Historique du code |
| Docker Engine et Docker Compose | Apache-2.0 | Lancer les conteneurs |
| Docker Desktop | Propriétaire (conditions d'abonnement de Docker) | Docker sous Windows, sur l'ordinateur de la démo. Remplaçable par Docker Engine sous Linux |
| Claude Code (Anthropic) | Propriétaire (conditions commerciales d'Anthropic) | Assistant de programmation utilisé par l'équipe pour écrire du code et des documents. Le code produit est relu par l'équipe et publié sous AGPL-3.0 |
| FreeOTP | Apache-2.0 | Application de téléphone pour le code TOTP des agents (conseillée) |
| Aegis | GPL-3.0 | Autre application TOTP libre (conseillée) |

## 5. Compatibilité avec l'AGPL-3.0

- **MIT, MIT-0, MIT-CMU, BSD-2-Clause, BSD-3-Clause, PSF-2.0** : licences permissives, compatibles avec
  l'AGPL-3.0. Il suffit de garder leurs mentions de copyright.
- **Apache-2.0** : compatible avec la famille GPL version 3, dont l'AGPL-3.0.
- **MPL-2.0** (certifi) : compatible ; la MPL-2.0 autorise la combinaison avec les licences GNU.
- **PostgreSQL, Keycloak, Caddy** : ce sont des **programmes séparés**, qui communiquent par le réseau. Ils ne
  forment pas une œuvre unique avec notre code, et leur licence ne change pas la nôtre.
- **poppler-utils (GPL-2.0)** : appelé comme **commande séparée**, dans un conteneur à part, lancé à la main.
  Il n'est pas lié à notre code : c'est un simple assemblage de programmes, sans conflit de licence.
- **Outils propriétaires** (Docker Desktop, Claude Code) : ils ne sont pas distribués avec le code et n'ajoutent
  aucune condition à sa licence.

**Conclusion** : aucune dépendance n'empêche de publier Griot Secure sous AGPL-3.0, ni de le réutiliser.
À refaire si on ajoute une dépendance : vérifier sa licence de la même façon.

# Provenance du code

<!-- Texte d'introduction à rédiger par Enock -->

## Fichiers repris du sprint

Origine : notre dépôt du sprint (messagerie souveraine Matrix, AGPL-3.0),
commit `5d2a80abb654dde6ca320d443e7a0f6730d968f4`.

Ils ont été importés **sans aucune modification** dans le commit `317fe8b` de ce dépôt
(`chore: import du code du sprint …`). Toutes leurs modifications ultérieures sont visibles
dans l'historique git (`git log --follow <fichier>`).

| Fichier du sprint | Emplacement actuel |
|---|---|
| `.env.example` | `.env.example` |
| `.gitattributes` | `.gitattributes` |
| `.gitignore` | `.gitignore` |
| `LICENSE` (AGPL-3.0) | `LICENSE` |
| `docker-compose.yml` | `docker-compose.yml` |
| `caddy/Caddyfile` | `caddy/Caddyfile` |
| `postgres/init-bases.sh` | `postgres/init-bases.sh` |
| `keycloak/realm-administration.json` | `keycloak/realm-griot.json` |
| `keycloak/themes/messagerie/login/theme.properties` | `keycloak/themes/griot/login/theme.properties` |
| `keycloak/themes/messagerie/login/messages/messages_fr.properties` | `keycloak/themes/griot/login/messages/messages_fr.properties` |
| `keycloak/themes/messagerie/login/messages/messages_mos.properties` | `keycloak/themes/griot/login/messages/messages_mos.properties` |
| `traduction-moore/integrer.py` | `traduction-moore/integrer.py` |
| `traduction-moore/phrases.csv` | `traduction-moore/phrases.csv` |
| `traduction-moore/LISEZMOI.md` | `traduction-moore/LISEZMOI.md` |
| `console/Dockerfile` | `guichet/Dockerfile` |
| `console/requirements.txt` | `guichet/requirements.txt` |
| `console/app/__init__.py` | `guichet/app/__init__.py` |
| `console/app/config.py` | `guichet/app/config.py` |
| `console/app/main.py` (connexion OIDC + CSRF) | `guichet/app/main.py` |
| `console/app/static/style.css` | `guichet/app/static/style.css` |
| `console/app/templates/base.html` | `guichet/app/templates/base.html` |
| `console/app/templates/erreur.html` | `guichet/app/templates/erreur.html` |

`console/app/audit.py` (journal SQLite en ajout seul) a été importé puis retiré du guichet : son principe (déclencheurs SQLite qui refusent UPDATE et DELETE) est repris dans `mediateur/app/journal.py`, complété par le chaînage par hachage.

Importés puis supprimés (propres à la messagerie) : `console/app/keycloak.py` et les modèles
`accueil`, `agent`, `canaux`, `confirmer`, `enrole`, `enroler`, `journal`, `resultat` (`.html`).

Non repris : `synapse/`, `element/`, `scripts/`, `docs/`, `README.md`, `console/app/synapse.py`,
`console/tests/`, `.env`, `caddy-racine.crt`.

## Code écrit pendant la finale

Tout le reste est écrit pendant la finale (16 – 18 novembre 2026), à partir du commit `317fe8b`.

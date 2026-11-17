# Couche « socle »

**Rôle** : ce qui sert à toutes les autres couches, sans code applicatif.

| Dossier | Contenu |
|---|---|
| `caddy/Caddyfile` | HTTPS (`tls internal`), en-têtes de sécurité, CSP ; publie guichet, auth, usager. Rien d'autre |
| `caddy/Caddyfile.vitrine` | vitrine de NOS 3 registres pour les autres équipes : ports 8101-8103, GET seulement |
| `keycloak/` | realm `griot` (mot de passe + TOTP des agents, anti-force brute) et thème fr / mooré |
| `postgres/init-bases.sh` | crée la base de Keycloak (PostgreSQL ne sert qu'à Keycloak) |
| `secrets-demo/` | secrets de DÉMONSTRATION publics, pour `docker compose up` sans `.env` |
| `tests/test_realm.py` | vérifie le realm (TOTP obligatoire, groupes, rôles) |

Réseaux (docker-compose.yml) : `interne` et `registres` sans Internet ; `sortie-registres` réservé à la passerelle ;
`externe` pour Caddy ; `vitrine` pour la vitrine des registres. Pas de contrat OpenAPI : aucune API applicative ici.

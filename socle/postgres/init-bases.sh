#!/bin/bash
# Exécuté UNE SEULE FOIS par l'image postgres, quand le volume de données est vide.
# Crée la base de Keycloak avec son propre utilisateur (PostgreSQL ne sert qu'à Keycloak).
set -euo pipefail

# Le mot de passe est passé comme variable psql (:'...'), ce qui l'entoure
# de guillemets correctement, même s'il contient une apostrophe.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" \
     -v mdp_keycloak="$KEYCLOAK_DB_PASSWORD" <<'SQL'
CREATE USER keycloak WITH PASSWORD :'mdp_keycloak';
CREATE DATABASE keycloak OWNER keycloak;

-- Personne d'autre que le propriétaire ne peut se connecter à la base.
REVOKE CONNECT ON DATABASE keycloak FROM PUBLIC;
SQL

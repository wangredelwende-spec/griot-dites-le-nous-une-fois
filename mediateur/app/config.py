"""Adresses et constantes du médiateur (les chemins peuvent être changés pour les tests)."""
import os
from pathlib import Path

SECRETS = Path(os.environ.get("GRIOT_SECRETS", "/run/secrets"))
DONNEES = Path(os.environ.get("GRIOT_DONNEES", "/donnees"))
CLES_PUBLIQUES = Path(os.environ.get("GRIOT_PUBLIQUES", "/publiques"))
ADAPTATEURS = Path(os.environ.get("GRIOT_ADAPTATEURS", "/adaptateurs"))   # descriptions des registres (lecture seule)
CATALOGUE = Path(os.environ.get("GRIOT_CATALOGUE", "/catalogue"))        # annuaire.yaml + demarches.yaml

# Jetons des agents : émis par Keycloak, vérifiés avec ses clés publiques (lues par le réseau interne)
KEYCLOAK_CLES = "http://keycloak:8080/realms/griot/protocol/openid-connect/certs"
KEYCLOAK_EMETTEUR = "https://auth.griot.test/realms/griot"
AUDIENCE = "mediateur"
ROLE_AGENT = "agent-guichet"

DELAI_REGISTRE = float(os.environ.get("DELAI_REGISTRE", "3"))           # secondes
DUREE_CONSENTEMENT = int(os.environ.get("DUREE_CONSENTEMENT", "600"))   # 10 minutes


def lire_secret(nom: str) -> str:
    """Secrets fournis par docker compose dans /run/secrets/ (jamais dans les variables d'environnement)."""
    return (SECRETS / nom).read_text().strip()

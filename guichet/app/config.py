"""Adresses et constantes du guichet."""
from pathlib import Path

REALM = "griot"
# Le navigateur voit l'adresse publique ; le guichet appelle les services par le réseau Docker interne
KEYCLOAK_PUBLIC = "https://auth.griot.test"
KEYCLOAK_INTERNE = "http://keycloak:8080"
GUICHET_URL = "https://guichet.griot.test"

CLIENT_ID = "guichet"
ROLE_AGENT = "agent-guichet"
MEDIATEUR = "http://mediateur:8000"
CLES_PUBLIQUES = Path("/publiques")
CATALOGUE = Path("/catalogue")          # annuaire.yaml + demarches.yaml (lecture seule)
ADAPTATEURS = Path("/adaptateurs")      # attributs déclarés par chaque registre (lecture seule)


def lire_secret(nom: str) -> str:
    """Secrets fournis par docker compose dans /run/secrets/ (jamais dans les variables d'environnement)."""
    return Path("/run/secrets", nom).read_text().strip()

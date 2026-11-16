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
# Limite par (service, citoyen) : un même service ne peut pas interroger sans fin la même personne
# (sinon, avec des questions répétées, il pourrait reconstituer des données)
LIMITE_PAR_CITOYEN = int(os.environ.get("LIMITE_PAR_CITOYEN", "5"))     # demandes par 24 heures
# Limite de débit : nombre de citoyens DIFFÉRENTS qu'un agent peut consulter dans la fenêtre (bas pour la démo)
LIMITE_SUJETS = int(os.environ.get("LIMITE_SUJETS", "5"))
FENETRE_LIMITE = int(os.environ.get("FENETRE_LIMITE", "3600"))          # 1 heure
# Comptes de TEST (clients Keycloak « outil-test-* ») : refusés sauf si OUTILS_TEST=1 (désactivés pendant la démo)
OUTILS_TEST = os.environ.get("OUTILS_TEST", "0") == "1"
# Agents des tests de bout en bout exemptés des limites de débit : SEULEMENT si OUTILS_TEST=1 (voir main.exempte)
LIMITE_EXEMPTES = {n.strip() for n in os.environ.get("LIMITE_EXEMPTES", "").split(",") if n.strip()}


def lire_secret(nom: str) -> str:
    """Secrets fournis par docker compose dans /run/secrets/ (jamais dans les variables d'environnement)."""
    return (SECRETS / nom).read_text().strip()

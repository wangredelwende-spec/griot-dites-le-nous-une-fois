"""Identification de l'agent : jeton d'accès Keycloak transmis par le guichet (« Bearer »).

Le jeton est vérifié avec les clés publiques de Keycloak (signature, émetteur, audience « mediateur »,
expiration). Le service demandeur vient du GROUPE de l'agent dans ce jeton, jamais d'un formulaire.
"""
import jwt
from fastapi import Header, HTTPException

from .config import AUDIENCE, KEYCLOAK_CLES, KEYCLOAK_EMETTEUR, OUTILS_TEST, ROLE_AGENT

_cles_keycloak = jwt.PyJWKClient(KEYCLOAK_CLES)


def agent_connecte(authorization: str = Header("")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "jeton d'agent manquant")
    jeton = authorization.removeprefix("Bearer ")
    try:
        cle = _cles_keycloak.get_signing_key_from_jwt(jeton)
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "Keycloak injoignable : impossible de vérifier l'agent")
    except jwt.PyJWTError:
        raise HTTPException(401, "jeton d'agent invalide")
    try:
        infos = jwt.decode(jeton, cle.key, algorithms=["RS256"], audience=AUDIENCE, issuer=KEYCLOAK_EMETTEUR)
    except jwt.PyJWTError:
        raise HTTPException(401, "jeton d'agent invalide ou expiré")
    if ROLE_AGENT not in infos.get("roles", []):
        raise HTTPException(403, "rôle agent-guichet absent")
    # Comptes de test (banc de pannes) : seulement si OUTILS_TEST=1. Leur nom (« service-account-outil-test-… »)
    # les signale dans le journal.
    if str(infos.get("azp", "")).startswith("outil-test-") and not OUTILS_TEST:
        raise HTTPException(403, "comptes de test désactivés (OUTILS_TEST=0)")
    # « jeton » : transmis tel quel au registre, qui le revérifie LUI-MÊME (jamais stocké)
    return {"nom": infos.get("preferred_username", infos["sub"]), "groupes": infos.get("groups", []), "jeton": jeton}

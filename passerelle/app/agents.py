"""Identification de l'agent : jeton d'accès Keycloak transmis par le guichet (« Bearer »).

Le jeton est vérifié avec les clés publiques de Keycloak (signature, émetteur, audience « mediateur »,
expiration). Le service demandeur vient du GROUPE de l'agent dans ce jeton, jamais d'un formulaire.
Le contrôleur (rôle « controleur », lecture seule) passe par la même vérification.
"""
import hashlib
import hmac

import jwt
from fastapi import Header, HTTPException

from .config import AUDIENCE, KEYCLOAK_CLES, KEYCLOAK_EMETTEUR, OUTILS_TEST, ROLE_AGENT, ROLE_CONTROLEUR

_cles_keycloak = jwt.PyJWKClient(KEYCLOAK_CLES)

# Annuaire des services (annuaire.yaml, rechargé à chaud) : branché par main.py. Sert aux clés API.
services_de_l_annuaire = lambda: {}      # noqa: E731


def agent_par_cle_api(cle: str) -> dict:
    """Une clé API par administration (en-tête X-Cle-Api). On compare l'EMPREINTE SHA-256 à celle de
    l'annuaire (jamais la clé en clair). Le service vient de la clé, jamais du corps de la demande."""
    empreinte = hashlib.sha256(cle.encode("utf-8")).hexdigest()
    for code, service in services_de_l_annuaire().items():
        attendue = service.get("cle_api_sha256")
        if attendue and hmac.compare_digest(empreinte, str(attendue)):
            # Pas de jeton Keycloak : les registres qui exigent la double clé refuseront (voir LIMITES.md)
            return {"nom": f"api-{code}", "groupes": [service["groupe"]], "jeton": ""}
    raise HTTPException(401, "clé API inconnue")


def infos_du_jeton(authorization: str) -> tuple[str, dict]:
    """Vérifie le jeton Keycloak (signature, émetteur, audience, expiration) ; renvoie (jeton, contenu)."""
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
    return jeton, infos


def agent_connecte(authorization: str = Header(""), x_cle_api: str = Header("")) -> dict:
    if x_cle_api:
        return agent_par_cle_api(x_cle_api)
    jeton, infos = infos_du_jeton(authorization)
    if ROLE_AGENT not in infos.get("roles", []):
        raise HTTPException(403, "rôle agent-guichet absent")
    # Comptes de test (banc de pannes) : seulement si OUTILS_TEST=1. Leur nom (« service-account-outil-test-… »)
    # les signale dans le journal.
    if str(infos.get("azp", "")).startswith("outil-test-") and not OUTILS_TEST:
        raise HTTPException(403, "comptes de test désactivés (OUTILS_TEST=0)")
    # « jeton » : transmis tel quel au registre, qui le revérifie LUI-MÊME (jamais stocké)
    return {"nom": infos.get("preferred_username", infos["sub"]), "groupes": infos.get("groups", []), "jeton": jeton}


def controleur_connecte(authorization: str = Header("")) -> str:
    """Contrôleur : rôle « controleur » obligatoire. Il ne peut que LIRE (aucune route d'écriture ne l'accepte,
    et sans le rôle agent-guichet il ne peut faire aucune demande)."""
    _jeton, infos = infos_du_jeton(authorization)
    if ROLE_CONTROLEUR not in infos.get("roles", []):
        raise HTTPException(403, "rôle controleur absent")
    return infos.get("preferred_username", infos["sub"])

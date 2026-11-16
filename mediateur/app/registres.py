"""Appel d'un registre et vérification de sa réponse signée.

Règle d'or : au moindre doute, on refuse ; on ne devine jamais.
- Registre injoignable ou trop lent  -> Indisponible (« rien n'a été deviné »)
- Réponse mal formée, signature fausse, contenu inattendu -> ReponseCorrompue (ligne d'alerte)
"""
import httpx
import jwt

# Claims présents dans TOUTE réponse signée, en plus de l'attribut lui-même
CLAIMS_COMMUNS = {"iss", "aud", "sub", "demande", "iat", "exp", "jti"}


class Indisponible(Exception):
    pass


class ReponseCorrompue(Exception):
    pass


def appeler(url: str, corps: dict, delai: float) -> dict:
    """Renvoie {"jeton": "..."} ou {"refus": "motif"} ; rien d'autre n'est accepté."""
    try:
        r = httpx.post(f"{url}/attributs", json=corps, timeout=delai)
    except httpx.TimeoutException:
        raise Indisponible(f"délai dépassé ({delai:g} s)")
    except httpx.HTTPError:
        raise Indisponible("registre injoignable")
    if r.status_code != 200:
        raise Indisponible(f"registre en erreur (HTTP {r.status_code})")
    try:
        reponse = r.json()
    except ValueError:
        raise ReponseCorrompue("réponse illisible (pas du JSON)")
    if (not isinstance(reponse, dict) or len(reponse) != 1 or set(reponse) - {"jeton", "refus"}
            or not isinstance(next(iter(reponse.values())), str)):
        raise ReponseCorrompue("réponse mal formée")
    return reponse


def verifier(jeton: str, cle_publique: bytes, emetteur: str, destinataire: str, sujet_ref: str,
             id_demande: str, claim: str, cle: str | None) -> tuple[bool, dict]:
    """Vérifie TOUT : signature (clé du registre attendu), iss, aud, exp, sujet, demande, forme exacte.
    Renvoie (valeur de l'attribut, claims) ; au moindre écart : ReponseCorrompue."""
    try:
        infos = jwt.decode(jeton, cle_publique, algorithms=["EdDSA"], audience=destinataire, issuer=emetteur,
                           options={"require": sorted(CLAIMS_COMMUNS)})
    except jwt.InvalidSignatureError:
        raise ReponseCorrompue("signature invalide")
    except jwt.ExpiredSignatureError:
        raise ReponseCorrompue("réponse expirée")
    except jwt.PyJWTError as e:
        raise ReponseCorrompue(f"réponse invalide ({e})")
    if infos["sub"] != sujet_ref:
        raise ReponseCorrompue("réponse émise pour une autre personne")
    if infos["demande"] != id_demande:
        raise ReponseCorrompue("réponse émise pour une autre demande")
    if set(infos) != CLAIMS_COMMUNS | {claim}:
        raise ReponseCorrompue("contenu inattendu (informations en trop ou manquantes)")
    valeur = infos[claim]
    if cle is not None:
        if not isinstance(valeur, dict) or set(valeur) != {cle}:
            raise ReponseCorrompue("forme de l'attribut inattendue")
        valeur = valeur[cle]
    if type(valeur) is not bool:
        raise ReponseCorrompue("valeur de l'attribut inattendue (oui/non attendu)")
    return valeur, infos

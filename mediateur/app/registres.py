"""Appel d'un registre et vérification de sa réponse signée.

Règle d'or : au moindre doute, on refuse ; on ne devine jamais.
- Registre injoignable ou trop lent (délai TOTAL dépassé) -> Indisponible (« rien n'a été deviné »)
- Réponse mal formée, signature fausse, contenu inattendu  -> ReponseCorrompue (ligne d'alerte)
Le registre signe TOUT ce qu'il répond, y compris ses refus : un refus non signé est une réponse corrompue.
"""
import asyncio

import httpx
import jwt

# Claims présents dans TOUTE réponse signée. En plus : l'attribut (statut « ok ») ou « motif » (statut « refus »).
CLAIMS_COMMUNS = {"iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut"}


class Indisponible(Exception):
    pass


class ReponseCorrompue(Exception):
    pass


async def appeler(url: str, corps: dict, delai: float) -> str:
    """Renvoie le jeton signé du registre. Le délai est appliqué à chaque étape par httpx ET au total
    (asyncio.wait_for) : un registre qui répond goutte à goutte ne bloque jamais le guichet."""
    try:
        async with httpx.AsyncClient(timeout=delai) as client:
            r = await asyncio.wait_for(client.post(f"{url}/attributs", json=corps), timeout=delai)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        raise Indisponible(f"délai dépassé ({delai:g} s)")
    except httpx.HTTPError:
        raise Indisponible("registre injoignable")
    if r.status_code != 200:
        raise Indisponible(f"registre en erreur (HTTP {r.status_code})")
    try:
        reponse = r.json()
    except ValueError:
        raise ReponseCorrompue("réponse illisible (pas du JSON)")
    if not isinstance(reponse, dict) or set(reponse) != {"jeton"} or not isinstance(reponse["jeton"], str):
        raise ReponseCorrompue("réponse mal formée (une réponse signée est attendue)")
    return reponse["jeton"]


def verifier(jeton: str, cle_publique: bytes, emetteur: str, destinataire: str, sujet_ref: str,
             id_demande: str, claim: str, cle: str | None) -> tuple[str, bool | str, dict]:
    """Vérifie TOUT : signature (clé du registre attendu), iss, aud, exp, sujet, demande, forme exacte.
    Renvoie ("ok", valeur de l'attribut, claims) ou ("refus", motif public, claims).
    Au moindre écart : ReponseCorrompue."""
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

    if infos["statut"] == "refus":
        if set(infos) != CLAIMS_COMMUNS | {"motif"} or not isinstance(infos["motif"], str):
            raise ReponseCorrompue("refus au contenu inattendu (informations en trop ou manquantes)")
        return "refus", infos["motif"][:200], infos

    if infos["statut"] != "ok" or set(infos) != CLAIMS_COMMUNS | {claim}:
        raise ReponseCorrompue("contenu inattendu (informations en trop ou manquantes)")
    valeur = infos[claim]
    if cle is not None:
        if not isinstance(valeur, dict) or set(valeur) != {cle}:
            raise ReponseCorrompue("forme de l'attribut inattendue")
        valeur = valeur[cle]
    if type(valeur) is not bool:
        raise ReponseCorrompue("valeur de l'attribut inattendue (oui/non attendu)")
    return "ok", valeur, infos

"""Appel d'un registre (selon le contrat) : lire la fiche d'un citoyen par son identifiant.

DEPUIS LE 17/11 : lire_fiche() ci-dessous remplace le flux « réponse signée ». Les fonctions appeler() et verifier()
plus bas (registres signés, Ed25519) sont DÉSACTIVÉES : conservées, plus appelées (LIMITES.md).

Ancienne description :
Appel d'un registre et vérification de sa réponse signée.

Règle d'or : au moindre doute, on refuse ; on ne devine jamais.
- Registre injoignable ou trop lent (délai TOTAL dépassé) -> Indisponible (« rien n'a été deviné »)
- Réponse mal formée, signature fausse, contenu inattendu  -> ReponseCorrompue (ligne d'alerte)
Le registre signe TOUT ce qu'il répond, y compris ses refus : un refus non signé est une réponse corrompue.
"""
import asyncio
import re
import ssl
from urllib.parse import quote

import httpx
import jwt

# Claims présents dans TOUTE réponse signée. En plus : l'attribut (statut « ok ») ou « motif » (statut « refus »).
CLAIMS_COMMUNS = {"iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut"}

# Contexte TLS standard créé UNE fois : le recréer à chaque appel coûte 0,25 s de calcul,
# ce qui ralentirait les appels en parallèle aux 3 registres.
CONTEXTE_TLS = ssl.create_default_context()


class Indisponible(Exception):
    pass


class ReponseCorrompue(Exception):
    pass


class CitoyenInconnu(Exception):
    """Le registre répond 404 : il ne connaît pas cette personne (ce n'est PAS une panne)."""


TENTATIVES = 2     # un appel + 1 réessai, seulement si le registre n'a pas répondu à temps ou est injoignable


async def lire_fiche(url: str, chemin: str, sujet_ref: str, delai: float, cle_api: tuple | None = None):
    """GET {url}{chemin avec l'identifiant} ; renvoie le JSON de la fiche (pas encore validé contre le contrat).
    Délai de 2 s par essai (httpx ET asyncio.wait_for) et UN réessai si le registre ne répond pas à temps ou est
    injoignable. 404 -> CitoyenInconnu ; autre code, ou pas de réponse -> Indisponible ; corps illisible -> ReponseCorrompue."""
    entetes = {cle_api[0]: cle_api[1]} if cle_api else {}
    # L'identifiant remplace LE paramètre de la route, quel que soit son nom ({id}, {numero}…) : la route est
    # recopiée du contrat du registre (un seul paramètre, vérifié au chargement du catalogue)
    adresse = url + re.sub(r"\{[^{}/]+\}", lambda _: quote(sujet_ref, safe=""), chemin, count=1)
    for tentative in range(1, TENTATIVES + 1):
        try:
            async with httpx.AsyncClient(timeout=delai, verify=CONTEXTE_TLS) as client:
                r = await asyncio.wait_for(client.get(adresse, headers=entetes), timeout=delai)
            break
        except (asyncio.TimeoutError, httpx.TimeoutException):
            if tentative == TENTATIVES:
                raise Indisponible(f"délai dépassé ({delai:g} s, {TENTATIVES} essais)")
        except httpx.HTTPError:
            if tentative == TENTATIVES:
                raise Indisponible("registre injoignable")
    if r.status_code == 404:
        raise CitoyenInconnu("citoyen inconnu de ce registre")
    if r.status_code != 200:
        raise Indisponible(f"registre en erreur (HTTP {r.status_code})")
    try:
        return r.json()
    except ValueError:
        raise ReponseCorrompue("réponse illisible (pas du JSON)")


async def appeler(url: str, corps: dict, delai: float, jeton_agent: str = "", cle_api: tuple | None = None) -> str:
    """Renvoie le jeton signé du registre. Le délai (2 s par défaut) est appliqué à chaque étape par httpx ET au
    total (asyncio.wait_for) : un registre qui répond goutte à goutte ne bloque jamais le guichet.
    Un seul réessai, et seulement si le registre n'a pas répondu à temps ou est injoignable.
    « cle_api » = (nom de l'en-tête, valeur) si le registre en exige une (déclarée dans annuaire.yaml)."""
    entetes = {"Authorization": f"Bearer {jeton_agent}"}
    if cle_api:
        entetes[cle_api[0]] = cle_api[1]
    for tentative in range(1, TENTATIVES + 1):
        try:
            async with httpx.AsyncClient(timeout=delai, verify=CONTEXTE_TLS) as client:
                # Le jeton de l'agent accompagne la demande : le registre vérifie lui-même qui demande
                r = await asyncio.wait_for(client.post(f"{url}/attributs", json=corps, headers=entetes),
                                           timeout=delai)
            break
        except (asyncio.TimeoutError, httpx.TimeoutException):
            if tentative == TENTATIVES:
                raise Indisponible(f"délai dépassé ({delai:g} s, {TENTATIVES} essais)")
        except httpx.HTTPError:
            if tentative == TENTATIVES:
                raise Indisponible("registre injoignable")
    if r.status_code == 404:
        raise CitoyenInconnu("citoyen inconnu de ce registre")
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
             id_demande: str, attribut: dict, parametres: dict) -> tuple[str, bool | str, dict]:
    """Vérifie TOUT : signature (clé du registre attendu), iss, aud, exp, sujet, demande, forme exacte.
    Renvoie ("ok", oui/non, claims) ou ("refus", motif public, claims).
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
    if infos["statut"] != "ok":
        raise ReponseCorrompue("statut inattendu")
    return "ok", lire_valeur(infos, attribut, parametres), infos


def lire_valeur(infos: dict, attribut: dict, parametres: dict) -> bool | dict:
    """Réponse « ok » -> oui/non (ou, pour identité et naissance/filiation, les cases précises), après contrôle de la
    forme EXACTE (rien en trop, rien en moins)."""
    claim = attribut["claim"]
    if attribut["regle"] == "champs":
        # ex. {"identite": {"nom": "KABORE", "prenoms": "Aminata"}} : exactement les cases déclarées, en texte non vide
        valeur = infos.get(claim)
        if (set(infos) != CLAIMS_COMMUNS | {claim} or not isinstance(valeur, dict)
                or set(valeur) != set(attribut["champs"])
                or any(not isinstance(v, str) or not v.strip() for v in valeur.values())):
            raise ReponseCorrompue("contenu inattendu (informations en trop ou manquantes)")
        return valeur
    if attribut["regle"] != "age_entre":
        # ex. {"nationalite_bf": true}
        if set(infos) != CLAIMS_COMMUNS | {claim} or type(infos[claim]) is not bool:
            raise ReponseCorrompue("contenu inattendu (informations en trop ou manquantes)")
        return infos[claim]
    # ex. {"age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31"}
    #     = au moins 18 ans ET pas encore 38 ans (donc 37 ans au plus) à la date de référence
    seuils = [str(parametres["min"])]
    if parametres.get("max") is not None:
        seuils.append(str(parametres["max"] + 1))
    if set(infos) != CLAIMS_COMMUNS | {claim, "date_reference"}:
        raise ReponseCorrompue("contenu inattendu (informations en trop ou manquantes)")
    ages = infos[claim]
    if (not isinstance(ages, dict) or set(ages) != set(seuils)
            or any(type(v) is not bool for v in ages.values())):
        raise ReponseCorrompue("forme de l'attribut inattendue (seuils d'âge)")
    if infos["date_reference"] != parametres["date_reference"]:
        raise ReponseCorrompue("date de référence différente de celle demandée")
    return ages[seuils[0]] and not (len(seuils) == 2 and ages[seuils[1]])

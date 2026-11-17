"""Couche consentement et minimisation, côté USAGER : ce qu'il voit avant l'envoi et ce qu'il décide.

- aperçu exact de ce qui partira (« Le service des bourses recevra : majeur = oui. Rien d'autre. ») ;
- confirmer ou refuser (UNE décision pour tout l'aperçu) ; retirer un accord ; liste des accords ;
- expiration : sans réponse en 10 minutes, les réponses en attente sont effacées et rien ne part.

Mêmes adresses qu'avant (docs/API_USAGER.md, openapi.yaml de cette couche). Ces routes tournent dans le processus
de la passerelle d'échange : elles utilisent sa base de travail, son journal et son catalogue en vigueur, qu'elle
leur donne au démarrage (brancher). Aucune valeur n'est écrite au journal, jamais.
"""
import hmac
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

COUCHE = "consentement et minimisation"
routeur = APIRouter(tags=[COUCHE])

# La passerelle (module app.main), donnée par brancher() au démarrage. On lit P.CAT à chaque appel :
# le catalogue en vigueur change quand le fichier change.
P = None


def brancher(passerelle):
    global P
    P = passerelle


def canal(x_cle_canal: str = Header("")) -> str:
    """Écran usager authentifié (« ussd » ou « web ») d'après son secret ; sinon 401."""
    return P.canal_usager(x_cle_canal)


class Usager(BaseModel):
    sujet_ref: str = Field(min_length=1, max_length=200)     # format : annuaire.yaml (controler_identifiant)


# --- Expiration ---

def rafraichir(demande: dict) -> dict:
    """Consentement non donné (ou réponse non retirée) dans le délai : on efface les réponses."""
    if demande["statut"] in ("en_attente", "confirmee") and time.time() > demande["expire_le"]:
        P.refuser(demande, "expiree", "expiration", "délai de 10 minutes dépassé : rien n'a été remis")
    return demande


# --- Aperçu : construit depuis le catalogue, jamais écrit en dur ---

def libelles(code_demarche: str) -> dict:
    """{code d'attribut: sa demande dans le catalogue} pour une démarche (vide si elle a été retirée)."""
    demarche = P.CAT["demarches"].get(code_demarche, {})
    return {a["attribut"]: a for a in demarche.get("attributs", [])}


def apercu(demande: dict) -> dict:
    """Ce que l'usager voit AVANT : exactement ce qui partira, et rien d'autre."""
    fiche = P.CAT["services"].get(demande["demandeur"], {})
    # « nom_court » (annuaire) pour tenir dans un écran USSD de 160 caractères, sinon le nom complet
    service = fiche.get("nom_court") or fiche.get("nom", demande["demandeur"])
    connus = libelles(demande["demarche"])
    attributs = [{"code": v["attribut"], "libelle": connus.get(v["attribut"], {}).get("libelle", v["attribut"]),
                  "parametres": connus.get(v["attribut"], {}).get("parametres", {}),
                  "valeur": "oui" if v["valeur"] else "non"}
                 for v in demande["volets"] if v["statut"] == "ok"]
    liste = " ; ".join(f"{a['libelle']} = {a['valeur']}" for a in attributs)
    return {"id_demande": demande["id_demande"], "service": service, "code_service": demande["demandeur"],
            "demarche": P.CAT["demarches"].get(demande["demarche"], {}).get("libelle", demande["demarche"]),
            "finalite": demande["finalite"], "attributs": attributs, "expire_le": int(demande["expire_le"]),
            "apercu": f"{service} recevra : {liste}. Rien d'autre."}


def finalites_traduites(demarche: dict, finalite: str) -> dict:
    """{langue: finalité traduite} (champs finalite_mos… du catalogue). Seulement si la finalité écrite au journal
    est celle du catalogue en vigueur : une traduction d'une AUTRE finalité serait fausse (l'écran garde le français)."""
    if demarche.get("finalite") != finalite:
        return {}
    return {cle.removeprefix("finalite_"): v for cle, v in demarche.items() if cle.startswith("finalite_")}


# --- Routes ---

@routeur.get("/usagers/{sujet_ref}/en-attente", dependencies=[Depends(canal)])
def en_attente(sujet_ref: str):
    P.controler_identifiant(sujet_ref)
    with P.VERROU:
        ids = P.base.execute("SELECT id_demande FROM demandes WHERE sujet = ? AND statut = 'en_attente'",
                             (P.pseudonyme(sujet_ref),)).fetchall()
    demandes = [rafraichir(P.lire(i["id_demande"])) for i in ids]
    return [apercu(d) for d in demandes if d["statut"] == "en_attente"]


def demande_de_l_usager(id_demande: str, usager: Usager) -> dict:
    P.controler_identifiant(usager.sujet_ref)
    demande = P.lire(id_demande)
    if demande is None or not hmac.compare_digest(demande["sujet"], P.pseudonyme(usager.sujet_ref)):
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["statut"] != "en_attente":
        raise HTTPException(409, f"demande déjà traitée (statut : {demande['statut']})")
    return demande


@routeur.post("/demandes/{id_demande}/confirmer")
def confirmer(id_demande: str, usager: Usager, canal: str = Depends(canal)):
    """UNE confirmation pour tout l'aperçu (un ou plusieurs attributs)."""
    demande = demande_de_l_usager(id_demande, usager)
    ligne = P.tracer(demande, "confirmation", "ok", canal=canal, **P.transmis(demande))
    P.changer(demande, statut="confirmee")
    return {"id_demande": id_demande, "statut": "confirmee", "empreinte": ligne["hash"]}


@routeur.post("/demandes/{id_demande}/refuser")
def refuser_par_usager(id_demande: str, usager: Usager, canal: str = Depends(canal)):
    demande = demande_de_l_usager(id_demande, usager)
    P.refuser(demande, "refuse", "refus-usager", "refusé par l'usager : rien n'a été transmis", canal)
    return {"id_demande": id_demande, "statut": "refuse"}


@routeur.get("/usagers/{sujet_ref}/accords", dependencies=[Depends(canal)])
def accords(sujet_ref: str):
    """Accords donnés par l'usager, qu'il peut retirer : pas encore remis (« en cours ») ou déjà remis."""
    P.controler_identifiant(sujet_ref)
    with P.VERROU:
        ids = P.base.execute("SELECT id_demande FROM demandes WHERE sujet = ? AND base = 'consentement' "
                             "AND statut IN ('confirmee', 'remise') ORDER BY rowid DESC LIMIT 9",
                             (P.pseudonyme(sujet_ref),)).fetchall()
    resultat = []
    for i in ids:
        demande = rafraichir(P.lire(i["id_demande"]))
        if demande["statut"] not in ("confirmee", "remise"):
            continue
        connus = libelles(demande["demarche"])
        resultat.append({
            "id_demande": demande["id_demande"], "code_service": demande["demandeur"],
            "service": P.CAT["services"].get(demande["demandeur"], {}).get("nom", demande["demandeur"]),
            "demarche": P.CAT["demarches"].get(demande["demarche"], {}).get("libelle", demande["demarche"]),
            "attributs": [{"code": v["attribut"], "libelle": connus.get(v["attribut"], {}).get("libelle", v["attribut"])}
                          for v in demande["volets"] if v["statut"] == "ok"],
            "transmis": demande["statut"] == "remise"})
    return resultat


@routeur.post("/demandes/{id_demande}/retirer")
def retirer(id_demande: str, usager: Usager, canal: str = Depends(canal)):
    """Retrait de l'accord. Pas encore remis : plus rien ne partira. Déjà remis : on ne peut pas rappeler une
    réponse transmise, mais le retrait est écrit au journal (le service ne doit plus l'utiliser)."""
    demande = P.lire(id_demande)
    if demande is None or not hmac.compare_digest(demande["sujet"], P.pseudonyme(usager.sujet_ref)):
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["base"] != "consentement":
        raise HTTPException(409, "base légale : il n'y a pas d'accord à retirer")
    if demande["statut"] in ("en_attente", "confirmee"):
        motif = "accord retiré par l'usager : rien n'a été transmis"
        ligne = P.tracer(demande, "retrait", "ok", motif, canal=canal, **P.transmis(demande))
        P.changer(demande, statut="retiree", motif=motif)
        P.effacer_reponses(demande)
        return {"id_demande": id_demande, "statut": "retiree", "transmis": False, "empreinte": ligne["hash"]}
    if demande["statut"] == "remise":
        motif = "accord retiré après la transmission : le service ne doit plus utiliser la réponse"
        ligne = P.tracer(demande, "retrait", "ok", motif, canal=canal, **P.transmis(demande))
        P.changer(demande, statut="retiree_apres_remise", motif=motif)
        return {"id_demande": id_demande, "statut": "retiree_apres_remise", "transmis": True,
                "empreinte": ligne["hash"]}
    raise HTTPException(409, f"rien à retirer (statut : {demande['statut']})")


@routeur.get("/catalogue/langues", dependencies=[Depends(canal)])
def langues_du_catalogue():
    """Langues dans lesquelles TOUTES les démarches actives ont leur finalité traduite. L'USSD ne propose une
    langue que si elle est ici ET complète dans phrases-ussd.csv."""
    par_demarche = [set(finalites_traduites(d, d.get("finalite"))) for d in P.CAT["demarches"].values()]
    return {"langues": sorted(set.intersection(*par_demarche)) if par_demarche else []}

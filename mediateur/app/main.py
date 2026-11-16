"""Médiateur : fait circuler l'attribut UTILE du registre vers le guichet, avec consentement et traçabilité.

API JSON, joignable uniquement par le réseau Docker interne (jamais publiée par Caddy).
- Côté guichet (jeton Keycloak de l'agent) : POST /demandes, GET /demandes/{id}
- Côté usager (canal authentifié par un secret partagé) : en-attente, confirmer, refuser, historique
  (contrats décrits dans docs/API_USAGER.md)

Le médiateur ne voit que la réponse minimale signée par le registre ; il la garde en attente
jusqu'à la confirmation de l'usager, puis l'efface dès qu'elle est remise ou expirée.
"""
import hashlib
import hmac
import json
import sqlite3
import threading
import time

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import registres
from .agents import agent_connecte
from .config import CLES_PUBLIQUES, DELAI_REGISTRE, DONNEES, DUREE_CONSENTEMENT, FICHIER_REGLES, lire_secret
from .journal import Journal

REGLES = yaml.safe_load(FICHIER_REGLES.read_text(encoding="utf-8"))
SECRET_PSEUDONYME = lire_secret("sujet_hmac").encode()
SECRET_CANAL = lire_secret("canal_usager").encode()

# Une seule connexion SQLite, protégée par un verrou (les requêtes sont traitées en parallèle)
VERROU = threading.RLock()
base = sqlite3.connect(DONNEES / "mediateur.sqlite3", check_same_thread=False, isolation_level=None)
base.row_factory = sqlite3.Row
journal = Journal(base, VERROU)
with VERROU:
    base.executescript("""
        -- Demandes : table de TRAVAIL (modifiable), à ne pas confondre avec le journal (ajout seul).
        -- On n'y garde ni le nom ni l'identifiant en clair du citoyen : seulement son pseudonyme.
        CREATE TABLE IF NOT EXISTS demandes (
            id_demande TEXT PRIMARY KEY,
            requete TEXT NOT NULL,       -- empreinte de la demande (détecte un id réutilisé pour autre chose)
            agent TEXT NOT NULL, demandeur TEXT NOT NULL, demarche TEXT NOT NULL, finalite TEXT NOT NULL,
            base TEXT NOT NULL, attribut TEXT NOT NULL, registre TEXT NOT NULL, sujet TEXT NOT NULL,
            statut TEXT NOT NULL,        -- en_cours | en_attente | confirmee | remise | refuse | indisponible | expiree
            motif TEXT NOT NULL DEFAULT '',
            valeur INTEGER,              -- réponse minimale (pour l'aperçu), effacée dès la remise
            jeton TEXT,                  -- réponse signée en attente, effacée dès la remise ou l'expiration
            expire_le REAL NOT NULL DEFAULT 0
        );
        -- Identifiants (jti) des réponses déjà acceptées : une réponse ne sert qu'une fois
        CREATE TABLE IF NOT EXISTS jti_vus (jti TEXT PRIMARY KEY);
    """)

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def pseudonyme(sujet_ref: str) -> str:
    """HMAC-SHA256 (bibliothèque standard) : le journal ne contient jamais l'identifiant du citoyen."""
    return hmac.new(SECRET_PSEUDONYME, sujet_ref.encode("utf-8"), hashlib.sha256).hexdigest()


def service_de(agent: dict) -> str | None:
    """Groupe Keycloak de l'agent -> code du service demandeur (un et un seul)."""
    services = [code for code, s in REGLES["services"].items() if s["groupe"] in agent["groupes"]]
    return services[0] if len(services) == 1 else None


def tracer(demande: dict, evenement: str, resultat: str, motif: str = "") -> dict:
    """Écrit une ligne au journal : le fait, jamais la valeur de l'attribut."""
    return journal.ecrire(agent=demande["agent"], demandeur=demande["demandeur"], demarche=demande["demarche"],
                          finalite=demande["finalite"], base=demande["base"], attribut=demande["attribut"],
                          registre=demande["registre"], sujet=demande["sujet"], evenement=evenement,
                          resultat=resultat, motif=motif)


def lire(id_demande: str) -> dict | None:
    with VERROU:
        ligne = base.execute("SELECT * FROM demandes WHERE id_demande = ?", (id_demande,)).fetchone()
    return dict(ligne) if ligne else None


def changer(demande: dict, **champs):
    demande.update(champs)
    with VERROU:
        base.execute(f"UPDATE demandes SET {', '.join(f'{c} = ?' for c in champs)} WHERE id_demande = ?",
                     [*champs.values(), demande["id_demande"]])


def refuser(demande: dict, statut: str, evenement: str, motif: str) -> dict:
    tracer(demande, evenement, "indisponible" if statut == "indisponible" else "refuse", motif)
    changer(demande, statut=statut, motif=motif, valeur=None, jeton=None)
    return demande


def rafraichir(demande: dict) -> dict:
    """Consentement non donné (ou réponse non retirée) dans le délai : on efface la réponse."""
    if demande["statut"] in ("en_attente", "confirmee") and time.time() > demande["expire_le"]:
        refuser(demande, "expiree", "expiration", "délai de 10 minutes dépassé : rien n'a été remis")
    return demande


def etat(demande: dict, jeton: str | None = None) -> dict:
    """Ce que voit le guichet : jamais la valeur en clair, seulement la réponse signée au moment de la remise."""
    reponse = {"id_demande": demande["id_demande"], "statut": demande["statut"], "motif": demande["motif"],
               "demarche": demande["demarche"], "registre": demande["registre"]}
    if demande["statut"] in ("en_attente", "confirmee"):
        reponse["expire_le"] = int(demande["expire_le"])
    if jeton:
        reponse["jeton"] = jeton
    return reponse


def remettre(demande: dict) -> dict:
    """Remise au guichet : la réponse signée part une fois, puis le médiateur l'efface."""
    jeton = demande["jeton"]
    tracer(demande, "remise", "ok")
    changer(demande, statut="remise", valeur=None, jeton=None)
    return etat(demande, jeton)


# --- Côté guichet ---

UUID4 = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class Demande(BaseModel):
    id_demande: str = Field(pattern=UUID4)
    demarche: str = Field(max_length=64)
    attribut: str = Field(max_length=64)
    sujet_ref: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    finalite: str = Field(max_length=200)


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


@app.post("/demandes")
async def creer_demande(d: Demande, agent: dict = Depends(agent_connecte)):
    demandeur = service_de(agent) or "inconnu"
    regle = REGLES["demarches"].get(d.demarche, {})
    conf_attribut = REGLES["attributs"].get(d.attribut, {})
    demande = {"id_demande": d.id_demande, "agent": agent["nom"], "demandeur": demandeur, "demarche": d.demarche,
               "finalite": d.finalite, "base": regle.get("base", ""), "attribut": d.attribut,
               "registre": conf_attribut.get("registre", ""), "sujet": pseudonyme(d.sujet_ref),
               "statut": "en_cours", "motif": "", "valeur": None, "jeton": None, "expire_le": 0}
    demande["requete"] = hashlib.sha256(json.dumps(
        [agent["nom"], d.model_dump()], sort_keys=True).encode()).hexdigest()

    # Rejeu : même id_demande -> une seule exécution, le même résultat est renvoyé (registre non rappelé)
    with VERROU:
        existante = lire(d.id_demande)
        if existante is None:
            base.execute(f"INSERT INTO demandes ({', '.join(demande)}) VALUES ({', '.join('?' * len(demande))})",
                         list(demande.values()))
    if existante:
        if existante["requete"] != demande["requete"]:
            raise HTTPException(409, "identifiant de demande déjà utilisé pour une autre demande")
        return etat(rafraichir(existante))

    # 1. Règles : service, démarche, attribut, finalité
    if demandeur == "inconnu":
        return etat(refuser(demande, "refuse", "demande", "service de l'agent indéterminé"))
    if not regle or regle["service"] != demandeur:
        return etat(refuser(demande, "refuse", "demande", "démarche non autorisée pour ce service"))
    if d.attribut != regle["attribut"]:
        return etat(refuser(demande, "refuse", "demande", "attribut non autorisé pour cette démarche"))
    if d.finalite != regle["finalite"]:
        return etat(refuser(demande, "refuse", "demande", "finalité non autorisée"))
    tracer(demande, "demande", "ok")

    # 2. Appel du registre, avec un délai maximal (total)
    conf_registre = REGLES["registres"][demande["registre"]]
    corps = {"id_demande": d.id_demande, "attribut": d.attribut, "sujet_ref": d.sujet_ref, "destinataire": demandeur}
    try:
        jeton = await registres.appeler(conf_registre["url"], corps, DELAI_REGISTRE)
        # La clé publique vient du volume du registre, monté en LECTURE SEULE ici
        cle_publique = (CLES_PUBLIQUES / demande["registre"] / "cle.pem").read_bytes()
        # 3. Vérification complète de la réponse signée (réponse OU refus)
        statut, contenu, infos = registres.verifier(jeton, cle_publique, conf_registre["emetteur"], demandeur,
                                                    d.sujet_ref, d.id_demande, conf_attribut["claim"],
                                                    conf_attribut.get("cle"))
        try:
            with VERROU:
                base.execute("INSERT INTO jti_vus (jti) VALUES (?)", (infos["jti"],))
        except sqlite3.IntegrityError:
            raise registres.ReponseCorrompue("réponse déjà utilisée (rejeu du jeton)")
    except registres.Indisponible as e:
        return etat(refuser(demande, "indisponible", "reponse-registre",
                            f"Registre indisponible ({e}), rien n'a été deviné"))
    except FileNotFoundError:
        return etat(refuser(demande, "indisponible", "reponse-registre",
                            "clé publique du registre absente, rien n'a été deviné"))
    except registres.ReponseCorrompue as e:
        return etat(refuser(demande, "refuse", "alerte", f"réponse corrompue : {e}"))

    if statut == "refus":
        # Refus signé par le registre : transmis tel quel, le guichet en revérifie la signature
        return etat(refuser(demande, "refuse", "reponse-registre", contenu), jeton)
    tracer(demande, "reponse-registre", "ok")

    # 4. Base légale : remise immédiate. Consentement : en attente de l'usager (aperçu exact).
    changer(demande, jeton=jeton, valeur=int(contenu), expire_le=time.time() + DUREE_CONSENTEMENT)
    if regle["base"] == "base-legale":
        return remettre(demande)
    changer(demande, statut="en_attente")
    return etat(demande)


@app.get("/demandes/{id_demande}")
def suivre_demande(id_demande: str, agent: dict = Depends(agent_connecte)):
    demande = lire(id_demande)
    if demande is None or demande["agent"] != agent["nom"]:
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["statut"] == "confirmee":
        return remettre(demande)
    return etat(demande)


# --- Côté usager (USSD simulé, portail) : canal authentifié par un secret partagé ---

def canal_usager(x_cle_canal: str = Header("")):
    if not hmac.compare_digest(x_cle_canal.encode(), SECRET_CANAL):
        raise HTTPException(401, "canal usager non authentifié")


class Usager(BaseModel):
    sujet_ref: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")


def apercu(demande: dict) -> dict:
    service = REGLES["services"].get(demande["demandeur"], {}).get("nom", demande["demandeur"])
    libelle = REGLES["attributs"][demande["attribut"]]["libelle"]
    valeur = "oui" if demande["valeur"] else "non"
    return {"id_demande": demande["id_demande"], "service": service, "code_service": demande["demandeur"],
            "code_attribut": demande["attribut"],
            "demarche": REGLES["demarches"][demande["demarche"]]["libelle"], "finalite": demande["finalite"],
            "attribut": libelle, "valeur": valeur, "expire_le": int(demande["expire_le"]),
            "apercu": f"{service} recevra : {libelle} = {valeur}. Rien d'autre."}


@app.get("/usagers/{sujet_ref}/en-attente", dependencies=[Depends(canal_usager)])
def en_attente(sujet_ref: str):
    with VERROU:
        lignes = base.execute("SELECT * FROM demandes WHERE sujet = ? AND statut = 'en_attente'",
                              (pseudonyme(sujet_ref),)).fetchall()
    demandes = [rafraichir(dict(l)) for l in lignes]
    return [apercu(d) for d in demandes if d["statut"] == "en_attente"]


def demande_de_l_usager(id_demande: str, usager: Usager) -> dict:
    demande = lire(id_demande)
    if demande is None or not hmac.compare_digest(demande["sujet"], pseudonyme(usager.sujet_ref)):
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["statut"] != "en_attente":
        raise HTTPException(409, f"demande déjà traitée (statut : {demande['statut']})")
    return demande


@app.post("/demandes/{id_demande}/confirmer", dependencies=[Depends(canal_usager)])
def confirmer(id_demande: str, usager: Usager):
    demande = demande_de_l_usager(id_demande, usager)
    ligne = tracer(demande, "confirmation", "ok")
    changer(demande, statut="confirmee")
    return {"id_demande": id_demande, "statut": "confirmee", "empreinte": ligne["hash"]}


@app.post("/demandes/{id_demande}/refuser", dependencies=[Depends(canal_usager)])
def refuser_par_usager(id_demande: str, usager: Usager):
    demande = demande_de_l_usager(id_demande, usager)
    refuser(demande, "refuse", "refus-usager", "refusé par l'usager : rien n'a été transmis")
    return {"id_demande": id_demande, "statut": "refuse"}


@app.get("/usagers/{sujet_ref}/historique", dependencies=[Depends(canal_usager)])
def historique(sujet_ref: str):
    """Qui a consulté, quand, pourquoi, sur quelle base. Jamais la valeur (le journal ne la contient pas)."""
    lignes = []
    for l in journal.lignes_du_sujet(pseudonyme(sujet_ref)):
        demarche = REGLES["demarches"].get(l["demarche"], {})
        lignes.append({
            "n": l["n"], "ts": l["ts"], "agent": l["agent"],
            "service": REGLES["services"].get(l["demandeur"], {}).get("nom", l["demandeur"]),
            "code_service": l["demandeur"],
            "demarche": demarche.get("libelle", l["demarche"]), "finalite": l["finalite"], "base": l["base"],
            "texte_base": demarche.get("texte", "") if l["base"] == "base-legale" else "",
            "attribut": l["attribut"], "evenement": l["evenement"], "resultat": l["resultat"],
            "motif": l["motif"], "empreinte": l["hash"]})
    return lignes

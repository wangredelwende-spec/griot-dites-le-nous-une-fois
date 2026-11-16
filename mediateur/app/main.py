"""Médiateur : fait circuler les attributs UTILES des registres vers le guichet, avec consentement et traçabilité.

API JSON, joignable uniquement par le réseau Docker interne (jamais publiée par Caddy).
- Côté guichet (jeton Keycloak de l'agent) : POST /demandes, GET /demandes/{id}  (docs/API.md)
- Côté usager (canal authentifié par un secret partagé) : en-attente, confirmer, refuser, historique
  (docs/API_USAGER.md)

Une demande = une démarche du catalogue = un ou plusieurs attributs (« volets »), chacun demandé à SON
registre, en parallèle. Le médiateur ne voit que les réponses minimales signées par les registres ; il les
garde en attente jusqu'à la confirmation de l'usager, puis les efface dès qu'elles sont remises ou expirées.
"""
import asyncio
import hashlib
import hmac
import json
import sqlite3
import threading
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from . import catalogue, registres
from .agents import agent_connecte
from .config import (CLES_PUBLIQUES, DELAI_REGISTRE, DONNEES, DUREE_CONSENTEMENT, FENETRE_LIMITE,
                     LIMITE_EXEMPTES, LIMITE_PAR_CITOYEN, LIMITE_SUJETS, lire_secret)
from .journal import Journal

# Catalogue validé au démarrage : s'il est incomplet, le médiateur ne démarre pas (on ne devine pas une règle)
try:
    CAT = catalogue.charger()
except catalogue.CatalogueInvalide as e:
    raise SystemExit(f"CATALOGUE INVALIDE : le médiateur ne démarre pas.\n{e}")
for avertissement in CAT["avertissements"]:
    print(f"Attention, {avertissement}", flush=True)

SECRET_PSEUDONYME = lire_secret("sujet_hmac").encode()
SECRET_CANAL = lire_secret("canal_usager").encode()

def archiver_ancien_journal() -> str:
    """Journal d'une version précédente (sans la colonne id_demande) : il est gardé INTACT sous un autre nom
    (toujours vérifiable : verifier.py <fichier>) et le nouveau journal le cite dans sa première ligne."""
    chemin = DONNEES / "mediateur.sqlite3"
    if not chemin.exists():
        return ""
    ancien = sqlite3.connect(chemin)
    colonnes = [c[1] for c in ancien.execute("PRAGMA table_info(journal)")]
    derniere = ancien.execute("SELECT n, hash FROM journal ORDER BY n DESC LIMIT 1").fetchone() if colonnes else None
    ancien.close()
    if not colonnes or "id_demande" in colonnes:
        return ""
    nom = f"mediateur-archive-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.sqlite3"
    chemin.rename(DONNEES / nom)
    n, empreinte = derniere or (0, "0" * 64)
    return f"journal précédent archivé intact dans {nom} : {n} lignes, dernière empreinte {empreinte}"


ARCHIVE = archiver_ancien_journal()

# Une seule connexion SQLite, protégée par un verrou (les requêtes sont traitées en parallèle)
VERROU = threading.RLock()
base = sqlite3.connect(DONNEES / "mediateur.sqlite3", check_same_thread=False, isolation_level=None)
base.row_factory = sqlite3.Row
journal = Journal(base, VERROU)
with VERROU:
    # Ancienne forme de la table de travail (un seul attribut par demande) : on la reconstruit.
    # Seules les demandes en cours sont perdues ; le JOURNAL n'est jamais touché.
    colonnes = [c["name"] for c in base.execute("PRAGMA table_info(demandes)")]
    if colonnes and "attributs" not in colonnes:
        print("Table de travail « demandes » à l'ancienne forme : reconstruite (journal intact)", flush=True)
        base.execute("DROP TABLE demandes")
    base.executescript("""
        -- Demandes et volets : tables de TRAVAIL (modifiables), à ne pas confondre avec le journal (ajout seul).
        -- On n'y garde ni le nom ni l'identifiant en clair du citoyen : seulement son pseudonyme.
        CREATE TABLE IF NOT EXISTS demandes (
            id_demande TEXT PRIMARY KEY,
            requete TEXT NOT NULL,       -- empreinte de la demande (détecte un id réutilisé pour autre chose)
            agent TEXT NOT NULL, demandeur TEXT NOT NULL, demarche TEXT NOT NULL, finalite TEXT NOT NULL,
            base TEXT NOT NULL, sujet TEXT NOT NULL,
            attributs TEXT NOT NULL,     -- codes des attributs demandés, séparés par « + »
            registres TEXT NOT NULL,     -- registres correspondants, séparés par « + »
            statut TEXT NOT NULL,        -- en_cours | en_attente | confirmee | remise | refuse | indisponible
                                         -- | expiree | retiree | retiree_apres_remise | bloquee
            motif TEXT NOT NULL DEFAULT '',
            expire_le REAL NOT NULL DEFAULT 0,
            cree_le REAL NOT NULL DEFAULT 0   -- pour les limites de débit
        );
        -- Un volet = un attribut demandé à un registre
        CREATE TABLE IF NOT EXISTS volets (
            id_demande TEXT NOT NULL, attribut TEXT NOT NULL, registre TEXT NOT NULL,
            statut TEXT NOT NULL,        -- ok | refuse | indisponible
            motif TEXT NOT NULL DEFAULT '',
            valeur INTEGER,              -- réponse minimale (pour l'aperçu), effacée dès la remise
            jeton TEXT,                  -- réponse signée en attente, effacée dès la remise ou l'expiration
            PRIMARY KEY (id_demande, attribut)
        );
        -- Identifiants (jti) des réponses déjà acceptées : une réponse ne sert qu'une fois
        CREATE TABLE IF NOT EXISTS jti_vus (jti TEXT PRIMARY KEY);
    """)
    if "cree_le" not in [c["name"] for c in base.execute("PRAGMA table_info(demandes)")]:
        base.execute("ALTER TABLE demandes ADD COLUMN cree_le REAL NOT NULL DEFAULT 0")
if ARCHIVE:
    journal.ecrire(agent="systeme", evenement="archive", resultat="ok", motif=ARCHIVE)
# À chaque chargement, l'empreinte du catalogue entre dans le journal chaîné :
# on peut prouver quelles règles étaient en vigueur au moment d'une consultation.
journal.ecrire(agent="systeme", evenement="catalogue", resultat="ok",
               motif=f"catalogue chargé : {len(CAT['demarches'])} démarches, sha256 {CAT['empreinte']}")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def pseudonyme(sujet_ref: str) -> str:
    """HMAC-SHA256 (bibliothèque standard) : le journal ne contient jamais l'identifiant du citoyen."""
    return hmac.new(SECRET_PSEUDONYME, sujet_ref.encode("utf-8"), hashlib.sha256).hexdigest()


def service_de(agent: dict) -> str | None:
    """Groupe Keycloak de l'agent -> code du service demandeur (un et un seul)."""
    services = [code for code, s in CAT["services"].items() if s["groupe"] in agent["groupes"]]
    return services[0] if len(services) == 1 else None


def tracer(demande: dict, evenement: str, resultat: str, motif: str = "", **precisions) -> dict:
    """Écrit une ligne au journal : le fait, jamais la valeur d'un attribut.
    « precisions » remplace attribut et registre quand la ligne ne concerne qu'un volet."""
    champs = {"id_demande": demande["id_demande"], "agent": demande["agent"], "demandeur": demande["demandeur"],
              "demarche": demande["demarche"],
              "finalite": demande["finalite"], "base": demande["base"], "attribut": demande["attributs"],
              "registre": demande["registres"], "sujet": demande["sujet"]}
    return journal.ecrire(**champs | precisions, evenement=evenement, resultat=resultat, motif=motif)


def transmis(demande: dict) -> dict:
    """Attributs réellement obtenus (volets « ok ») : ce sont eux qu'on confirme, remet ou efface."""
    ok = [v for v in demande.get("volets", []) if v["statut"] == "ok"]
    if not ok:
        return {}
    return {"attribut": "+".join(v["attribut"] for v in ok), "registre": "+".join(v["registre"] for v in ok)}


def lire(id_demande: str) -> dict | None:
    with VERROU:
        ligne = base.execute("SELECT * FROM demandes WHERE id_demande = ?", (id_demande,)).fetchone()
        volets = base.execute("SELECT * FROM volets WHERE id_demande = ? ORDER BY rowid", (id_demande,)).fetchall()
    return dict(ligne) | {"volets": [dict(v) for v in volets]} if ligne else None


def changer(demande: dict, **champs):
    demande.update(champs)
    with VERROU:
        base.execute(f"UPDATE demandes SET {', '.join(f'{c} = ?' for c in champs)} WHERE id_demande = ?",
                     [*champs.values(), demande["id_demande"]])


def effacer_reponses(demande: dict):
    """Le médiateur ne garde aucune réponse au-delà du nécessaire."""
    for volet in demande.get("volets", []):
        volet.update(valeur=None, jeton=None)
    with VERROU:
        base.execute("UPDATE volets SET valeur = NULL, jeton = NULL WHERE id_demande = ?", (demande["id_demande"],))


def refuser(demande: dict, statut: str, evenement: str, motif: str) -> dict:
    tracer(demande, evenement, "refuse", motif, **transmis(demande))
    changer(demande, statut=statut, motif=motif)
    effacer_reponses(demande)
    return demande


def rafraichir(demande: dict) -> dict:
    """Consentement non donné (ou réponse non retirée) dans le délai : on efface les réponses."""
    if demande["statut"] in ("en_attente", "confirmee") and time.time() > demande["expire_le"]:
        refuser(demande, "expiree", "expiration", "délai de 10 minutes dépassé : rien n'a été remis")
    return demande


def etat(demande: dict, remise: bool = False) -> dict:
    """Ce que voit le guichet : jamais une valeur en clair. Les réponses signées « ok » ne partent
    qu'au moment de la remise ; un refus signé par un registre part tout de suite (il ne contient aucune donnée)."""
    volets = []
    for v in demande.get("volets", []):
        statut = v["statut"]
        if statut == "ok" and demande["statut"] in ("en_attente", "confirmee"):
            statut = "en_attente"                       # obtenu, mais l'usager n'a pas encore confirmé
        elif statut == "ok" and not remise:
            statut = "remise" if demande["statut"] == "remise" else "non_transmis"
        volet = {"attribut": v["attribut"], "registre": v["registre"], "statut": statut, "motif": v["motif"]}
        if v.get("jeton") and (v["statut"] != "ok" or remise):
            volet["jeton"] = v["jeton"]
        volets.append(volet)
    reponse = {"id_demande": demande["id_demande"], "statut": demande["statut"], "motif": demande["motif"],
               "demarche": demande["demarche"], "volets": volets}
    if demande["statut"] in ("en_attente", "confirmee"):
        reponse["expire_le"] = int(demande["expire_le"])
    return reponse


def remettre(demande: dict) -> dict:
    """Remise au guichet : les réponses signées partent une fois, puis le médiateur les efface."""
    tracer(demande, "remise", "ok", **transmis(demande))
    changer(demande, statut="remise")
    reponse = etat(demande, remise=True)
    effacer_reponses(demande)
    return reponse


# --- Appel des registres ---

async def interroger(demande: dict, code: str, parametres: dict, sujet_ref: str,
                     jeton_agent: str) -> tuple[str, bool | str, str]:
    """Demande UN attribut à son registre et vérifie TOUTE la réponse signée.
    Renvoie (« ok », oui/non, jeton) ou (« refus », motif public, jeton).
    Lève Indisponible (rien n'est deviné) ou ReponseCorrompue (ligne d'alerte)."""
    attribut = CAT["attributs"][code]
    registre = CAT["registres"][attribut["registre"]]
    corps = {"id_demande": demande["id_demande"], "attribut": code, "parametres": parametres,
             "sujet_ref": sujet_ref, "destinataire": demande["demandeur"]}
    try:
        jeton = await registres.appeler(registre["url"], corps, DELAI_REGISTRE, jeton_agent)
        # La clé publique vient du volume du registre, monté en LECTURE SEULE ici
        cle_publique = (CLES_PUBLIQUES / attribut["registre"] / "cle.pem").read_bytes()
    except registres.Indisponible as e:
        raise registres.Indisponible(f"{registre['nom']} indisponible ({e})")
    except FileNotFoundError:
        raise registres.Indisponible(f"{registre['nom']} : clé publique absente")
    statut, contenu, infos = registres.verifier(jeton, cle_publique, registre["emetteur"], demande["demandeur"],
                                                sujet_ref, demande["id_demande"], attribut, parametres)
    try:
        with VERROU:
            base.execute("INSERT INTO jti_vus (jti) VALUES (?)", (infos["jti"],))
    except sqlite3.IntegrityError:
        raise registres.ReponseCorrompue("réponse déjà utilisée (rejeu du jeton)")
    return statut, contenu, jeton


async def traiter_volet(demande: dict, demande_attribut: dict, sujet_ref: str, jeton_agent: str) -> dict:
    """Un volet = un attribut demandé à son registre. Renvoie toujours un volet, jamais une exception :
    un registre en panne n'empêche pas les autres de répondre."""
    code = demande_attribut["attribut"]
    registre = CAT["attributs"][code]["registre"]
    volet = {"id_demande": demande["id_demande"], "attribut": code, "registre": registre,
             "statut": "refuse", "motif": "", "valeur": None, "jeton": None}
    try:
        if registre in CAT["absence_vierge"]:
            # Casier « absence: vierge » : on vérifie D'ABORD à l'état civil que la personne existe
            # (sinon un identifiant inventé obtiendrait « casier vierge »)
            ou = {"attribut": "personne_connue", "registre": CAT["attributs"]["personne_connue"]["registre"]}
            connue, _, _ = await interroger(demande, "personne_connue", {}, sujet_ref, jeton_agent)
            tracer(demande, "reponse-registre", "ok" if connue == "ok" else "refuse", **ou)
            if connue != "ok":
                volet["motif"] = "identité non confirmée par l'état civil"
                tracer(demande, "demande", "refuse", volet["motif"], attribut=code, registre=registre)
                return volet
        statut, contenu, jeton = await interroger(demande, code, catalogue.resoudre(demande_attribut["parametres"]),
                                                  sujet_ref, jeton_agent)
    except registres.Indisponible as e:
        motif = f"{e}, rien n'a été deviné"
        volet.update(statut="indisponible", motif=motif[0].upper() + motif[1:])
        tracer(demande, "reponse-registre", "indisponible", volet["motif"], attribut=code, registre=registre)
        return volet
    except registres.ReponseCorrompue as e:
        volet["motif"] = f"réponse corrompue : {e}"
        tracer(demande, "alerte", "refuse", volet["motif"], attribut=code, registre=registre)
        return volet

    if statut == "refus":
        # Refus signé par le registre : transmis tel quel, le guichet en revérifie la signature
        volet.update(motif=contenu, jeton=jeton)
        tracer(demande, "reponse-registre", "refuse", contenu, attribut=code, registre=registre)
        return volet
    tracer(demande, "reponse-registre", "ok", attribut=code, registre=registre)
    return volet | {"statut": "ok", "valeur": int(contenu), "jeton": jeton}


# --- Limites de débit ---

def trop_de_demandes_sur_ce_citoyen(demande: dict) -> bool:
    """Un même service ne peut pas interroger sans fin la même personne : au-delà de LIMITE_PAR_CITOYEN
    demandes en 24 heures, la demande est bloquée (registres jamais appelés) et une ALERTE entre dans
    l'historique du citoyen (« Qui a consulté mes données »)."""
    if demande["agent"] in LIMITE_EXEMPTES:
        return False
    with VERROU:
        nombre = base.execute(
            "SELECT COUNT(*) FROM demandes WHERE demandeur = ? AND sujet = ? AND cree_le > ? "
            "AND statut != 'bloquee' AND id_demande != ?",
            (demande["demandeur"], demande["sujet"], time.time() - 86400, demande["id_demande"])).fetchone()[0]
    if nombre < LIMITE_PAR_CITOYEN:
        return False
    motif = (f"bloqué : plus de {LIMITE_PAR_CITOYEN} demandes du même service sur vous en 24 h, "
             "consultation à contrôler")
    tracer(demande, "alerte", "refuse", motif)
    changer(demande, statut="bloquee", motif=motif)
    return True


# --- Limite de débit : un agent qui consulte trop de citoyens DIFFÉRENTS est bloqué ---

def trop_de_citoyens(demande: dict) -> bool:
    """Au-delà de LIMITE_SUJETS citoyens distincts en FENETRE_LIMITE secondes, la demande est bloquée
    (registres jamais appelés) et une ALERTE entre dans l'historique de chaque citoyen concerné.
    Reconsulter un citoyen déjà consulté reste possible (ex. actualiser une demande)."""
    if demande["agent"] in LIMITE_EXEMPTES:
        return False
    depuis = time.time() - FENETRE_LIMITE
    with VERROU:
        deja = {l["sujet"] for l in base.execute(
            "SELECT DISTINCT sujet FROM demandes WHERE agent = ? AND cree_le > ? AND statut != 'bloquee' "
            "AND id_demande != ?", (demande["agent"], depuis, demande["id_demande"]))}
        bloque_avant = base.execute("SELECT 1 FROM demandes WHERE agent = ? AND cree_le > ? AND statut = 'bloquee' "
                                    "AND id_demande != ?", (demande["agent"], depuis, demande["id_demande"])).fetchone()
    if demande["sujet"] in deja or len(deja) < LIMITE_SUJETS:
        return False
    motif = (f"agent bloqué : plus de {LIMITE_SUJETS} citoyens différents consultés en "
             f"{FENETRE_LIMITE // 60} minutes, consultation à contrôler")
    # Au premier blocage, tous les citoyens déjà consultés par cet agent sont prévenus
    for sujet in ([] if bloque_avant else sorted(deja)):
        tracer(demande, "alerte", "refuse", motif, sujet=sujet)
    tracer(demande, "alerte", "refuse", motif)
    changer(demande, statut="bloquee", motif=motif)
    return True


# --- Côté guichet ---

UUID4 = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class Demande(BaseModel):
    model_config = ConfigDict(extra="forbid")       # aucun champ libre : on ne peut rien demander « en plus »
    id_demande: str = Field(pattern=UUID4)
    demarche: str = Field(max_length=64)
    sujet_ref: str = Field(pattern=r"^[A-Za-z0-9-]{1,64}$")
    finalite: str = Field(max_length=200)
    # Facultatif : si le demandeur précise des attributs, ce doit être EXACTEMENT ceux du catalogue
    attributs: list[str] | None = Field(default=None, max_length=10)


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


@app.post("/demandes")
async def creer_demande(d: Demande, agent: dict = Depends(agent_connecte)):
    demandeur = service_de(agent) or "inconnu"
    demarche = CAT["demarches"].get(d.demarche)
    prevus = [a["attribut"] for a in demarche["attributs"]] if demarche else []
    demande = {"id_demande": d.id_demande, "agent": agent["nom"], "demandeur": demandeur, "demarche": d.demarche,
               "finalite": d.finalite, "base": demarche["base"] if demarche else "", "sujet": pseudonyme(d.sujet_ref),
               "attributs": "+".join(prevus),
               "registres": "+".join(CAT["attributs"][a]["registre"] for a in prevus),
               "statut": "en_cours", "motif": "", "expire_le": 0, "cree_le": time.time()}
    demande["requete"] = hashlib.sha256(json.dumps(
        [agent["nom"], d.model_dump()], sort_keys=True).encode()).hexdigest()

    # Rejeu : même id_demande -> une seule exécution, le même résultat est renvoyé (registres non rappelés)
    with VERROU:
        existante = lire(d.id_demande)
        if existante is None:
            base.execute(f"INSERT INTO demandes ({', '.join(demande)}) VALUES ({', '.join('?' * len(demande))})",
                         list(demande.values()))
    if existante:
        if existante["requete"] != demande["requete"]:
            raise HTTPException(409, "identifiant de demande déjà utilisé pour une autre demande")
        return etat(rafraichir(existante))

    # 1. Règles du catalogue : service, démarche, attributs, finalité
    if demandeur == "inconnu":
        return etat(refuser(demande, "refuse", "demande", "service de l'agent indéterminé"))
    if demarche is None or demandeur not in demarche["services"]:
        return etat(refuser(demande, "refuse", "demande", "démarche non autorisée pour ce service"))
    if d.attributs is not None and d.attributs != prevus:
        return etat(refuser(demande, "refuse", "demande", "attributs non autorisés : le catalogue fixe ce que "
                            "cette démarche peut demander"))
    if d.finalite != demarche["finalite"]:
        return etat(refuser(demande, "refuse", "demande", "finalité non autorisée"))
    if trop_de_demandes_sur_ce_citoyen(demande) or trop_de_citoyens(demande):
        return etat(demande)
    tracer(demande, "demande", "ok")

    # 2. Un appel par attribut, tous EN PARALLÈLE : chaque registre a son délai, sa clé, son résultat
    volets = await asyncio.gather(*(traiter_volet(demande, a, d.sujet_ref, agent["jeton"])
                                    for a in demarche["attributs"]))
    demande["volets"] = volets
    with VERROU:
        for v in volets:
            # Seules les réponses « ok » restent en attente ; un refus signé part tout de suite au guichet
            garde = v | {"jeton": v["jeton"] if v["statut"] == "ok" else None}
            base.execute(f"INSERT INTO volets ({', '.join(garde)}) VALUES ({', '.join('?' * len(garde))})",
                         list(garde.values()))

    # 3. Rien d'exploitable : la demande s'arrête là (chaque volet garde son motif)
    if not any(v["statut"] == "ok" for v in volets):
        tous_en_panne = all(v["statut"] == "indisponible" for v in volets)
        motif = volets[0]["motif"] if len(volets) == 1 else "aucune réponse exploitable, rien n'a été deviné"
        changer(demande, statut="indisponible" if tous_en_panne else "refuse", motif=motif)
        return etat(demande)

    # 4. Base légale : remise immédiate. Consentement : en attente de l'usager (aperçu exact).
    changer(demande, expire_le=time.time() + DUREE_CONSENTEMENT)
    if demarche["base"] == "base_legale":
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


def libelles(code_demarche: str) -> dict:
    """{code d'attribut: sa demande dans le catalogue} pour une démarche (vide si elle a été retirée)."""
    demarche = CAT["demarches"].get(code_demarche, {})
    return {a["attribut"]: a for a in demarche.get("attributs", [])}


def apercu(demande: dict) -> dict:
    """Ce que l'usager voit AVANT : exactement ce qui partira, et rien d'autre."""
    service = CAT["services"].get(demande["demandeur"], {}).get("nom", demande["demandeur"])
    connus = libelles(demande["demarche"])
    attributs = [{"code": v["attribut"], "libelle": connus.get(v["attribut"], {}).get("libelle", v["attribut"]),
                  "parametres": connus.get(v["attribut"], {}).get("parametres", {}),
                  "valeur": "oui" if v["valeur"] else "non"}
                 for v in demande["volets"] if v["statut"] == "ok"]
    liste = " ; ".join(f"{a['libelle']} = {a['valeur']}" for a in attributs)
    return {"id_demande": demande["id_demande"], "service": service, "code_service": demande["demandeur"],
            "demarche": CAT["demarches"].get(demande["demarche"], {}).get("libelle", demande["demarche"]),
            "finalite": demande["finalite"], "attributs": attributs, "expire_le": int(demande["expire_le"]),
            "apercu": f"{service} recevra : {liste}. Rien d'autre."}


@app.get("/usagers/{sujet_ref}/en-attente", dependencies=[Depends(canal_usager)])
def en_attente(sujet_ref: str):
    with VERROU:
        ids = base.execute("SELECT id_demande FROM demandes WHERE sujet = ? AND statut = 'en_attente'",
                           (pseudonyme(sujet_ref),)).fetchall()
    demandes = [rafraichir(lire(i["id_demande"])) for i in ids]
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
    """UNE confirmation pour tout l'aperçu (un ou plusieurs attributs)."""
    demande = demande_de_l_usager(id_demande, usager)
    ligne = tracer(demande, "confirmation", "ok", **transmis(demande))
    changer(demande, statut="confirmee")
    return {"id_demande": id_demande, "statut": "confirmee", "empreinte": ligne["hash"]}


@app.post("/demandes/{id_demande}/refuser", dependencies=[Depends(canal_usager)])
def refuser_par_usager(id_demande: str, usager: Usager):
    demande = demande_de_l_usager(id_demande, usager)
    refuser(demande, "refuse", "refus-usager", "refusé par l'usager : rien n'a été transmis")
    return {"id_demande": id_demande, "statut": "refuse"}


@app.get("/usagers/{sujet_ref}/accords", dependencies=[Depends(canal_usager)])
def accords(sujet_ref: str):
    """Accords donnés par l'usager, qu'il peut retirer : pas encore remis (« en cours ») ou déjà remis."""
    with VERROU:
        ids = base.execute("SELECT id_demande FROM demandes WHERE sujet = ? AND base = 'consentement' "
                           "AND statut IN ('confirmee', 'remise') ORDER BY rowid DESC LIMIT 9",
                           (pseudonyme(sujet_ref),)).fetchall()
    resultat = []
    for i in ids:
        demande = rafraichir(lire(i["id_demande"]))
        if demande["statut"] not in ("confirmee", "remise"):
            continue
        connus = libelles(demande["demarche"])
        resultat.append({
            "id_demande": demande["id_demande"], "code_service": demande["demandeur"],
            "service": CAT["services"].get(demande["demandeur"], {}).get("nom", demande["demandeur"]),
            "demarche": CAT["demarches"].get(demande["demarche"], {}).get("libelle", demande["demarche"]),
            "attributs": [{"code": v["attribut"], "libelle": connus.get(v["attribut"], {}).get("libelle", v["attribut"])}
                          for v in demande["volets"] if v["statut"] == "ok"],
            "transmis": demande["statut"] == "remise"})
    return resultat


@app.post("/demandes/{id_demande}/retirer", dependencies=[Depends(canal_usager)])
def retirer(id_demande: str, usager: Usager):
    """Retrait de l'accord. Pas encore remis : plus rien ne partira. Déjà remis : on ne peut pas rappeler une
    réponse transmise, mais le retrait est écrit au journal (le service ne doit plus l'utiliser)."""
    demande = lire(id_demande)
    if demande is None or not hmac.compare_digest(demande["sujet"], pseudonyme(usager.sujet_ref)):
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["base"] != "consentement":
        raise HTTPException(409, "base légale : il n'y a pas d'accord à retirer")
    if demande["statut"] in ("en_attente", "confirmee"):
        motif = "accord retiré par l'usager : rien n'a été transmis"
        ligne = tracer(demande, "retrait", "ok", motif, **transmis(demande))
        changer(demande, statut="retiree", motif=motif)
        effacer_reponses(demande)
        return {"id_demande": id_demande, "statut": "retiree", "transmis": False, "empreinte": ligne["hash"]}
    if demande["statut"] == "remise":
        motif = "accord retiré après la transmission : le service ne doit plus utiliser la réponse"
        ligne = tracer(demande, "retrait", "ok", motif, **transmis(demande))
        changer(demande, statut="retiree_apres_remise", motif=motif)
        return {"id_demande": id_demande, "statut": "retiree_apres_remise", "transmis": True,
                "empreinte": ligne["hash"]}
    raise HTTPException(409, f"rien à retirer (statut : {demande['statut']})")


@app.get("/usagers/{sujet_ref}/historique", dependencies=[Depends(canal_usager)])
def historique(sujet_ref: str):
    """Qui a consulté, quand, pourquoi, sur quelle base. Jamais la valeur (le journal ne la contient pas)."""
    lignes = []
    for l in journal.lignes_du_sujet(pseudonyme(sujet_ref)):
        demarche = CAT["demarches"].get(l["demarche"], {})
        connus = libelles(l["demarche"])
        lignes.append({
            "n": l["n"], "ts": l["ts"], "agent": l["agent"],
            "service": CAT["services"].get(l["demandeur"], {}).get("nom", l["demandeur"]),
            "code_service": l["demandeur"],
            "demarche": demarche.get("libelle", l["demarche"]), "finalite": l["finalite"], "base": l["base"],
            "texte_base": demarche.get("texte", "") if l["base"] == "base_legale" else "",
            "attributs": [{"code": c, "libelle": connus.get(c, {}).get("libelle", c)}
                          for c in l["attribut"].split("+") if c],
            "evenement": l["evenement"], "resultat": l["resultat"],
            "motif": l["motif"], "empreinte": l["hash"]})
    return lignes

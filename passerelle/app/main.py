"""Médiateur : fait circuler les attributs UTILES des registres vers le guichet, avec consentement et traçabilité.

API JSON, joignable uniquement par le réseau Docker interne (jamais publiée par Caddy).
- Côté guichet (jeton Keycloak de l'agent) : POST /demandes, GET /demandes/{id}  (docs/API.md)
- Côté usager (canal authentifié par un secret partagé) : en-attente, confirmer, refuser, historique
  (docs/API_USAGER.md)
- Côté contrôleur (jeton Keycloak, rôle « controleur ») : GET /controle, GET /controle/verification
  (LECTURE SEULE)

Une demande = une démarche du catalogue = un ou plusieurs attributs (« volets »), chacun demandé à SON
registre, en parallèle. Le médiateur ne voit que les réponses minimales signées par les registres ; il les
garde en attente jusqu'à la confirmation de l'usager, puis les efface dès qu'elles sont remises ou expirées.
"""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import yaml
import re
import sqlite3
import sys
import threading
import time

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from consentement import catalogue, usager  # couche consentement-minimisation (même processus)
from consentement.usager import apercu, finalites_traduites, libelles, rafraichir  # noqa: F401 (apercu : tests)
from . import agents as modele_agents, contrat, registres
from .agents import agent_connecte, controleur_connecte
from .config import (CATALOGUE, CLES_PUBLIQUES, SECRETS, DELAI_REGISTRE, DONNEES, DUREE_CONSENTEMENT, FENETRE_LIMITE,
                     JOURNAL_VERIFIER, LIMITE_EXEMPTES, LIMITE_PAR_CITOYEN, LIMITE_SUJETS, OUTILS_TEST,
                     lire_secret)
from tracabilite.journal import Journal     # couche journal (même processus)
from regles_attributs import Refus, minimisation     # couche consentement-minimisation (même processus)

# Le contrat des registres et la correspondance de ses champs : lus au démarrage (CONFIGURATION, pas du code)
CONTRAT_CHARGE = contrat.charger()
CORRESPONDANCE = yaml.safe_load((CATALOGUE / "correspondance.yaml").read_text(encoding="utf-8"))

# Catalogue validé au démarrage. Copie du dernier catalogue VALIDE gardée dans le volume du médiateur :
# si le fichier est invalide au démarrage, on repart de cette copie au lieu de s'arrêter devant le jury.
COPIE_VALIDE = DONNEES / "catalogue-en-vigueur.yaml"
# Dernière version refusée : {"empreinte", "raison", "date"} (affichée au guichet et sur la page Contrôle)
REFUS_CATALOGUE: dict = {}


def essayer_catalogue(brut: bytes) -> tuple[dict | None, str]:
    """(catalogue, "") si valide, sinon (None, toutes les raisons). Ne lève jamais d'exception."""
    try:
        return catalogue.charger(brut), ""
    except catalogue.CatalogueInvalide as e:
        return None, str(e)
    except Exception as e:                       # forme inattendue (ex. un nombre à la place d'une liste)
        return None, f"  - fichier mal formé ({type(e).__name__} : {e})"


_brut = (catalogue.CATALOGUE / "demarches.yaml").read_bytes()
CAT, _raison = essayer_catalogue(_brut)
modele_agents.services_de_l_annuaire = lambda: CAT["services"]    # clés API des administrations
if CAT is None:
    print(f"CATALOGUE INVALIDE, refusé :\n{_raison}", flush=True)
    REFUS_CATALOGUE = {"empreinte": hashlib.sha256(_brut).hexdigest(), "raison": _raison,
                       "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    CAT, _ = essayer_catalogue(COPIE_VALIDE.read_bytes()) if COPIE_VALIDE.exists() else (None, "")
    if CAT is None:          # tout premier démarrage, aucune version valide connue : rien à garder
        raise SystemExit("CATALOGUE INVALIDE et aucune version valide précédente : le médiateur ne démarre pas.")
    print(f"Dernier catalogue valide gardé (sha256 {CAT['empreinte']})", flush=True)
else:
    COPIE_VALIDE.write_bytes(_brut)

# Format de l'identifiant de l'usager (annuaire.yaml, réglable pour les données du jury)
FORMAT_IDENTIFIANT = re.compile(CAT["identifiant"]["format"])


def controler_identifiant(sujet_ref: str):
    if not FORMAT_IDENTIFIANT.fullmatch(sujet_ref):
        raise HTTPException(422, f"identifiant d'usager au mauvais format (exemple : {CAT['identifiant']['exemple']})")


SECRET_PSEUDONYME = lire_secret("sujet_hmac").encode()
# Un secret par écran usager : le médiateur sait d'où vient une action (canal écrit au journal) sans croire
# l'écran sur parole. Un secret absent ou vide ferme ce canal (jamais « secret vide = tout le monde »).
def secret_canal(nom: str) -> bytes:
    try:
        return lire_secret(nom).encode()
    except FileNotFoundError:
        return b""


SECRETS_CANAUX = {"ussd": secret_canal("canal_usager"), "web": secret_canal("canal_web")}

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
        -- Accord de l'usager PAR DÉMARCHE : donné quand il confirme, valable « duree_accord_heures » (catalogue),
        -- retirable à tout moment. Tant qu'il est valable, la même démarche pour le même service est remise tout de
        -- suite. Aucune valeur, jamais : seulement qui (pseudonyme), pour quelle démarche, jusqu'à quand.
        CREATE TABLE IF NOT EXISTS accords (
            sujet TEXT NOT NULL, demandeur TEXT NOT NULL, demarche TEXT NOT NULL,
            donne_le REAL NOT NULL, expire_le REAL NOT NULL, retire_le REAL,
            PRIMARY KEY (sujet, demandeur, demarche)
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
if REFUS_CATALOGUE:
    journal.ecrire(agent="systeme", evenement="catalogue", resultat="refuse",
                   motif=f"catalogue refusé (sha256 {REFUS_CATALOGUE['empreinte']}), le dernier catalogue valide "
                         f"reste en vigueur : {REFUS_CATALOGUE['raison'].strip()[:900]}")

# Pas de page /docs en service : le contrat est dans openapi.yaml de chaque couche (scripts/generer_openapi.py)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title="Griot : passerelle d'échange",
              version="1.0")
# Une étiquette par couche, avec le vocabulaire du sujet : chaque openapi.yaml ne garde que les routes de sa couche
PASSERELLE, JOURNAL = "passerelle d'échange", "journal de traçabilité"

# --- Catalogue en direct : le fichier est relu dès qu'il change, sans redémarrer le médiateur ---
_VU = {"date": 0.0, "verification": 0.0}


def surveiller_catalogue():
    """Appelée avant chaque requête (au plus une fois par seconde). Fichier modifié :
    - valide   -> il remplace l'ancien catalogue ; sa nouvelle empreinte est écrite au journal ;
    - invalide -> REFUSÉ : l'ancien catalogue reste en vigueur, la raison est écrite au journal et affichée.
    Jamais d'arrêt du médiateur."""
    global CAT, FORMAT_IDENTIFIANT, REFUS_CATALOGUE
    maintenant = time.monotonic()
    if maintenant - _VU["verification"] < 1:
        return
    _VU["verification"] = maintenant
    chemins = [catalogue.CATALOGUE / "demarches.yaml", catalogue.CATALOGUE / "annuaire.yaml"]
    try:
        date = max(c.stat().st_mtime for c in chemins)
        if date == _VU["date"]:
            return
        brut = chemins[0].read_bytes()
    except OSError:
        return                                  # fichier en cours d'écriture : on regardera à la requête suivante
    _VU["date"] = date
    empreinte = hashlib.sha256(brut).hexdigest()
    if empreinte == REFUS_CATALOGUE.get("empreinte"):
        return                                  # même version déjà refusée : rien de nouveau
    nouveau, raison = essayer_catalogue(brut)
    with VERROU:
        if nouveau is None:
            REFUS_CATALOGUE = {"empreinte": empreinte, "raison": raison,
                               "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            print(f"CATALOGUE REFUSÉ (sha256 {empreinte}), l'ancien reste en vigueur :\n{raison}", flush=True)
            journal.ecrire(agent="systeme", evenement="catalogue", resultat="refuse",
                           motif=f"catalogue refusé (sha256 {empreinte}), le catalogue sha256 {CAT['empreinte']} "
                                 f"reste en vigueur : {raison.strip()[:900]}")
            return
        REFUS_CATALOGUE = {}
        if (nouveau["empreinte"] == CAT["empreinte"] and nouveau["services"] == CAT["services"]
                and nouveau["registres"] == CAT["registres"]):       # (une nouvelle URL de registre compte aussi)
            return                              # retour à la version en vigueur : rien à recharger
        CAT, FORMAT_IDENTIFIANT = nouveau, re.compile(nouveau["identifiant"]["format"])
        COPIE_VALIDE.write_bytes(brut)
        print(f"Catalogue rechargé : {len(CAT['demarches'])} démarches, sha256 {CAT['empreinte']}", flush=True)
        journal.ecrire(agent="systeme", evenement="catalogue", resultat="ok",
                       motif=f"catalogue rechargé : {len(CAT['demarches'])} démarches, sha256 {CAT['empreinte']}")


@app.middleware("http")
async def catalogue_a_jour(requete, suite):
    surveiller_catalogue()
    return await suite(requete)


@app.get("/catalogue", tags=[PASSERELLE])
def catalogue_public() -> dict:
    """Catalogue EN VIGUEUR (celui que le médiateur applique), pour le guichet. Ce sont des règles publiques :
    aucune donnée de citoyen. « refus » : dernière version refusée et sa raison (vide si aucune)."""
    return {"empreinte": CAT["empreinte"], "demarches": CAT["demarches"], "refus": REFUS_CATALOGUE}


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
    # Noms d'attributs seulement (jamais de valeurs) : demandés = ce que la démarche réclame ; refusés = volets
    # non « ok » (refusé ou registre indisponible) ; transmis = ce qui a réellement été remis (ligne « remise »).
    volets = demande.get("volets", [])
    champs |= {"attributs_demandes": demande["attributs"],
               "attributs_refuses": "+".join(v["attribut"] for v in volets if v["statut"] != "ok"),
               "attributs_transmis": ("+".join(v["attribut"] for v in volets if v["statut"] == "ok")
                                      if evenement == "remise" else "")}
    if (evenement in ("demande", "reponse-registre", "alerte") and resultat != "ok" and precisions.get("attribut")):
        champs["attributs_refuses"] = precisions["attribut"]       # ligne d'un volet refusé ou indisponible
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


def refuser(demande: dict, statut: str, evenement: str, motif: str, canal: str = "") -> dict:
    tracer(demande, evenement, "refuse", motif, canal=canal, **transmis(demande))
    changer(demande, statut=statut, motif=motif)
    effacer_reponses(demande)
    return demande


def etat(demande: dict, remise: bool = False) -> dict:
    """Ce que voit le guichet : une valeur (« majeur : oui ») n'existe dans la réponse qu'au moment de la remise ;
    avant, seulement le statut de chaque volet et son motif."""
    volets = []
    for v in demande.get("volets", []):
        statut = v["statut"]
        if statut == "ok" and demande["statut"] in ("en_attente", "confirmee"):
            statut = "en_attente"                       # obtenu, mais l'usager n'a pas encore confirmé
        elif statut == "ok" and not remise:
            statut = "remise" if demande["statut"] == "remise" else "non_transmis"
        volet = {"attribut": v["attribut"], "registre": v["registre"], "statut": statut, "motif": v["motif"]}
        if v["statut"] == "ok" and remise:      # la valeur n'existe côté guichet qu'à la remise, une seule fois
            volet["valeur"] = json.loads(v["valeur"]) if isinstance(v["valeur"], str) else bool(v["valeur"])
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


# --- Appel des registres (selon le contrat) ---

def cle_du_registre(registre: dict) -> tuple[str, str] | None:
    """Clé API d'un registre, si annuaire.yaml en déclare une : « en_tete_cle » (nom de l'en-tête) et « cle_secret »
    (nom du fichier dans /run/secrets). Rien d'autre n'est écrit dans le code : on branche un registre par configuration."""
    if not registre.get("en_tete_cle") or not registre.get("cle_secret"):
        return None
    try:
        return registre["en_tete_cle"], (SECRETS / registre["cle_secret"]).read_text(encoding="utf-8").strip()
    except OSError:
        raise registres.Indisponible(f"{registre['nom']} : clé API illisible")


async def lire_registre(registre_code: str, sujet_ref: str) -> dict:
    """Lit la fiche d'un citoyen dans UN registre et la VALIDE contre le contrat. Ne lève jamais d'exception :
    {"etat": "ok", "fiche": {...}} | {"etat": "inconnu"} | {"etat": "indisponible", "motif": …} | {"etat": "corrompu", "motif": …}.
    La fiche brute reste dans cette fonction et dans minimiser() : elle n'est jamais écrite ni renvoyée."""
    registre = CAT["registres"][registre_code]
    try:
        fiche = await registres.lire_fiche(registre["url"], registre["chemin"], sujet_ref, DELAI_REGISTRE,
                                           cle_du_registre(registre))
        ecarts = contrat.erreurs_de_conformite(CONTRAT_CHARGE, registre["chemin"], fiche)
        if ecarts:
            raise registres.ReponseCorrompue("non conforme au contrat (" + " ; ".join(ecarts[:3]) + ")")
        return {"etat": "ok", "fiche": fiche}
    except registres.CitoyenInconnu:
        return {"etat": "inconnu"}
    except registres.Indisponible as e:
        return {"etat": "indisponible", "motif": f"{registre['nom']} indisponible ({e})"}
    except registres.ReponseCorrompue as e:
        return {"etat": "corrompu", "motif": str(e)}
    except Exception as e:                   # jamais de plantage : une erreur imprévue = « indisponible », au journal
        return {"etat": "imprevu", "motif": type(e).__name__}


def volet_depuis_registre(demande: dict, demande_attribut: dict, lecture: dict) -> dict:
    """Un volet = un attribut demandé. Calcule l'attribut (minimisation) depuis la fiche lue, ou dit pourquoi pas.
    Renvoie toujours un volet, jamais une exception : un registre en panne n'empêche pas les autres de répondre."""
    code = demande_attribut["attribut"]
    definition = CAT["attributs"][code]
    registre = definition["registre"]
    nom = CAT["registres"][registre]["nom"]
    volet = {"id_demande": demande["id_demande"], "attribut": code, "registre": registre,
             "statut": "refuse", "motif": "", "valeur": None, "jeton": None}
    etat_lecture = lecture["etat"]
    if etat_lecture == "indisponible":
        volet.update(statut="indisponible", motif=lecture["motif"][0].upper() + lecture["motif"][1:] + ", rien n'a été deviné")
        tracer(demande, "reponse-registre", "indisponible", volet["motif"], attribut=code, registre=registre)
    elif etat_lecture == "imprevu":
        volet.update(statut="indisponible", motif="Erreur interne, rien n'a été deviné")
        tracer(demande, "alerte", "indisponible", f"erreur interne ({lecture['motif']})", attribut=code, registre=registre)
    elif etat_lecture == "inconnu":
        volet["motif"] = MOTIF_INCONNU
        tracer(demande, "reponse-registre", "refuse", MOTIF_INCONNU, attribut=code, registre=registre)
    elif etat_lecture == "corrompu":
        volet["motif"] = f"réponse corrompue : {lecture['motif']}"
        tracer(demande, "alerte", "refuse", volet["motif"], attribut=code, registre=registre)
    else:
        try:
            fiche = lecture["fiche"]
            # Décès : vérifié pour tout registre dont la correspondance déclare « date_deces » (aucun nom de registre en dur)
            if ("date_deces" in (CORRESPONDANCE.get("registres", {}).get(registre) or {})
                    and minimisation.lire_ou_vide(fiche, CORRESPONDANCE, registre, "date_deces")):
                raise Refus("personne décédée")
            resultat = minimisation.minimiser(definition, registre, fiche, CORRESPONDANCE,
                                              catalogue.resoudre(demande_attribut["parametres"]))
        except Refus as e:
            # Le motif précis (décédé, date incomplète…) reste ici : le guichet n'apprend rien de plus que « impossible »
            volet["motif"] = f"réponse impossible, s'adresser au {nom}"
            tracer(demande, "reponse-registre", "refuse", volet["motif"], attribut=code, registre=registre)
        else:
            tracer(demande, "reponse-registre", "ok", attribut=code, registre=registre)
            # Oui/non : 1 ou 0. Cases précises (identité, naissance et filiation) : texte JSON, effacé dès la remise.
            return volet | {"statut": "ok", "valeur": json.dumps(resultat, ensure_ascii=False)
                            if isinstance(resultat, dict) else int(resultat)}
    return volet


# --- Limites de débit ---

def exempte(agent: str) -> bool:
    """Comptes des tests de bout en bout (agent.banc…) : exemptés SEULEMENT si OUTILS_TEST=1.
    Pendant la démonstration (OUTILS_TEST=0), ils suivent les limites comme tout le monde."""
    return OUTILS_TEST and agent in LIMITE_EXEMPTES

def trop_de_demandes_sur_ce_citoyen(demande: dict) -> bool:
    """Un même service ne peut pas interroger sans fin la même personne : au-delà de LIMITE_PAR_CITOYEN
    demandes en 24 heures, la demande est bloquée (registres jamais appelés) et une ALERTE entre dans
    l'historique du citoyen (« Qui a consulté mes données »)."""
    if LIMITE_PAR_CITOYEN <= 0 or exempte(demande["agent"]):   # 0 = limite désactivée (voir config.py)
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

def limite_sujets() -> int:
    """Limite en vigueur : le fichier /donnees/limite_sujets (écrit par le banc de pannes pour son scénario
    « agent curieux ») l'emporte sur la configuration ; 0 = pas de limite."""
    try:
        return int((DONNEES / "limite_sujets").read_text().strip())
    except (OSError, ValueError):
        return LIMITE_SUJETS


def trop_de_citoyens(demande: dict) -> bool:
    """Au-delà de LIMITE_SUJETS citoyens distincts en FENETRE_LIMITE secondes, la demande est bloquée
    (registres jamais appelés) et une ALERTE entre dans l'historique de chaque citoyen concerné.
    Reconsulter un citoyen déjà consulté reste possible (ex. actualiser une demande)."""
    limite = limite_sujets()
    if limite <= 0 or exempte(demande["agent"]):
        return False
    depuis = time.time() - FENETRE_LIMITE
    with VERROU:
        deja = {l["sujet"] for l in base.execute(
            "SELECT DISTINCT sujet FROM demandes WHERE agent = ? AND cree_le > ? AND statut != 'bloquee' "
            "AND id_demande != ?", (demande["agent"], depuis, demande["id_demande"]))}
        bloque_avant = base.execute("SELECT 1 FROM demandes WHERE agent = ? AND cree_le > ? AND statut = 'bloquee' "
                                    "AND id_demande != ?", (demande["agent"], depuis, demande["id_demande"])).fetchone()
    if demande["sujet"] in deja or len(deja) < limite:
        return False
    motif = (f"agent bloqué : plus de {limite} citoyens différents consultés en "
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
    sujet_ref: str = Field(min_length=1, max_length=200)     # format : annuaire.yaml (controler_identifiant)
    finalite: str = Field(max_length=200)
    # Facultatif : si le demandeur précise des attributs, ce doit être EXACTEMENT ceux du catalogue
    attributs: list[str] | None = Field(default=None, max_length=10)


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


MOTIF_INCONNU = "citoyen inconnu"
# Refus « hors catalogue » (service, démarche, attributs ou finalité non prévus) -> HTTP 403
HORS_CATALOGUE = ("service de l'agent indéterminé", "démarche non autorisée", "attributs non autorisés",
                  "finalité non autorisée")
REPONSES_HTTP = {403: {"description": "HORS_CATALOGUE : démarche, attributs ou finalité hors catalogue"},
                 404: {"description": "CITOYEN_INCONNU : aucun registre ne connaît cette personne"},
                 503: {"description": "REGISTRE_INDISPONIBLE : registre éteint ou trop lent ; démarche « en attente »"}}


def reponse_http(corps: dict):
    """Code HTTP déduit de l'état de la demande (donc identique quand une demande est rejouée) :
    503 registre indisponible, 404 citoyen inconnu, 403 hors catalogue, sinon 200. Le corps reste le même."""
    if corps["statut"] == "indisponible":
        return JSONResponse(corps | {"code": "REGISTRE_INDISPONIBLE", "etat_demarche": "en_attente"}, status_code=503)
    if corps["statut"] == "refuse" and corps["motif"] == MOTIF_INCONNU:
        return JSONResponse(corps | {"code": "CITOYEN_INCONNU"}, status_code=404)
    if corps["statut"] == "refuse" and corps["motif"].startswith(HORS_CATALOGUE):
        return JSONResponse(corps | {"code": "HORS_CATALOGUE"}, status_code=403)
    return corps


@app.post("/demandes", tags=[PASSERELLE], responses=REPONSES_HTTP)
async def creer_demande(d: Demande, agent: dict = Depends(agent_connecte)):
    return reponse_http(await traiter_demande(d, agent))


async def traiter_demande(d: Demande, agent: dict) -> dict:
    controler_identifiant(d.sujet_ref)
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
    # (un appel par REGISTRE, tous en parallèle ; la fiche brute ne sort pas de lire_registre / minimiser)
    utiles = sorted({CAT["attributs"][a["attribut"]]["registre"] for a in demarche["attributs"]})
    lectures = dict(zip(utiles, await asyncio.gather(*(lire_registre(r, d.sujet_ref) for r in utiles))))
    volets = [volet_depuis_registre(demande, a, lectures[CAT["attributs"][a["attribut"]]["registre"]])
              for a in demarche["attributs"]]
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
        if all(v["motif"] == MOTIF_INCONNU for v in volets):
            motif = MOTIF_INCONNU
        changer(demande, statut="indisponible" if tous_en_panne else "refuse", motif=motif)
        return etat(demande)

    # 4. Base légale : remise immédiate. Consentement : en attente de l'usager (aperçu exact).
    changer(demande, expire_le=time.time() + DUREE_CONSENTEMENT)
    if demarche["base"] == "base_legale":
        return remettre(demande)
    if usager.accord_valide(demande):
        # L'usager a déjà donné son accord pour cette démarche, et il n'est ni expiré ni retiré : réponse immédiate
        tracer(demande, "accord-valide", "ok", "accord de l'usager encore valable : réponse remise sans nouvelle confirmation")
        return remettre(demande)
    changer(demande, statut="en_attente")
    return etat(demande)


@app.get("/demandes/{id_demande}", tags=[PASSERELLE], responses=REPONSES_HTTP)
def suivre_demande(id_demande: str, agent: dict = Depends(agent_connecte)):
    return reponse_http(etat_de_la_demande(id_demande, agent))


def etat_de_la_demande(id_demande: str, agent: dict) -> dict:
    demande = lire(id_demande)
    if demande is None or demande["agent"] != agent["nom"]:
        raise HTTPException(404, "demande introuvable")
    rafraichir(demande)
    if demande["statut"] == "confirmee":
        return remettre(demande)
    return etat(demande)


# --- Côté usager (USSD simulé, portail) : canal authentifié par un secret partagé ---

def canal_usager(x_cle_canal: str = Header("")) -> str:
    """Renvoie le canal (« ussd » ou « web ») d'après le secret présenté ; sinon 401."""
    for canal, secret in SECRETS_CANAUX.items():
        if secret and x_cle_canal and hmac.compare_digest(x_cle_canal.encode(), secret):
            return canal
    raise HTTPException(401, "canal usager non authentifié")


# Couche consentement et minimisation : en attente (aperçu), confirmer, refuser, accords, retirer, langues.
# Ses routes tournent ici et utilisent la base, le journal et le catalogue de la passerelle.
usager.brancher(sys.modules[__name__])
app.include_router(usager.routeur)


# --- Journal de traçabilité, lu par l'usager : qui a consulté ses données ---

@app.get("/usagers/{sujet_ref}/historique", dependencies=[Depends(canal_usager)], tags=[JOURNAL])
def historique(sujet_ref: str):
    """Qui a consulté, quand, pourquoi, sur quelle base. Jamais la valeur (le journal ne la contient pas)."""
    controler_identifiant(sujet_ref)
    lignes = []
    for l in journal.lignes_du_sujet(pseudonyme(sujet_ref)):
        demarche = CAT["demarches"].get(l["demarche"], {})
        connus = libelles(l["demarche"])
        lignes.append({
            "n": l["n"], "ts": l["ts"], "agent": l["agent"],
            "service": CAT["services"].get(l["demandeur"], {}).get("nom", l["demandeur"]),
            "code_service": l["demandeur"],
            "demarche": demarche.get("libelle", l["demarche"]), "finalite": l["finalite"],
            "finalites": finalites_traduites(demarche, l["finalite"]), "base": l["base"],
            "texte_base": demarche.get("texte", "") if l["base"] == "base_legale" else "",
            # « parametres » (seuils d'âge…) : pour composer le libellé dans une autre langue
            "attributs": [{"code": c, "libelle": connus.get(c, {}).get("libelle", c),
                           "parametres": connus.get(c, {}).get("parametres", {})}
                          for c in l["attribut"].split("+") if c],
            "evenement": l["evenement"], "resultat": l["resultat"],
            "motif": l["motif"], "canal": l.get("canal") or "", "empreinte": l["hash"]})
    return lignes


# --- Contrôle (rôle « controleur », LECTURE SEULE, comme le Security Officer de X-Road ou un DPD) ---
# Aucune route d'écriture, aucune valeur, aucun identifiant de citoyen (ni en clair ni pseudonymisé).

def nom_service(code: str) -> str:
    return CAT["services"].get(code, {}).get("nom", code)


def alertes() -> list[dict]:
    """Alertes (agent bloqué, réponse corrompue…) et refus des registres, les plus récents d'abord.
    Une alerte « agent bloqué » est écrite une fois par citoyen concerné : on les regroupe."""
    with VERROU:
        lignes = base.execute(
            "SELECT n, ts, agent, demandeur, demarche, registre, attribut, evenement, motif FROM journal "
            "WHERE evenement = 'alerte' OR (evenement = 'reponse-registre' AND resultat = 'refuse') "
            "ORDER BY n DESC LIMIT 200").fetchall()
    groupes = []
    for l in map(dict, lignes):
        precedente = groupes[-1] if groupes else None
        if precedente and all(precedente[c] == l[c] for c in ("ts", "agent", "evenement", "registre", "motif")):
            precedente["nombre"] += 1
            continue
        groupes.append(l | {"nombre": 1, "service": nom_service(l["demandeur"]),
                            "demarche": CAT["demarches"].get(l["demarche"], {}).get("libelle", l["demarche"])})
    return groupes[:50]


async def etat_registre(code: str, registre: dict) -> dict:
    """Le registre répond-il ? + dernier incident vu au journal (indisponible, réponse corrompue)."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            joignable = (await client.get(f"{registre['url']}/sante")).status_code == 200
    except httpx.HTTPError:
        joignable = False
    with VERROU:
        incident = base.execute(
            "SELECT ts, motif FROM journal WHERE registre = ? AND (resultat = 'indisponible' "
            "OR (evenement = 'alerte' AND motif LIKE 'réponse corrompue%')) ORDER BY n DESC LIMIT 1", (code,)).fetchone()
    return {"code": code, "nom": registre["nom"], "joignable": joignable,
            "dernier_incident": dict(incident) if incident else None}


def seuils(p: dict) -> str:
    """{min: 18, max: 37, date_reference: 2026-12-31} -> « 18 à 37 ans au 2026-12-31 »."""
    age = f"{p.get('min')} à {p['max']} ans" if p.get("max") is not None else f"{p.get('min')} ans et plus"
    return f"{age} au {p.get('date_reference')}"


def catalogue_en_vigueur() -> dict:
    """Démarches (qui peut demander quoi, pourquoi, sur quelle base) et autorisations déclarées par les registres
    (double clé). L'empreinte est celle écrite au journal au chargement."""
    demarches = [{"code": code, "libelle": d["libelle"], "services": [nom_service(s) for s in d["services"]],
                  "finalite": d["finalite"], "base": d["base"], "texte": d.get("texte", ""),
                  "attributs": [a.get("libelle", a["attribut"]) for a in d["attributs"]]}
                 for code, d in CAT["demarches"].items()]
    autorisations = []
    for code, a in CAT["attributs"].items():
        services = a["services"]
        if isinstance(services, dict):     # le registre fixe aussi les paramètres autorisés par service
            detail = [f"{nom_service(s)} : " + " ou ".join(map(seuils, params or [])) for s, params in services.items()]
        else:
            detail = [nom_service(s) for s in services]
        autorisations.append({"attribut": code, "registre": CAT["registres"][a["registre"]]["nom"],
                              "services": detail})
    return {"empreinte": CAT["empreinte"], "demarches": demarches, "autorisations": autorisations,
            "refus": REFUS_CATALOGUE}


@app.get("/controle", tags=[PASSERELLE])
async def controle(_controleur: str = Depends(controleur_connecte)):
    etats = await asyncio.gather(*(etat_registre(code, r) for code, r in CAT["registres"].items()))
    return {"comptes_de_test_actifs": OUTILS_TEST,
            "limites": {"citoyens_par_agent": limite_sujets(), "fenetre_minutes": FENETRE_LIMITE // 60,
                        "demandes_par_service_et_citoyen_24h": LIMITE_PAR_CITOYEN},
            "registres": etats, "alertes": alertes(), "catalogue": catalogue_en_vigueur()}


def charger_verifier():
    """Charge journal/verifier.py : c'est le MÊME code que la commande, rien n'est réécrit."""
    spec = importlib.util.spec_from_file_location("verifier", JOURNAL_VERIFIER)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    return verifier


@app.get("/journal/verification", tags=[JOURNAL])
def verification_du_journal():
    """Le journal est-il intact ? Réponse publique (réseau interne) : ni identifiant ni valeur, seulement
    « OK » ou le numéro de la première ligne modifiée ou supprimée. Sert au badge « journal intègre » de l'usager."""
    integre, message, lignes = charger_verifier().verifier(str(DONNEES / "mediateur.sqlite3"))
    ligne = None if integre else int(re.search(r"Ligne (\d+)", message).group(1))
    return {"statut": "OK" if integre else "ALTERE", "integre": integre, "lignes": len(lignes),
            "premiere_ligne_modifiee": ligne, "message": message}


@app.get("/controle/verification", tags=[JOURNAL])
def verification(_controleur: str = Depends(controleur_connecte)):
    """MÊME vérification que journal/verifier.py --registres (le même fichier est chargé, rien n'est réécrit)."""
    verifier = charger_verifier()
    chemin = str(DONNEES / "mediateur.sqlite3")
    integre, message, lignes = verifier.verifier(chemin)
    traces = verifier.traces_des_registres(chemin)
    return {"integre": integre, "message": message,
            "traces": {r: t if isinstance(t, str) else f"{len(t['trace'])} réponses signées, signature vérifiée"
                       for r, t in traces.items()},
            "ecarts": verifier.comparer(traces, lignes)}

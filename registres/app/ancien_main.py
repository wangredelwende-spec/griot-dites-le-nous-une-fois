"""Registre simulé : un seul code, une instance par registre (état civil, nationalité, casier).

Il ne renvoie JAMAIS la fiche du citoyen : seulement l'attribut demandé, calculé ici puis
SIGNÉ avec la clé Ed25519 du registre (JWT EdDSA, bibliothèque PyJWT). Le médiateur ne peut
donc ni lire la fiche, ni fabriquer une réponse, ni fabriquer un refus.
Joignable uniquement par le réseau Docker « registres » (médiateur seulement).
"""
import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .adaptateur import Adaptateur, Refus, SourceIndisponible

ADAPTATEUR = Adaptateur(Path(os.environ["ADAPTATEUR"]))
DUREE_VALIDITE = 600          # une réponse signée vaut 10 minutes
# Interrupteur de panne (banc de pannes) : resilience/panne.py écrit « lent » ou « corrompu » dans ce fichier
PANNE = Path(os.environ.get("PANNE", "/tmp/panne"))
CLES = Path(os.environ.get("CLES", "/cles"))                  # clé privée : volume de CE registre seulement
PUBLIQUE = Path(os.environ.get("PUBLIQUE", "/publique"))      # clé publique : volume monté en lecture seule
                                                              # chez le médiateur et le guichet


def empreinte_cle(cle_publique_pem: bytes) -> str:
    """Empreinte courte de la clé publique (SHA-256 de sa forme DER), à comparer avec celle du guichet."""
    der = serialization.load_pem_public_key(cle_publique_pem).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = hashlib.sha256(der).hexdigest()[:16]
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def charger_cle() -> Ed25519PrivateKey:
    """Clé générée au premier démarrage (par la bibliothèque cryptography), conservée dans le volume."""
    prive = CLES / "prive.pem"
    if not prive.exists():
        cle = Ed25519PrivateKey.generate()
        prive.write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        prive.chmod(0o600)
    cle = serialization.load_pem_private_key(prive.read_bytes(), password=None)
    publique = cle.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    (PUBLIQUE / "cle.pem").write_bytes(publique)
    print(f"Registre {ADAPTATEUR.registre} : empreinte de la clé publique {empreinte_cle(publique)}", flush=True)
    return cle


class NonAutorise(Exception):
    """Le service demandeur n'est pas dans la liste « services » de l'attribut (double clé)."""


# Jeton de l'agent : vérifié ICI avec les clés PUBLIQUES de Keycloak (réseau « cles-agents », sans Internet)
KEYCLOAK_CLES = os.environ.get("KEYCLOAK_CLES", "http://keycloak:8080/realms/griot/protocol/openid-connect/certs")
KEYCLOAK_EMETTEUR = os.environ.get("KEYCLOAK_EMETTEUR", "https://auth.griot.test/realms/griot")
CLES_KEYCLOAK = jwt.PyJWKClient(KEYCLOAK_CLES)
OUTILS_TEST = os.environ.get("OUTILS_TEST", "0") == "1"      # comptes de test « outil-test-* » refusés sauf si 1


def service_de_l_agent(authorization: str) -> str:
    """Le registre vérifie LUI-MÊME le jeton Keycloak de l'agent (signature, émetteur, audience, expiration,
    rôle) et en déduit le service par le groupe. Le médiateur ne peut donc plus inventer le demandeur."""
    if not authorization.startswith("Bearer "):
        raise NonAutorise("jeton d'agent absent")
    jeton = authorization.removeprefix("Bearer ")
    try:
        cle = CLES_KEYCLOAK.get_signing_key_from_jwt(jeton)
        infos = jwt.decode(jeton, cle.key, algorithms=["RS256"], audience="mediateur", issuer=KEYCLOAK_EMETTEUR)
    except jwt.PyJWKClientConnectionError:
        raise NonAutorise("clés de Keycloak injoignables : agent non vérifiable")
    except jwt.PyJWTError:
        raise NonAutorise("jeton d'agent invalide ou expiré")
    if "agent-guichet" not in infos.get("roles", []):
        raise NonAutorise("jeton sans le rôle agent-guichet")
    if str(infos.get("azp", "")).startswith("outil-test-") and not OUTILS_TEST:
        raise NonAutorise("compte de test refusé : outils de test désactivés")
    services = {ADAPTATEUR.groupes[g] for g in infos.get("groups", []) if g in ADAPTATEUR.groupes}
    if len(services) != 1:
        raise NonAutorise("service de l'agent non reconnu par ce registre")
    return services.pop()


CLE = charger_cle()
print(f"Registre {ADAPTATEUR.registre} : source {ADAPTATEUR.source['type']}"
      + (f", {len(ADAPTATEUR.lignes)} lignes, sha256 {ADAPTATEUR.empreinte_source}" if ADAPTATEUR.lignes is not None
         else " (interrogée à chaque demande)"), flush=True)

# --- Double trace : le registre garde SA liste des réponses signées (jamais la valeur, jamais le citoyen) ---
# Volume de CE registre seulement : le médiateur ne peut ni la lire en écriture ni la modifier.
# verifier.py --registres la compare au journal du médiateur : une consultation cachée par le médiateur
# (ligne supprimée puis chaîne recalculée) apparaît comme une réponse du registre absente du journal.
TRACE = Path(os.environ.get("TRACE", "/trace"))
VERROU_TRACE = threading.Lock()
TRACE_BASE = sqlite3.connect(TRACE / "trace.sqlite3", check_same_thread=False, isolation_level=None)
with VERROU_TRACE:
    TRACE_BASE.executescript("""
        CREATE TABLE IF NOT EXISTS reponses (
            n INTEGER PRIMARY KEY, ts TEXT NOT NULL, id_demande TEXT NOT NULL, jti TEXT NOT NULL,
            destinataire TEXT NOT NULL, attribut TEXT NOT NULL, statut TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS trace_sans_modification BEFORE UPDATE ON reponses
            BEGIN SELECT RAISE(ABORT, 'trace en ajout seul'); END;
        CREATE TRIGGER IF NOT EXISTS trace_sans_suppression BEFORE DELETE ON reponses
            BEGIN SELECT RAISE(ABORT, 'trace en ajout seul'); END;
        CREATE TABLE IF NOT EXISTS debut (ts TEXT NOT NULL);   -- date de création de la trace
    """)
    if not TRACE_BASE.execute("SELECT 1 FROM debut").fetchone():
        TRACE_BASE.execute("INSERT INTO debut VALUES (?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))


def tracer_reponse(charge: dict, attribut: str):
    """Une ligne par réponse SIGNÉE : qui, quoi, quand, ok ou refus. Ni la valeur, ni l'identifiant du citoyen."""
    with VERROU_TRACE:
        TRACE_BASE.execute(
            "INSERT INTO reponses (ts, id_demande, jti, destinataire, attribut, statut) VALUES (?, ?, ?, ?, ?, ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(charge["iat"])), charge["demande"], charge["jti"],
             charge["aud"], attribut, charge["statut"]))
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class DemandeAttribut(BaseModel):
    id_demande: str = Field(max_length=64)
    attribut: str = Field(max_length=64)
    parametres: dict[str, int | str | None] = {}    # ex. {"min": 18, "max": 37, "date_reference": "2026-12-31"}
    sujet_ref: str = Field(max_length=200)     # identifiant, ou clé composée « NOM|Prénoms|2001-03-14 »
    destinataire: str = Field(max_length=64)    # service demandeur : devient « aud » du jeton
    base: str = Field("", max_length=32)        # consentement | base_legale (vérifiée : bases du YAML)
    texte: str = Field("", max_length=1000)     # texte cité par la démarche (base légale)


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


@app.post("/attributs")
def attribut(d: DemandeAttribut, authorization: str = Header("")):
    """Réponse TOUJOURS signée : {"statut": "ok", <attribut>} ou {"statut": "refus", "motif": <motif public>}."""
    maintenant = int(time.time())
    charge = {"iss": ADAPTATEUR.emetteur, "aud": d.destinataire, "sub": d.sujet_ref, "demande": d.id_demande,
              "iat": maintenant, "exp": maintenant + DUREE_VALIDITE, "jti": str(uuid.uuid4())}
    try:
        # 1. Qui demande ? Le registre le vérifie lui-même dans le jeton de l'agent
        if service_de_l_agent(authorization) != d.destinataire:
            raise NonAutorise("le service déclaré ne correspond pas au jeton de l'agent")
        # 2. Double clé : ce service a-t-il droit à cet attribut, AVEC ces paramètres ?
        if not ADAPTATEUR.autorise(d.attribut, d.destinataire):
            raise NonAutorise("service non autorisé par le registre à demander cet attribut")
        aujourdhui = datetime.now(timezone.utc).date()
        if not ADAPTATEUR.parametres_autorises(d.attribut, d.destinataire, d.parametres, aujourdhui):
            raise NonAutorise("paramètres non autorisés par le registre pour ce service")
        # 3. Double clé sur le MODE : consentement ou base légale (avec un texte déclaré) pour CE service ?
        if not ADAPTATEUR.base_autorisee(d.destinataire, d.base, d.texte):
            raise NonAutorise("base juridique non autorisée par le registre pour ce service")
        charge |= {"statut": "ok", **ADAPTATEUR.calculer(d.attribut, d.sujet_ref, d.parametres)}
    except NonAutorise as motif:
        # Motif public précis : il concerne le DEMANDEUR, il ne dit rien du citoyen
        print(f"demande {d.id_demande} : refus ({motif})", flush=True)
        charge |= {"statut": "refus", "motif": str(motif)}
    except Refus as motif:
        # Le motif précis (décédé, homonyme…) reste ici : le guichet n'apprend rien de plus que « impossible ».
        # Trace locale sans identifiant du citoyen, pour le service du registre.
        print(f"demande {d.id_demande} : refus ({motif})", flush=True)
        charge |= {"statut": "refus", "motif": ADAPTATEUR.motif_refus_public}
    except SourceIndisponible as motif:
        # API du jury injoignable : « indisponible » n'est PAS signé (ce n'est pas une réponse du registre).
        # Le médiateur affichera « registre indisponible, rien n'a été deviné ».
        print(f"demande {d.id_demande} : source indisponible ({motif})", flush=True)
        return JSONResponse({"detail": "source du registre indisponible"}, status_code=503)
    jeton = jwt.encode(charge, CLE, algorithm="EdDSA")
    tracer_reponse(charge, d.attribut)

    # --- Simulation de pannes (démonstration uniquement) ---
    mode = PANNE.read_text().strip() if PANNE.exists() else "normal"
    if mode == "lent":
        time.sleep(10)          # bien au-delà du délai maximal du médiateur (3 s)
    elif mode == "corrompu":
        jeton = falsifier(jeton)
    return {"jeton": jeton}


@app.get("/trace")
def trace():
    """Export SIGNÉ de la trace (pour verifier.py --registres) : le médiateur ne peut pas la falsifier."""
    with VERROU_TRACE:
        debut = TRACE_BASE.execute("SELECT ts FROM debut").fetchone()[0]
        lignes = TRACE_BASE.execute("SELECT ts, id_demande, jti, destinataire, attribut, statut FROM reponses "
                                    "ORDER BY n").fetchall()
    maintenant = int(time.time())
    charge = {"iss": ADAPTATEUR.emetteur, "aud": "verification", "iat": maintenant, "exp": maintenant + 60,
              "debut": debut, "trace": [dict(zip(("ts", "id_demande", "jti", "destinataire", "attribut", "statut"), l))
                                        for l in lignes]}
    return {"jeton": jwt.encode(charge, CLE, algorithm="EdDSA")}


def falsifier(jeton: str) -> str:
    """Simule une réponse modifiée en chemin : on change le contenu SANS re-signer
    (comme le ferait un intermédiaire malveillant). La signature ne correspond donc plus."""
    entete, contenu, signature = jeton.split(".")
    claims = json.loads(base64.urlsafe_b64decode(contenu + "=" * (-len(contenu) % 4)))
    for nom, valeur in claims.items():
        if valeur is False:
            claims[nom] = True                  # « non » devient « oui »
        elif isinstance(valeur, dict):          # seuils d'âge : {"18": false} devient {"18": true}
            claims[nom] = {seuil: True for seuil in valeur}
    claims["exp"] += 3600                       # et la réponse vaudrait une heure de plus
    contenu = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{entete}.{contenu}.{signature}"

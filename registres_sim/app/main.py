"""Registre simulé : un seul code, une instance par registre (état civil, nationalité, casier).

Il ne renvoie JAMAIS la fiche du citoyen : seulement l'attribut demandé, calculé ici puis
SIGNÉ avec la clé Ed25519 du registre (JWT EdDSA, bibliothèque PyJWT). Le médiateur ne peut
donc ni lire la fiche, ni fabriquer une réponse.
Joignable uniquement par le réseau Docker « registres » (médiateur seulement).
"""
import os
import time
import uuid
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .adaptateur import Adaptateur, Refus

ADAPTATEUR = Adaptateur(Path(os.environ["ADAPTATEUR"]))
DUREE_VALIDITE = 600          # une réponse signée vaut 10 minutes
CLES = Path(os.environ.get("CLES", "/cles"))                    # volume privé de ce registre
PUBLIQUES = Path(os.environ.get("PUBLIQUES", "/publiques"))     # volume partagé, lu par médiateur et guichet


def charger_cle() -> Ed25519PrivateKey:
    """Clé générée au premier démarrage (par la bibliothèque cryptography), conservée dans le volume.
    La clé publique est déposée là où le médiateur et le guichet la lisent."""
    prive = CLES / "prive.pem"
    if not prive.exists():
        cle = Ed25519PrivateKey.generate()
        prive.write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
        prive.chmod(0o600)
    cle = serialization.load_pem_private_key(prive.read_bytes(), password=None)
    (PUBLIQUES / f"{ADAPTATEUR.registre}.pem").write_bytes(cle.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    return cle


CLE = charger_cle()
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class DemandeAttribut(BaseModel):
    id_demande: str = Field(max_length=64)
    attribut: str = Field(max_length=64)
    sujet_ref: str = Field(max_length=64)
    destinataire: str = Field(max_length=64)    # service demandeur : devient « aud » du jeton


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


@app.post("/attributs")
def attribut(d: DemandeAttribut):
    try:
        reponse_minimale = ADAPTATEUR.calculer(d.attribut, d.sujet_ref)
    except Refus as motif:
        return {"refus": str(motif)}
    maintenant = int(time.time())
    charge = {"iss": ADAPTATEUR.emetteur, "aud": d.destinataire, "sub": d.sujet_ref, "demande": d.id_demande,
              "iat": maintenant, "exp": maintenant + DUREE_VALIDITE, "jti": str(uuid.uuid4()),
              **reponse_minimale}
    return {"jeton": jwt.encode(charge, CLE, algorithm="EdDSA")}

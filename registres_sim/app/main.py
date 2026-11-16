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
# Interrupteur de panne (banc de pannes) : scripts/panne.py écrit « lent » ou « corrompu » dans ce fichier
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
    """Réponse TOUJOURS signée : {"statut": "ok", <attribut>} ou {"statut": "refus", "motif": <motif public>}."""
    maintenant = int(time.time())
    charge = {"iss": ADAPTATEUR.emetteur, "aud": d.destinataire, "sub": d.sujet_ref, "demande": d.id_demande,
              "iat": maintenant, "exp": maintenant + DUREE_VALIDITE, "jti": str(uuid.uuid4())}
    try:
        charge |= {"statut": "ok", **ADAPTATEUR.calculer(d.attribut, d.sujet_ref)}
    except Refus as motif:
        # Le motif précis (décédé, homonyme…) reste ici : le guichet n'apprend rien de plus que « impossible ».
        # Trace locale sans identifiant du citoyen, pour le service du registre.
        print(f"demande {d.id_demande} : refus ({motif})", flush=True)
        charge |= {"statut": "refus", "motif": ADAPTATEUR.motif_refus_public}
    jeton = jwt.encode(charge, CLE, algorithm="EdDSA")

    # --- Simulation de pannes (démonstration uniquement) ---
    mode = PANNE.read_text().strip() if PANNE.exists() else "normal"
    if mode == "lent":
        time.sleep(10)          # bien au-delà du délai maximal du médiateur (3 s)
    elif mode == "corrompu":
        jeton = falsifier(jeton, d.attribut)
    return {"jeton": jeton}


def falsifier(jeton: str, attribut: str) -> str:
    """Simule une réponse modifiée en chemin : on force « oui » SANS re-signer
    (comme le ferait un intermédiaire malveillant). La signature ne correspond donc plus."""
    entete, contenu, signature = jeton.split(".")
    claims = json.loads(base64.urlsafe_b64decode(contenu + "=" * (-len(contenu) % 4)))
    claims["statut"] = "ok"
    claims.pop("motif", None)
    regle = ADAPTATEUR.attributs.get(attribut, {"claim": "inconnu"})
    claims[regle["claim"]] = {str(regle["age"]): True} if "age" in regle else True     # « oui » forcé
    contenu = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{entete}.{contenu}.{signature}"

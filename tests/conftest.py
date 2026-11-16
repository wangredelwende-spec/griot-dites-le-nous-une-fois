"""Préparation des tests : dossiers temporaires, secrets de test, clé du registre simulée.

Le médiateur est testé SANS Docker : le registre est remplacé par respx (faux serveur HTTP)
qui signe ses réponses avec une clé Ed25519 de test.
"""
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RACINE = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="griot-tests-"))
for dossier in ("secrets", "donnees", "publiques"):
    (TMP / dossier).mkdir()
(TMP / "secrets/sujet_hmac").write_text("secret-de-test-pseudonyme")
(TMP / "secrets/canal_usager").write_text("secret-de-test-canal")
os.environ.update(GRIOT_SECRETS=str(TMP / "secrets"), GRIOT_DONNEES=str(TMP / "donnees"),
                  GRIOT_PUBLIQUES=str(TMP / "publiques"), GRIOT_REGLES=str(RACINE / "mediateur/regles.yaml"),
                  DELAI_REGISTRE="0.5")

CLE_REGISTRE = Ed25519PrivateKey.generate()
(TMP / "publiques/etat-civil.pem").write_bytes(CLE_REGISTRE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
URL_REGISTRE = "http://registre-etat-civil:8000/attributs"
CANAL = {"X-Cle-Canal": "secret-de-test-canal"}
CHEMIN_JOURNAL = TMP / "donnees/mediateur.sqlite3"

sys.path.insert(0, str(RACINE / "mediateur"))
from app import main as mediateur  # noqa: E402
from app.agents import agent_connecte  # noqa: E402


def jeton_registre(corps: dict, cle=CLE_REGISTRE, **modifs) -> str:
    """Réponse que signerait le vrai registre (on peut la modifier pour simuler une corruption)."""
    maintenant = int(time.time())
    charge = {"iss": "registre-etat-civil", "aud": corps["destinataire"], "sub": corps["sujet_ref"],
              "demande": corps["id_demande"], "iat": maintenant, "exp": maintenant + 600,
              "jti": str(uuid.uuid4()), "age_equal_or_over": {"18": True}}
    charge.update(modifs)
    return jwt.encode(charge, cle, algorithm="EdDSA")


AGENTS = {
    "awa.ouedraogo": ["Service des bourses"],
    "issa.sawadogo": ["Direction des concours de la fonction publique"],
}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    agent = {"nom": "issa.sawadogo"}
    mediateur.app.dependency_overrides[agent_connecte] = lambda: {"nom": agent["nom"],
                                                                 "groupes": AGENTS[agent["nom"]]}
    with TestClient(mediateur.app) as c:
        c.agent = agent     # c.agent["nom"] = "awa.ouedraogo" pour changer d'agent
        yield c
    mediateur.app.dependency_overrides.clear()


def demande(demarche="concours", sujet="BF-0001", **modifs) -> dict:
    finalites = {"concours": "vérification de l'âge minimal pour concourir", "bourse": "attribution de bourse"}
    d = {"id_demande": str(uuid.uuid4()), "demarche": demarche, "attribut": "majeur", "sujet_ref": sujet,
         "finalite": finalites[demarche]}
    d.update(modifs)
    return d

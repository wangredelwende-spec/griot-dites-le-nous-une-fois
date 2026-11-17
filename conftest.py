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
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RACINE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="griot-tests-"))
for dossier in ("secrets", "donnees", "publiques"):
    (TMP / dossier).mkdir()
(TMP / "secrets/sujet_hmac").write_text("secret-de-test-pseudonyme")
(TMP / "secrets/canal_usager").write_text("secret-de-test-canal")
(TMP / "secrets/canal_web").write_text("secret-de-test-canal-web")
os.environ.update(GRIOT_SECRETS=str(TMP / "secrets"), GRIOT_DONNEES=str(TMP / "donnees"),
                  GRIOT_PUBLIQUES=str(TMP / "publiques"), GRIOT_CATALOGUE=str(RACINE / "consentement-minimisation/catalogue"),
                  GRIOT_ADAPTATEURS=str(RACINE / "registres/adaptateurs"),
                  LIMITE_PAR_CITOYEN="1000", LIMITE_SUJETS="1000",   # des tests dédiés baissent les limites
                  DELAI_REGISTRE="0.5", GRIOT_VERIFIER=str(RACINE / "journal/verifier.py"))

CLE_REGISTRE = Ed25519PrivateKey.generate()
# Pour simplifier, les trois faux registres signent avec la même clé de test
for registre in ("etat-civil", "nationalite", "casier"):
    (TMP / "publiques" / registre).mkdir()
    (TMP / "publiques" / registre / "cle.pem").write_bytes(CLE_REGISTRE.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
URL_REGISTRE = "http://registre-etat-civil:8000/attributs"
URL_NATIONALITE = "http://registre-nationalite:8000/attributs"
URL_CASIER = "http://registre-casier:8000/attributs"
CANAL = {"X-Cle-Canal": "secret-de-test-canal"}
CHEMIN_JOURNAL = TMP / "donnees/mediateur.sqlite3"

# Le registre est enregistré sous le nom de paquet « registre_app » (le médiateur occupe déjà le nom « app »)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("registre_app", RACINE / "registres/app/__init__.py",
                                               submodule_search_locations=[str(RACINE / "registres/app")])
sys.modules["registre_app"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sys.modules["registre_app"])

# Même processus que dans le conteneur : passerelle (paquet app) + couches consentement et journal
for _couche in ("passerelle", "consentement-minimisation", "journal"):
    sys.path.insert(0, str((RACINE / _couche).resolve()))
from app import main as mediateur  # noqa: E402
from app.agents import agent_connecte  # noqa: E402


EMETTEURS = {"age_entre": "registre-etat-civil", "personne_connue": "registre-etat-civil",
             "nationalite_burkinabe": "registre-nationalite", "casier_judiciaire_vierge": "registre-casier",
             "interdiction_sortie_territoire": "registre-casier"}


def claims_attribut(corps: dict) -> dict:
    """Réponse « oui » que calculerait le registre pour l'attribut demandé."""
    if corps["attribut"] == "age_entre":
        p = corps["parametres"]
        ages = {str(p["min"]): True}
        if p.get("max") is not None:
            ages[str(p["max"] + 1)] = False             # « pas encore max + 1 ans »
        return {"age_equal_or_over": ages, "date_reference": p["date_reference"]}
    return {corps["attribut"]: True}


def jeton_registre(corps: dict, cle=CLE_REGISTRE, **modifs) -> str:
    """Réponse que signerait le vrai registre (on peut la modifier pour simuler une corruption)."""
    maintenant = int(time.time())
    charge = {"iss": EMETTEURS[corps["attribut"]], "aud": corps["destinataire"], "sub": corps["sujet_ref"],
              "demande": corps["id_demande"], "iat": maintenant, "exp": maintenant + 600,
              "jti": str(uuid.uuid4()), "statut": "ok", **claims_attribut(corps)}
    charge.update(modifs)
    for nom in [c for c, v in charge.items() if v is None]:     # modifs={"x": None} retire le claim x
        del charge[nom]
    return jwt.encode(charge, cle, algorithm="EdDSA")


def refus_registre(corps: dict, cle=CLE_REGISTRE, **modifs) -> str:
    """Refus signé, tel que l'émet le registre."""
    sans_attribut = {c: None for c in claims_attribut(corps)}
    return jeton_registre(corps, cle, **sans_attribut | {"statut": "refus",
                          "motif": "réponse impossible, s'adresser à l'état civil"} | modifs)


# Adaptateur de l'état civil lisant le CSV du dépôt (au lieu de /donnees dans Docker)
ADAPTATEUR_TEST = TMP / "etat-civil.yaml"
ADAPTATEUR_TEST.write_text((RACINE / "registres/adaptateurs/etat-civil.yaml").read_text(encoding="utf-8").replace(
    "/donnees/etat_civil.csv", (RACINE / "registres/donnees_fictives/etat_civil.csv").as_posix()),
    encoding="utf-8")


JETON_AGENT = "jeton-keycloak-de-test"     # transmis tel quel aux registres (qui le vérifient eux-mêmes)
AGENTS = {
    "awa.ouedraogo": ["Service des bourses"],
    "issa.sawadogo": ["Direction des concours – ministère des Serviteurs du peuple"],
    "agent.curieux": ["Service des bourses"],
    "moussa.kone": ["Service des passeports – ONI (ministère de la Sécurité)"],
}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    agent = {"nom": "issa.sawadogo"}
    mediateur.app.dependency_overrides[agent_connecte] = lambda: {"nom": agent["nom"], "jeton": JETON_AGENT,
                                                                 "groupes": AGENTS[agent["nom"]]}
    with TestClient(mediateur.app) as c:
        c.agent = agent     # c.agent["nom"] = "awa.ouedraogo" pour changer d'agent
        yield c
    mediateur.app.dependency_overrides.clear()


FINALITES = {code: d["finalite"] for code, d in
             yaml.safe_load((RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8"))["demarches"].items()}


def demande(demarche="verifier-majorite", sujet="BF-0001", **modifs) -> dict:
    d = {"id_demande": str(uuid.uuid4()), "demarche": demarche, "sujet_ref": sujet, "finalite": FINALITES[demarche]}
    d.update(modifs)
    return d

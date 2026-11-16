"""Registre simulé (application complète) : toute réponse est signée, un refus ne révèle rien."""
import importlib.util
import json
import os
import sys

import jwt
from fastapi.testclient import TestClient

from conftest import ADAPTATEUR_TEST, RACINE, TMP

# Le registre est chargé sous le nom « registre_app » (le médiateur occupe déjà le nom « app »)
for dossier in ("cles", "publique"):
    (TMP / dossier).mkdir(exist_ok=True)
os.environ.update(ADAPTATEUR=str(ADAPTATEUR_TEST), CLES=str(TMP / "cles"), PUBLIQUE=str(TMP / "publique"))
spec = importlib.util.spec_from_file_location("registre_app", RACINE / "registres_sim/app/__init__.py",
                                              submodule_search_locations=[str(RACINE / "registres_sim/app")])
sys.modules["registre_app"] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sys.modules["registre_app"])
from registre_app import main as registre  # noqa: E402

client = TestClient(registre.app)
CLE_PUBLIQUE = (TMP / "publique/cle.pem").read_bytes()


def demander(sujet: str) -> dict:
    r = client.post("/attributs", json={"id_demande": "d-1", "attribut": "majeur", "sujet_ref": sujet,
                                        "destinataire": "service-bourses"})
    assert set(r.json()) == {"jeton"}          # TOUJOURS une réponse signée, jamais du texte en clair
    return jwt.decode(r.json()["jeton"], CLE_PUBLIQUE, algorithms=["EdDSA"], audience="service-bourses")


def test_reponse_signee_minimale():
    infos = demander("BF-0001")
    assert infos["statut"] == "ok" and infos["age_equal_or_over"] == {"18": True}
    assert set(infos) == {"iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut", "age_equal_or_over"}


def test_refus_signe_et_generique():
    # Vers 1990, décédée, doublon, introuvable : le guichet reçoit le MÊME motif, signé
    motifs = {demander(sujet)["motif"] for sujet in ("BF-0004", "BF-0007", "BF-0019", "BF-0099")}
    assert motifs == {"réponse impossible, s'adresser à l'état civil"}
    infos = demander("BF-0007")
    assert infos["statut"] == "refus" and "age_equal_or_over" not in infos
    assert "décéd" not in json.dumps(infos, ensure_ascii=False)


def test_empreinte_de_la_cle():
    empreinte = registre.empreinte_cle(CLE_PUBLIQUE)
    assert len(empreinte) == 19 and len(empreinte.replace(" ", "")) == 16

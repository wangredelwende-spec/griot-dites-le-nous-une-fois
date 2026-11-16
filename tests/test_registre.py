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


def demander(sujet: str, attribut: str = "age_entre", service: str = "service-bourses") -> dict:
    r = client.post("/attributs", json={"id_demande": "d-1", "attribut": attribut, "sujet_ref": sujet,
                                        "parametres": {"min": 18, "date_reference": "2026-11-16"},
                                        "destinataire": service})
    assert set(r.json()) == {"jeton"}          # TOUJOURS une réponse signée, jamais du texte en clair
    return jwt.decode(r.json()["jeton"], CLE_PUBLIQUE, algorithms=["EdDSA"], audience=service)


def test_reponse_signee_minimale():
    infos = demander("BF-0001")
    assert infos["statut"] == "ok" and infos["age_equal_or_over"] == {"18": True}
    assert infos["date_reference"] == "2026-11-16"
    assert set(infos) == {"iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut", "age_equal_or_over",
                          "date_reference"}


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


def test_double_cle_le_registre_refuse_un_service_non_autorise():
    """Même si le médiateur laissait passer, le registre refuse (signé) un service absent de sa liste."""
    infos = demander("BF-0001", attribut="personne_connue", service="mairie")
    assert infos["statut"] == "refus" and infos["motif"].startswith("service non autorisé")
    assert "personne_connue" not in infos


def test_mode_corrompu_casse_la_signature():
    jeton = client.post("/attributs", json={"id_demande": "d-1", "attribut": "age_entre", "sujet_ref": "BF-0003",
                                            "parametres": {"min": 18, "date_reference": "2026-11-16"},
                                            "destinataire": "mairie"}).json()["jeton"]
    falsifie = registre.falsifier(jeton)
    import pytest
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(falsifie, CLE_PUBLIQUE, algorithms=["EdDSA"], audience="mairie")
    infos = jwt.decode(falsifie, options={"verify_signature": False})
    assert infos["age_equal_or_over"] == {"18": True}        # « non » devenu « oui », sans re-signer

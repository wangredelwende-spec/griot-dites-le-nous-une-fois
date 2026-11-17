"""Registre simulé (application complète) : toute réponse est signée, un refus ne révèle rien."""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from conftest import ADAPTATEUR_TEST, RACINE, TMP

# Le registre est chargé sous le nom « registre_app » (le médiateur occupe déjà le nom « app »)
for dossier in ("cles", "publique", "trace"):
    (TMP / dossier).mkdir(exist_ok=True)
os.environ.update(ADAPTATEUR=str(ADAPTATEUR_TEST), CLES=str(TMP / "cles"), PUBLIQUE=str(TMP / "publique"),
                  TRACE=str(TMP / "trace"))
from registre_app import main as registre  # noqa: E402  (paquet enregistré par conftest.py)

client = TestClient(registre.app)
CLE_PUBLIQUE = (TMP / "publique/cle.pem").read_bytes()
AUJOURDHUI = datetime.now(timezone.utc).date().isoformat()
MAJORITE = {"min": 18, "date_reference": AUJOURDHUI}

# Faux Keycloak : une clé RSA de test. Le registre vérifie le jeton de l'agent avec SA clé publique.
CLE_KEYCLOAK = rsa.generate_private_key(public_exponent=65537, key_size=2048)
GROUPES = {"service-bourses": "Service des bourses", "direction-concours": "Direction des concours – ministère des Serviteurs du peuple",
           "mairie": "Mairie", "service-passeport": "Service des passeports – ONI (ministère de la Sécurité)"}


class FauxKeycloak:
    def get_signing_key_from_jwt(self, _jeton):
        return SimpleNamespace(key=CLE_KEYCLOAK.public_key())


registre.CLES_KEYCLOAK = FauxKeycloak()


def jeton_agent(service: str = "service-bourses", cle=CLE_KEYCLOAK, **modifs) -> str:
    maintenant = int(time.time())
    charge = {"iss": "https://auth.griot.test/realms/griot", "aud": "mediateur", "exp": maintenant + 300,
              "iat": maintenant, "preferred_username": "agent.test", "roles": ["agent-guichet"],
              "groups": [GROUPES[service]]} | modifs
    return jwt.encode(charge, cle, algorithm="RS256")


# Base juridique envoyée par défaut : base légale citant les deux textes déclarés par l'état civil
BASE = {"base": "base_legale", "texte": "Code des personnes et de la famille, loi n°012-2025/ALT ; loi n°081-2015/CNT"}


def demander(sujet: str, attribut: str = "age_entre", service: str = "service-bourses", parametres=None,
             jeton: str | None = None, base: dict = BASE) -> dict:
    parametres = MAJORITE if parametres is None and attribut == "age_entre" else (parametres or {})
    # jeton="" : AUCUN en-tête Authorization (appel direct au registre, sans agent)
    entetes = {} if jeton == "" else {"Authorization": f"Bearer {jeton if jeton is not None else jeton_agent(service)}"}
    r = client.post("/attributs", headers=entetes, json={"id_demande": "d-1", "attribut": attribut, "sujet_ref": sujet,
                                                         "parametres": parametres, "destinataire": service} | base)
    assert set(r.json()) == {"jeton"}          # TOUJOURS une réponse signée, jamais du texte en clair
    return jwt.decode(r.json()["jeton"], CLE_PUBLIQUE, algorithms=["EdDSA"], audience=service)


def test_reponse_signee_minimale():
    infos = demander("BF-0001")
    assert infos["statut"] == "ok" and infos["age_equal_or_over"] == {"18": True}
    assert infos["date_reference"] == AUJOURDHUI
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
    jeton = client.post("/attributs", headers={"Authorization": f"Bearer {jeton_agent('mairie')}"},
                        json={"id_demande": "d-1", "attribut": "age_entre", "sujet_ref": "BF-0003",
                              "parametres": MAJORITE, "destinataire": "mairie"} | BASE).json()["jeton"]
    falsifie = registre.falsifier(jeton)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(falsifie, CLE_PUBLIQUE, algorithms=["EdDSA"], audience="mairie")
    infos = jwt.decode(falsifie, options={"verify_signature": False})
    assert infos["age_equal_or_over"] == {"18": True}        # « non » devenu « oui », sans re-signer


# --- A. Le registre vérifie LUI-MÊME le jeton de l'agent ---

@pytest.mark.parametrize("jeton, motif", [
    ("", "jeton d'agent absent"),
    ("pas-un-jeton", "jeton d'agent invalide"),
    (jeton_agent(cle=rsa.generate_private_key(public_exponent=65537, key_size=2048)), "jeton d'agent invalide"),
    (jeton_agent(exp=int(time.time()) - 60), "jeton d'agent invalide ou expiré"),
    (jeton_agent(roles=[]), "rôle agent-guichet"),
    (jeton_agent(groups=["Groupe inconnu"]), "service de l'agent non reconnu"),
])
def test_appel_sans_jeton_d_agent_valide_refuse(jeton, motif):
    """Sans jeton d'agent valide, le registre refuse (réponse signée), même si le médiateur a laissé passer."""
    infos = demander("BF-0001", jeton=jeton)
    assert infos["statut"] == "refus" and motif in infos["motif"] and "age_equal_or_over" not in infos


def test_service_declare_different_du_jeton_refuse():
    """Le médiateur déclare « direction-concours », mais le jeton est celui d'un agent des bourses."""
    infos = demander("BF-0001", service="direction-concours", jeton=jeton_agent("service-bourses"))
    assert infos["statut"] == "refus" and "ne correspond pas au jeton" in infos["motif"]


# --- B. Double clé sur les paramètres : impossible de reconstituer une date de naissance ---

def test_parametres_declares_acceptes():
    infos = demander("BF-0001", service="direction-concours",
                     parametres={"min": 18, "max": 37, "date_reference": "2026-12-31"})
    assert infos["statut"] == "ok" and infos["age_equal_or_over"] == {"18": True, "38": False}


@pytest.mark.parametrize("service, parametres", [
    ("direction-concours", {"min": 18, "max": 36, "date_reference": "2026-12-31"}),    # autre seuil
    ("direction-concours", {"min": 18, "max": 37, "date_reference": "2026-06-30"}),    # autre date
    ("service-bourses", {"min": 25, "date_reference": AUJOURDHUI}),                    # seuil de 25 ans
    ("service-bourses", {"min": 18, "date_reference": "2019-03-14"}),                  # autre jour
    ("service-bourses", {"min": 18, "max": 37, "date_reference": "2026-12-31"}),       # seuils d'un autre service
])
def test_autres_seuils_refuses(service, parametres):
    infos = demander("BF-0001", service=service, parametres=parametres)
    assert infos["statut"] == "refus" and infos["motif"] == "paramètres non autorisés par le registre pour ce service"
    assert "age_equal_or_over" not in infos


def test_reconstitution_de_la_date_de_naissance_impossible():
    """Balayer les seuils 19, 20, … 40 pour encadrer l'âge : TOUS refusés, aucune information."""
    reponses = [demander("BF-0001", service="direction-concours",
                         parametres={"min": n, "date_reference": AUJOURDHUI}) for n in range(19, 41)]
    assert all(r["statut"] == "refus" for r in reponses)


# --- Double trace : le registre garde la liste de ses réponses signées ---

def test_trace_des_reponses_sans_valeur_ni_citoyen():
    import sqlite3
    demander("BF-0008", service="direction-concours", parametres={"min": 18, "max": 37, "date_reference": "2026-12-31"})
    export = jwt.decode(client.get("/trace").json()["jeton"], CLE_PUBLIQUE, algorithms=["EdDSA"],
                        audience="verification")                     # export SIGNÉ par le registre
    derniere = export["trace"][-1]
    assert set(derniere) == {"ts", "id_demande", "jti", "destinataire", "attribut", "statut"}
    assert derniere["destinataire"] == "direction-concours" and derniere["statut"] == "ok"
    assert "BF-0008" not in json.dumps(export) and "true" not in json.dumps(export).lower()
    base = sqlite3.connect(TMP / "trace/trace.sqlite3", isolation_level=None)
    with pytest.raises(sqlite3.DatabaseError, match="ajout seul"):
        base.execute("DELETE FROM reponses")
    base.close()


def test_compte_de_test_refuse_si_outils_desactives(monkeypatch):
    jeton = jeton_agent("direction-concours", azp="outil-test-concours")
    monkeypatch.setattr(registre, "OUTILS_TEST", False)
    infos = demander("BF-0001", service="direction-concours", jeton=jeton)
    assert infos["statut"] == "refus" and "outils de test désactivés" in infos["motif"]
    monkeypatch.setattr(registre, "OUTILS_TEST", True)
    assert demander("BF-0001", service="direction-concours", jeton=jeton)["statut"] == "ok"


def test_source_indisponible_503_non_signe(monkeypatch):
    """API du jury injoignable : le registre répond 503 SANS rien signer ni tracer (« indisponible »),
    le médiateur affiche « registre indisponible, rien n'a été deviné »."""
    def panne(*_a, **_k):
        raise registre.SourceIndisponible("API du registre injoignable ou trop lente")
    avant = registre.TRACE_BASE.execute("SELECT COUNT(*) FROM reponses").fetchone()[0]
    monkeypatch.setattr(registre.ADAPTATEUR, "calculer", panne)
    r = client.post("/attributs", headers={"Authorization": f"Bearer {jeton_agent()}"},
                    json={"id_demande": "d-api", "attribut": "age_entre", "sujet_ref": "BF-0001",
                          "destinataire": "service-bourses", "parametres": MAJORITE} | BASE)
    assert r.status_code == 503 and "jeton" not in r.json()
    assert registre.TRACE_BASE.execute("SELECT COUNT(*) FROM reponses").fetchone()[0] == avant


# --- Double clé sur le MODE : consentement / base légale déclarés par le registre, par service ---

TEXTE_PASSEPORT = "Décret relatif au passeport ordinaire (texte inventé pour le test)"


def test_registre_refuse_lui_meme_le_passeport_en_base_legale(monkeypatch):
    """Le registre de la nationalité accepte le passeport SEULEMENT avec l'accord de l'usager (consentement)."""
    sys.path.insert(0, str(RACINE / "tests"))
    from test_adaptateur import charger
    monkeypatch.setattr(registre, "ADAPTATEUR", charger("nationalite"))
    passeport = {"attribut": "nationalite_burkinabe", "service": "service-passeport"}
    assert demander("BF-0001", **passeport, base={"base": "consentement"})["statut"] == "ok"
    for base in ({"base": "base_legale", "texte": TEXTE_PASSEPORT},
                 {"base": "base_legale", "texte": "loi n°081-2015/CNT"},     # texte déclaré, mais pour le concours
                 {"base": ""}, {"base": "deviner"}):
        infos = demander("BF-0001", **passeport, base=base)
        assert infos["statut"] == "refus" and infos["motif"] == "base juridique non autorisée par le registre pour ce service"
        assert "nationalite_burkinabe" not in infos


def test_base_legale_sans_reference_declaree_refusee():
    """État civil, mairie : base légale acceptée avec la loi n°012-2025/ALT, refusée avec un autre texte ;
    consentement refusé (non déclaré pour la mairie)."""
    assert demander("BF-0001", service="mairie")["statut"] == "ok"
    for base in ({"base": "base_legale", "texte": "arrêté municipal"}, {"base": "consentement"}):
        motif = demander("BF-0001", service="mairie", base=base)["motif"]
        assert motif == "base juridique non autorisée par le registre pour ce service"

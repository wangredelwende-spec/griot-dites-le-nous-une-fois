"""API du jury EN DIRECT à travers le relais (profil « api-jury »), et export unique (option par défaut).

Ici sans Docker : une fausse API locale, le relais (relais_api_jury/relais.py) dans un fil, et un registre dont
l'adaptateur vise le relais. Le registre ne connaît ni l'adresse de l'API ni son jeton.
"""
import hashlib
import importlib.util
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from conftest import RACINE, TMP
from test_formats import MAJEUR, FausseApi, adaptateur, charger, majeur

spec = importlib.util.spec_from_file_location("relais", RACINE / "relais_api_jury/relais.py")
relais = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relais)


def demarrer(serveur):
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    return serveur.server_address[1]


@pytest.fixture
def pile():
    """Fausse API du jury + relais (délai 1 s). Renvoie (port du relais, fausse API pour pouvoir la couper)."""
    (TMP / "secrets/api_jury").write_text("jeton-jury-de-test")
    api = ThreadingHTTPServer(("127.0.0.1", 0), FausseApi)
    port_api = demarrer(api)
    os.environ.update(API_JURY_URL=f"http://127.0.0.1:{port_api}", DELAI_API_JURY="1")
    serveur_relais = relais.serveur(0)
    port_relais = demarrer(serveur_relais)
    yield port_relais, api
    serveur_relais.shutdown()


def registre_via_relais(port: int):
    """Adaptateur API dont l'adresse est le RELAIS, sans jeton (c'est le relais qui l'ajoute)."""
    return charger("etat-civil-api.yaml", **{
        "http://127.0.0.1:{port}/personnes": f"http://127.0.0.1:{port}/personnes",
        '    Authorization: "Bearer {secret:api_jury}"   # valeur dans .env (API_JURY_SECRET), jamais dans ce fichier':
            '    Accept: application/json'})


def test_registre_interroge_l_api_a_travers_le_relais(pile):
    registre = registre_via_relais(pile[0])
    assert majeur(registre, "BF-0001") is True                 # le relais a ajouté le jeton
    assert majeur(registre, "BF-0003") is False
    assert majeur(registre, "BF-0099") == "refus : introuvable"  # 404 transmis tel quel


def test_api_coupee_ou_lente_indisponible(pile):
    port, api = pile
    registre = registre_via_relais(port)
    with pytest.raises(adaptateur.SourceIndisponible):
        registre.calculer("age_entre", "BF-LENT", MAJEUR)      # 2 s > délai du relais (1 s) -> 504
    api.shutdown()
    api.server_close()                                          # API du jury coupée
    with pytest.raises(adaptateur.SourceIndisponible):
        registre.calculer("age_entre", "BF-0001", MAJEUR)


def test_relais_lecture_seule_et_destination_unique(pile):
    base = f"http://127.0.0.1:{pile[0]}"
    # « //autre-serveur… » : le serveur HTTP de Python le ramène à « /autre-serveur… », qui part vers l'API
    # CONFIGURÉE (404 de la fausse API) : jamais vers un autre serveur.
    for methode, chemin, attendu in (("POST", "/personnes", 405), ("GET", "//autre-serveur.example/x", 404),
                                     ("GET", "/http://autre-serveur.example/x", 400)):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(urllib.request.Request(base + chemin, method=methode, data=b"" if methode == "POST"
                                                          else None), timeout=5)
        assert e.value.code == attendu, (methode, chemin)
    assert urllib.request.urlopen(base + "/__sante", timeout=5).read() == b"ok"


def test_export_unique_avec_empreinte(pile, monkeypatch, capsys):
    """Option par défaut : un export JSON avec son empreinte, puis un registre « type: json » sans réseau."""
    spec_e = importlib.util.spec_from_file_location("exporter", RACINE / "scripts/exporter_api_jury.py")
    exporter = importlib.util.module_from_spec(spec_e)
    spec_e.loader.exec_module(exporter)
    url = f"http://127.0.0.1:{pile[0]}/personnes?nip=BF-0001"          # à travers le relais : jeton ajouté
    monkeypatch.setattr(sys, "argv", ["exporter", url, "essai_export_api"])
    exporter.main()
    fichier, provenance = RACINE / "donnees_jury/essai_export_api.json", RACINE / "donnees_jury/essai_export_api.provenance.json"
    try:
        p = json.loads(provenance.read_text(encoding="utf-8"))
        assert p["sha256"] == hashlib.sha256(fichier.read_bytes()).hexdigest()
        assert "nip=" not in p["source"]                              # pas d'identifiant dans la provenance
        assert json.loads(fichier.read_text(encoding="utf-8"))["resultats"][0]["nip"] == "BF-0001"
    finally:
        fichier.unlink(missing_ok=True)
        provenance.unlink(missing_ok=True)

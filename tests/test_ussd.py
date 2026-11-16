"""USSD simulé : parcours *226#, écrans de 160 caractères au plus, PIN, médiateur en panne.
Le médiateur est remplacé par respx (même contrats que docs/API_USAGER.md)."""
import html
import importlib.util
import os
import re
import sys

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import RACINE

os.environ.update(ABONNES=str(RACINE / "ussd_sim/abonnes.yaml"), TEXTES=str(RACINE / "traduction-moore/phrases-ussd.csv"),
                  MEDIATEUR="http://mediateur:8000")
spec = importlib.util.spec_from_file_location("ussd_app", RACINE / "ussd_sim/app/main.py")
ussd = importlib.util.module_from_spec(spec)
sys.modules["ussd_app"] = ussd
spec.loader.exec_module(ussd)

M = "http://mediateur:8000"
EN_ATTENTE = [{"id_demande": "d-1", "service": "Le service des bourses", "code_service": "service-bourses",
               "code_attribut": "majeur", "demarche": "Demande de bourse", "finalite": "attribution de bourse",
               "attribut": "majeur", "valeur": "oui", "expire_le": 1794838200,
               "apercu": "Le service des bourses recevra : majeur = oui. Rien d'autre."}]


def ligne(n, evenement="remise", service="direction-concours", resultat="ok"):
    return {"n": n, "ts": "2026-11-16T11:54:30Z", "agent": "issa.sawadogo", "service": "…", "code_service": service,
            "demarche": "…", "finalite": "…", "base": "base-legale", "texte_base": "…", "attribut": "majeur",
            "evenement": evenement, "resultat": resultat, "motif": "", "empreinte": f"{n:08x}" + "a" * 56}


class Telephone:
    def __init__(self, numero="70000012"):
        self.client = TestClient(ussd.app, base_url="https://testserver")
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', self.client.get("/").text)[1]
        self.client.post("/allumer", data={"csrf": self.csrf, "numero": numero})

    def ecran(self) -> str:
        page = self.client.get("/").text
        return html.unescape(re.search(r'<div class="ecran"[^>]*>(.*?)</div>', page, re.S)[1])

    def taper(self, reponse: str) -> str:
        self.client.post("/", data={"csrf": self.csrf, "reponse": reponse})
        texte = self.ecran()
        assert len(texte) <= 160, f"écran trop long ({len(texte)}) : {texte}"
        return texte

    def connecter(self):
        assert "PIN" in self.taper("*226#")
        assert "1. Demandes en attente" in self.taper("1234")


@respx.mock
def test_apercu_puis_confirmation_avec_recu():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=EN_ATTENTE))
    confirmer = respx.post(f"{M}/demandes/d-1/confirmer").mock(
        return_value=httpx.Response(200, json={"id_demande": "d-1", "statut": "confirmee", "empreinte": "3f9a1c0b" + "0" * 56}))
    tel = Telephone()
    tel.connecter()
    apercu = tel.taper("1")
    assert apercu.startswith("Le service des bourses recevra : majeur = oui. Rien d'autre.")
    assert "1. Confirmer 2. Refuser" in apercu
    assert tel.taper("1") == "Confirmé. Reçu : 3f9a1c0b\n0. Menu"
    assert confirmer.calls[0].request.headers["X-Cle-Canal"] == "secret-de-test-canal"
    assert b'"sujet_ref":"BF-0012"' in confirmer.calls[0].request.content.replace(b" ", b"")


@respx.mock
def test_refus_par_l_usager():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=EN_ATTENTE))
    respx.post(f"{M}/demandes/d-1/refuser").mock(return_value=httpx.Response(200, json={"statut": "refuse"}))
    tel = Telephone()
    tel.connecter()
    tel.taper("1")
    assert tel.taper("2").startswith("Refusé. Rien n'a été transmis.")


@respx.mock
def test_historique_pagine_par_3_sans_la_valeur():
    lignes = [ligne(n) for n in range(7, 0, -1)] + [ligne(8, "reponse-registre")]   # étape interne : omise
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=lignes))
    tel = Telephone()
    tel.connecter()
    page1 = tel.taper("2")
    assert page1.splitlines()[0] == "16/11 11h54 Concours majeur transmis 00000007"
    assert len(page1.splitlines()) == 4 and page1.endswith("9.Suite 0.Retour")
    assert len(tel.taper("9").splitlines()) == 4
    assert tel.taper("9").splitlines() == ["16/11 11h54 Concours majeur transmis 00000001", "0. Retour"]
    assert "oui" not in page1


@respx.mock
def test_pire_ecran_d_historique_tient_en_160():
    lignes = [ligne(n, "refus-usager", "service-bourses") for n in range(10)]
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=lignes))
    tel = Telephone()
    tel.connecter()
    assert not tel.taper("2").endswith("…")


def test_pin_faux_trois_fois_bloque():
    tel = Telephone("70000001")
    tel.taper("*226#")
    assert "Essais restants : 2" in tel.taper("0000")
    assert "Essais restants : 1" in tel.taper("0000")
    assert "Trop d'essais" in tel.taper("0000")
    assert "Trop d'essais" in tel.taper("1234")          # même le bon PIN est refusé pendant le blocage


def test_numero_non_inscrit():
    tel = Telephone("70999999")
    assert "pas inscrit" in tel.taper("*226#")


@respx.mock
def test_mediateur_en_panne_ecran_clair():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(side_effect=httpx.ConnectError("panne"))
    tel = Telephone()
    tel.connecter()
    assert tel.taper("1").startswith("Service momentanément indisponible. Rien n'a été transmis.")


def test_moore_incomplet_non_propose():
    # La colonne mos de phrases-ussd.csv est vide tant que l'équipe n'a pas traduit : pas de menu Langue
    assert list(ussd.TEXTES) == ["fr"]
    tel = Telephone("70000003")
    tel.connecter()
    assert "3. Langue" not in tel.ecran()


@pytest.mark.parametrize("cle", ["apercu", "confirme", "pin_faux"])
def test_les_reperes_sont_presents(cle):
    assert "{" in ussd.TEXTES["fr"][cle]

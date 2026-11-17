"""Portail web usager : connexion (mêmes règles que l'USSD), trois écrans, secret du canal web, médiateur en panne.
Le médiateur est remplacé par respx (mêmes contrats que docs/API_USAGER.md)."""
import importlib.util
import os
import re
import sys

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import RACINE

os.environ.update(ABONNES=str(RACINE / "espace-usager/ussd/abonnes.yaml"), TEXTES=str(RACINE / "traduction-moore/phrases-portail.csv"),
                  MEDIATEUR="http://mediateur:8000")
spec = importlib.util.spec_from_file_location("portail_app", RACINE / "espace-usager/portail/app/main.py")
portail = importlib.util.module_from_spec(spec)
sys.modules["portail_app"] = portail
spec.loader.exec_module(portail)

M = "http://mediateur:8000"
EN_ATTENTE = [{"id_demande": "d-1", "service": "Le service des bourses", "code_service": "service-bourses",
               "demarche": "Bourse nationale", "finalite": "attribution de la bourse nationale",
               "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè", "parametres": {},
                              "valeur": "oui"}], "expire_le": 1794838200,
               "apercu": "Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre."}]
EMPREINTE = "3f9a1c0b" + "e" * 56


def ligne(n, evenement="confirmation", canal="web"):
    return {"n": n, "ts": "2026-11-17T09:15:00Z", "agent": "awa.ouedraogo", "service": "Le service des bourses",
            "code_service": "service-bourses", "demarche": "Bourse nationale",
            "finalite": "attribution de la bourse nationale", "finalites": {}, "base": "consentement",
            "texte_base": "", "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}],
            "evenement": evenement, "resultat": "ok", "motif": "", "canal": canal, "empreinte": EMPREINTE}


@pytest.fixture(autouse=True)
def remise_a_zero():
    portail.SESSIONS.clear()
    portail.ECHECS_PIN.clear()


class Navigateur:
    def __init__(self):
        self.client = TestClient(portail.app, base_url="https://testserver")
        self.csrf = self.jeton(self.client.get("/portail").text)

    @staticmethod
    def jeton(page: str) -> str:
        return re.search(r'name="csrf" value="([^"]+)"', page)[1]

    def connecter(self, numero="70000012", pin="1234") -> httpx.Response:
        r = self.client.post("/portail/connexion", data={"csrf": self.csrf, "numero": numero, "pin": pin})
        if "csrf" in r.text:
            self.csrf = self.jeton(r.text)           # nouveau jeton après connexion
        return r


def test_page_legere_sans_script_ni_ressource_externe():
    page = Navigateur().client.get("/portail")
    assert page.status_code == 200 and "Code PIN" in page.text
    assert "<script" not in page.text and "http://" not in page.text and "https://" not in page.text
    assert len(page.content) < 4000
    css = Navigateur().client.get("/portail/static/portail.css")
    assert css.status_code == 200 and "url(" not in css.text and "@import" not in css.text and len(css.content) < 4000


def test_textes_francais_complets():
    assert "fr" in portail.TEXTES
    assert set(portail.EVENEMENTS.values()) <= set(portail.T)


def test_blocage_apres_trois_pin_faux():
    nav = Navigateur()
    assert "Essais restants : 2" in nav.connecter(pin="0000").text
    assert "Essais restants : 1" in nav.connecter(pin="0000").text
    assert "bloqué 5 minutes" in nav.connecter(pin="0000").text
    # Même le bon PIN est refusé pendant le blocage
    r = nav.connecter(pin="1234")
    assert r.status_code == 429 and "bloqué" in r.text


def test_numero_inconnu_meme_message_que_pin_faux():
    r = Navigateur().connecter(numero="79999999")
    assert r.status_code == 401 and "Numéro ou code PIN incorrect." in r.text


def test_ecrans_proteges_sans_connexion():
    nav = Navigateur()
    for chemin in ("/portail/attente", "/portail/historique", "/portail/accords", "/portail/historique/1"):
        r = nav.client.get(chemin, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/portail"


def test_formulaire_sans_jeton_csrf_refuse():
    nav = Navigateur()
    r = nav.client.post("/portail/connexion", data={"csrf": "faux", "numero": "70000012", "pin": "1234"})
    assert r.status_code == 403


@respx.mock
def test_apercu_puis_confirmation_avec_recu_par_le_canal_web():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=EN_ATTENTE))
    confirmer = respx.post(f"{M}/demandes/d-1/confirmer").mock(
        return_value=httpx.Response(200, json={"id_demande": "d-1", "statut": "confirmee", "empreinte": EMPREINTE}))
    nav = Navigateur()
    accueil = nav.connecter()
    assert "1 en attente" in accueil.text
    page = nav.client.get("/portail/attente").text
    assert "Le service des bourses recevra : nationalité burkinabè = oui. Rien d&#39;autre." in page
    assert "À confirmer avant 14h10" in page
    r = nav.client.post("/portail/attente/d-1/confirmer", data={"csrf": nav.csrf})
    assert "3f9a 1c0b eeee eeee" in r.text
    requete = confirmer.calls[0].request
    assert requete.headers["X-Cle-Canal"] == "secret-de-test-canal-web"       # le secret du WEB, pas celui de l'USSD
    assert b'"sujet_ref":"BF-0012"' in requete.content.replace(b" ", b"")


@respx.mock
def test_refus_et_demande_deja_traitee():
    respx.post(f"{M}/demandes/d-1/refuser").mock(return_value=httpx.Response(200, json={"statut": "refuse"}))
    respx.post(f"{M}/demandes/d-2/confirmer").mock(return_value=httpx.Response(409, json={"detail": "…"}))
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=[]))
    nav = Navigateur()
    nav.connecter()
    assert "Rien n&#39;a été transmis." in nav.client.post("/portail/attente/d-1/refuser", data={"csrf": nav.csrf}).text
    r = nav.client.post("/portail/attente/d-2/confirmer", data={"csrf": nav.csrf})
    assert r.status_code == 409 and "déjà été traitée" in r.text


@respx.mock
def test_historique_et_detail_avec_finalite_base_canal_et_recu():
    lignes = [ligne(12), ligne(11, "reponse-registre", ""), ligne(10, "remise", "")]
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=lignes))
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=[]))
    nav = Navigateur()
    nav.connecter()
    liste = nav.client.get("/portail/historique").text
    assert "/portail/historique/12" in liste and "/portail/historique/10" in liste
    assert "/portail/historique/11" not in liste          # étape interne omise, comme à l'USSD
    detail = nav.client.get("/portail/historique/12").text
    for attendu in ("attribution de la bourse nationale", "Avec votre accord", "le portail web", "3f9a 1c0b eeee eeee"):
        assert attendu in detail
    assert "= oui" not in detail
    assert nav.client.get("/portail/historique/999").status_code == 404     # pas une ligne de son historique


@respx.mock
def test_retrait_en_deux_temps_avec_recu():
    accords = [{"id_demande": "d-1", "code_service": "service-bourses", "service": "Le service des bourses",
                "demarche": "Bourse nationale",
                "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}], "transmis": True}]
    respx.get(f"{M}/usagers/BF-0012/accords").mock(return_value=httpx.Response(200, json=accords))
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=[]))
    retirer = respx.post(f"{M}/demandes/d-1/retirer").mock(return_value=httpx.Response(
        200, json={"statut": "retiree_apres_remise", "transmis": True, "empreinte": EMPREINTE}))
    nav = Navigateur()
    nav.connecter()
    assert "déjà transmis" in nav.client.get("/portail/accords").text
    question = nav.client.post("/portail/accords/d-1/retirer", data={"csrf": nav.csrf}).text
    assert "Retirer votre accord à Le service des bourses pour : nationalité burkinabè ?" in question
    assert not retirer.called                              # rien n'est retiré avant la confirmation
    fait = nav.client.post("/portail/accords/d-1/retirer", data={"csrf": nav.csrf, "confirme": "oui"}).text
    assert "le service ne doit plus l&#39;utiliser" in fait and "3f9a 1c0b eeee eeee" in fait
    assert retirer.calls[0].request.headers["X-Cle-Canal"] == "secret-de-test-canal-web"


@respx.mock
def test_mediateur_injoignable_message_clair():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(side_effect=httpx.ConnectError("coupé"))
    nav = Navigateur()
    r = nav.connecter()
    assert r.status_code == 503 and "Rien n&#39;a été transmis" in r.text


def test_deconnexion():
    nav = Navigateur()
    with respx.mock:
        respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=[]))
        nav.connecter()
    nav.client.post("/portail/deconnexion", data={"csrf": nav.csrf})
    assert nav.client.get("/portail/attente", follow_redirects=False).status_code == 303

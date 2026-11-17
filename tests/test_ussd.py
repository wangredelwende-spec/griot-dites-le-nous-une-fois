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
               "demarche": "Bourse nationale", "finalite": "attribution de la bourse nationale",
               "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè", "parametres": {},
                              "valeur": "oui"}], "expire_le": 1794838200,
               "apercu": "Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre."}]
CONCOURS = [{"code": "age_entre", "libelle": "âge de 18 à 37 ans au 31/12/2026"},
            {"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"},
            {"code": "casier_judiciaire_vierge", "libelle": "casier judiciaire vierge"}]


def ligne(n, evenement="remise", service="direction-concours", resultat="ok"):
    return {"n": n, "ts": "2026-11-16T11:54:30Z", "agent": "issa.sawadogo", "service": "…", "code_service": service,
            "demarche": "…", "finalite": "…", "base": "base_legale", "texte_base": "…",
            "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}],
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
    assert apercu.startswith("Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre.")
    assert "1. Confirmer 2. Refuser" in apercu
    assert tel.taper("1") == "Confirmé. Reçu : 3f9a 1c0b 0000 0000\n0. Menu"
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
    assert page1.splitlines()[0] == "1. 16/11 11h54 Concours nation. transmis"
    assert len(page1.splitlines()) == 4 and page1.endswith("9.Suite 0.Retour")
    assert len(tel.taper("9").splitlines()) == 4
    assert tel.taper("9").splitlines() == ["1. 16/11 11h54 Concours nation. transmis", "0. Retour"]
    assert "oui" not in page1


@respx.mock
def test_detail_avec_finalite_base_et_recu_de_16_caracteres():
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=[ligne(7)]))
    tel = Telephone()
    tel.connecter()
    tel.taper("2")
    detail = tel.taper("1")
    assert detail.splitlines() == ["La direction des concours : nationalité burkinabè transmis", "Pour : …", "Base légale",
                                   "Reçu : 0000 0007 aaaa aaaa", "0. Retour"]
    assert tel.taper("0").startswith("1. 16/11")          # retour à la liste


@respx.mock
def test_pires_ecrans_tiennent_en_160_sans_couper_le_recu():
    longue = {"finalite": "vérification de l'âge minimal pour concourir " * 5, "base": "consentement"}
    lignes = [ligne(n, "refus-usager", "direction-concours") | longue for n in range(10)]
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=lignes))
    tel = Telephone()
    tel.connecter()
    assert not tel.taper("2").endswith("…")
    detail = tel.taper("3")
    assert len(detail) <= 160 and "Reçu : 0000 0002 aaaa aaaa" in detail and detail.endswith("0. Retour")


@respx.mock
def test_confirmation_recu_16_caracteres_en_4_groupes():
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=EN_ATTENTE))
    respx.post(f"{M}/demandes/d-1/confirmer").mock(return_value=httpx.Response(
        200, json={"id_demande": "d-1", "statut": "confirmee", "empreinte": "903547b31c2e9f04" + "0" * 48}))
    tel = Telephone()
    tel.connecter()
    tel.taper("1")
    assert tel.taper("1") == "Confirmé. Reçu : 9035 47b3 1c2e 9f04\n0. Menu"


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


@respx.mock
def test_concours_trois_attributs_historique_et_detail():
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=[
        ligne(n) | {"attributs": CONCOURS, "finalite": "vérification des conditions d'inscription au concours "
                    "direct des adjoints administratifs"} for n in range(9, 0, -1)]))
    tel = Telephone()
    tel.connecter()
    assert tel.taper("2").splitlines()[0] == "1. 16/11 11h54 Concours 3 infos transmis"
    detail = tel.taper("1")
    assert detail.splitlines()[0] == "La direction des concours : âge, nation., casier transmis"
    assert "Reçu : 0000 0009 aaaa aaaa" in detail and detail.endswith("0. Retour")


@respx.mock
def test_apercu_de_plusieurs_attributs_tient_en_160():
    """Un seul aperçu liste TOUT ; trop long en libellés complets : libellés courts, jamais coupé."""
    attente = [EN_ATTENTE[0] | {"attributs": [a | {"valeur": "oui", "parametres": {}} for a in CONCOURS]},
               EN_ATTENTE[0]]
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=attente))
    tel = Telephone()
    tel.connecter()
    apercu = tel.taper("1")
    assert apercu.startswith("(1/2) Le service des bourses recevra : âge = oui ; nation. = oui ; casier = oui. "
                             "Rien d'autre.")
    assert "…" not in apercu and "1. Confirmer 2. Refuser" in apercu


ACCORDS = [{"id_demande": "d-7", "code_service": "service-bourses", "service": "Le service des bourses",
            "demarche": "Bourse nationale", "transmis": False,
            "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}]},
           {"id_demande": "d-8", "code_service": "service-bourses", "service": "Le service des bourses",
            "demarche": "Bourse nationale", "transmis": True,
            "attributs": [{"code": "nationalite_burkinabe", "libelle": "nationalité burkinabè"}]}]


@respx.mock
def test_retirer_un_accord_pas_encore_transmis():
    respx.get(f"{M}/usagers/BF-0012/accords").mock(return_value=httpx.Response(200, json=ACCORDS))
    retirer = respx.post(f"{M}/demandes/d-7/retirer").mock(return_value=httpx.Response(200, json={
        "statut": "retiree", "transmis": False, "empreinte": "77aa" * 16}))
    tel = Telephone()
    tel.connecter()
    assert "3. Retirer un accord" in tel.ecran()
    liste = tel.taper("3")
    assert liste.splitlines()[:3] == ["Vos accords :", "1. Bourses nation. en cours", "2. Bourses nation. transmis"]
    assert tel.taper("1").startswith("Retirer votre accord ? Le service des bourses : nation.")
    assert tel.taper("1") == "Accord retiré. Rien n'a été transmis. Reçu : 77aa 77aa 77aa 77aa\n0. Menu"
    assert b'"sujet_ref":"BF-0012"' in retirer.calls[0].request.content.replace(b" ", b"")


@respx.mock
def test_retirer_un_accord_deja_transmis():
    respx.get(f"{M}/usagers/BF-0012/accords").mock(return_value=httpx.Response(200, json=ACCORDS))
    respx.post(f"{M}/demandes/d-8/retirer").mock(return_value=httpx.Response(200, json={
        "statut": "retiree_apres_remise", "transmis": True, "empreinte": "5b5b" * 16}))
    tel = Telephone()
    tel.connecter()
    tel.taper("3")
    tel.taper("2")
    assert tel.taper("1").startswith("Accord retiré. Déjà transmis : le service ne doit plus l'utiliser.")


@respx.mock
def test_alerte_montre_son_motif():
    alerte = ligne(4, "alerte", "service-bourses", "refuse") | {
        "motif": "agent bloqué : plus de 5 citoyens différents consultés en 60 minutes, consultation à contrôler"}
    respx.get(f"{M}/usagers/BF-0012/historique").mock(return_value=httpx.Response(200, json=[alerte]))
    tel = Telephone()
    tel.connecter()
    assert "ALERTE" in tel.taper("2")
    detail = tel.taper("1")
    assert "agent bloqué" in detail and "Reçu : 0000 0004" in detail


# --- Passeport : l'écran USSD complet (aperçu + choix) tient en 160 caractères, avec ou sans le repli casier ---

def apercu_passeport(dernier: dict) -> list[dict]:
    attributs = [{"code": "nationalite_burkinabe", "libelle": "burkinabè", "parametres": {}, "valeur": "oui"}, dernier]
    return [{"id_demande": "d-p", "service": "…", "code_service": "service-passeport", "demarche": "Passeport ordinaire",
             "finalite": "établissement d'un passeport ordinaire", "attributs": attributs, "expire_le": 1794838200,
             "apercu": "…"}]


@pytest.mark.parametrize("dernier, attendu", [
    ({"code": "interdiction_sortie_territoire", "libelle": "interdiction de sortie du territoire", "parametres": {},
      "valeur": "non"}, "interdiction de sortie du territoire = non"),
    ({"code": "casier_judiciaire_vierge", "libelle": "casier judiciaire vierge", "parametres": {}, "valeur": "oui"},
     "casier judiciaire vierge = oui"),                                       # repli du jour J
])
@respx.mock
def test_ecran_passeport_tient_en_160_caracteres(dernier, attendu):
    respx.get(f"{M}/usagers/BF-0012/en-attente").mock(return_value=httpx.Response(200, json=apercu_passeport(dernier)))
    tel = Telephone()
    tel.connecter()
    ecran = tel.taper("1")              # taper() vérifie déjà ≤ 160 caractères
    assert "(passeports) recevra : burkinabè = oui ; " + attendu + ". Rien d'autre." in ecran
    assert "1. Confirmer 2. Refuser" in ecran


# --- Mooré préparé sans être activé (« ~ » devant un texte = marqueur de test, pas du mooré) ---

def csv_complet(monkeypatch):
    """Comme si toutes les phrases mooré de phrases-ussd.csv étaient remplies."""
    monkeypatch.setattr(ussd, "TEXTES", {"fr": ussd.TEXTES["fr"],
                                         "mos": {cle: f"~{texte}" for cle, texte in ussd.TEXTES["fr"].items()}})


@respx.mock
def test_phrases_completes_mais_finalites_manquantes_pas_de_moore(monkeypatch):
    csv_complet(monkeypatch)
    respx.get(f"{M}/catalogue/langues").respond(json={"langues": []})
    tel = Telephone("70000003")
    tel.connecter()
    assert "4. Langue" not in tel.ecran()


@respx.mock
def test_mediateur_injoignable_francais_seul(monkeypatch):
    csv_complet(monkeypatch)
    respx.get(f"{M}/catalogue/langues").mock(side_effect=httpx.ConnectError("coupé"))
    tel = Telephone("70000003")
    tel.connecter()
    assert "4. Langue" not in tel.ecran()


@respx.mock
def test_phrases_et_finalites_completes_moore_propose(monkeypatch):
    csv_complet(monkeypatch)
    respx.get(f"{M}/catalogue/langues").respond(json={"langues": ["mos"]})
    historique = [ligne(1) | {"finalite": "attribution de la bourse nationale",
                              "finalites": {"mos": "~bourse"}}]
    respx.get(url__regex=rf"{M}/usagers/.*/historique").respond(json=historique)
    tel = Telephone("70000003")
    tel.connecter()
    assert "4. Langue" in tel.ecran()
    assert "2. ~Français" in tel.taper("4")
    assert tel.taper("2").startswith("~1. Demandes en attente")
    tel.taper("2")                                   # historique
    detail = tel.taper("1")
    assert "~Pour : ~bourse" in detail and "attribution" not in detail


def test_cle_attribut_age_entre_presente_en_francais():
    assert ussd.TEXTES["fr"]["attribut_age_entre"]

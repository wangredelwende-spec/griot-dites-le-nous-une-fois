"""Isolement entre citoyens : connecté comme BF-0012, on ne peut ni VOIR, ni CONFIRMER, ni REFUSER, ni RETIRER la
demande d'un autre citoyen (BF-0001), même en changeant l'identifiant dans l'adresse ou en ajoutant un champ
« sujet_ref » au formulaire. Sur le portail web ET sur l'USSD.

Ici, PAS de faux médiateur : le portail et l'USSD parlent au VRAI médiateur (en mémoire, sans Docker), avec ses
vraies vérifications. Seuls les registres sont simulés (respx). Deux barrières sont donc testées ensemble :
  1. l'écran prend l'identifiant dans SA session (après numéro + PIN), jamais dans l'adresse ni le formulaire ;
  2. le médiateur refuse (404) toute action sur une demande dont le pseudonyme n'est pas celui de l'usager.
"""
import sqlite3

import httpx
import pytest
import respx

from conftest import CANAL, CHEMIN_JOURNAL, URL_NATIONALITE, demande, mediateur
from test_mediateur import registre_qui_signe
from test_portail import Navigateur, portail
from test_ussd import Telephone, ussd

MOI, AUTRE = "BF-0012", "BF-0001"           # 70000012 est connecté ; 70000001 est l'autre citoyen
ADRESSE_MEDIATEUR = "http://mediateur:8000"
_AsyncClient = httpx.AsyncClient


@pytest.fixture
def vrai_mediateur(client, monkeypatch):
    """Les clients HTTP des écrans vers http://mediateur:8000 arrivent dans l'application du médiateur elle-même.
    Les appels du médiateur aux registres ne sont pas touchés (respx les simule)."""
    def fabrique(*args, **kwargs):
        if kwargs.get("base_url") == ADRESSE_MEDIATEUR:
            kwargs["transport"] = httpx.ASGITransport(app=mediateur.app)
        return _AsyncClient(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", fabrique)
    portail.SESSIONS.clear()
    portail.ECHECS_PIN.clear()
    ussd.SESSIONS.clear()
    ussd.ECHECS_PIN.clear()
    client.agent["nom"] = "awa.ouedraogo"          # Service des bourses : démarche « test-nationalite »
    yield client
    # Nettoyage (base de test partagée) : rien ne reste en attente pour ces deux citoyens, utilisés par d'autres tests
    monkeypatch.undo()
    for sujet in (MOI, AUTRE):
        for d in client.get(f"/usagers/{sujet}/en-attente", headers=CANAL).json():
            client.post(f"/demandes/{d['id_demande']}/refuser", json={"sujet_ref": sujet}, headers=CANAL)


def nouvelle_demande(client, sujet: str) -> str:
    d = demande(demarche="test-nationalite", sujet=sujet)
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    return d["id_demande"]


def statut(client, id_demande: str) -> str:
    return client.get(f"/demandes/{id_demande}").json()["statut"]


def lignes_web(id_demande: str) -> list:
    base = sqlite3.connect(CHEMIN_JOURNAL)
    return base.execute("SELECT evenement FROM journal WHERE id_demande = ? AND canal IN ('web', 'ussd')",
                        (id_demande,)).fetchall()


def preparer(client):
    """L'AUTRE citoyen a une demande en attente et un accord confirmé (donc retirable) ; MOI, une demande en attente."""
    en_attente_autre = nouvelle_demande(client, AUTRE)
    accord_autre = nouvelle_demande(client, AUTRE)
    r = client.post(f"/demandes/{accord_autre}/confirmer", json={"sujet_ref": AUTRE}, headers=CANAL)
    assert r.status_code == 200
    a_moi = nouvelle_demande(client, MOI)
    historique_autre = client.get(f"/usagers/{AUTRE}/historique", headers=CANAL).json()
    return en_attente_autre, accord_autre, a_moi, {l["n"] for l in historique_autre}


@respx.mock
def test_portail_isolement_entre_citoyens(vrai_mediateur):
    client = vrai_mediateur
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    en_attente_autre, accord_autre, a_moi, lignes_autre = preparer(client)
    nav = Navigateur()
    nav.connecter("70000012", "1234")
    pirate = {"csrf": nav.csrf, "sujet_ref": AUTRE, "numero": "70000001"}     # champs ajoutés au formulaire

    # VOIR : ses écrans ne montrent que SES demandes, même avec ?sujet_ref=… dans l'adresse
    attente = nav.client.get(f"/portail/attente?sujet_ref={AUTRE}").text
    assert a_moi in attente and en_attente_autre not in attente
    assert accord_autre not in nav.client.get(f"/portail/accords?sujet_ref={AUTRE}").text
    historique = nav.client.get(f"/portail/historique?sujet_ref={AUTRE}").text
    assert not any(f"/portail/historique/{n}\"" in historique for n in lignes_autre)
    for n in lignes_autre:                      # détail d'une ligne de l'autre, numéro tapé dans l'adresse
        assert nav.client.get(f"/portail/historique/{n}?sujet_ref={AUTRE}").status_code == 404

    # CONFIRMER / REFUSER la demande de l'autre (son identifiant de demande mis dans l'adresse)
    for action in ("confirmer", "refuser"):
        r = nav.client.post(f"/portail/attente/{en_attente_autre}/{action}", data=pirate)
        assert r.status_code == 409 and "Reçu" not in r.text
    assert statut(client, en_attente_autre) == "en_attente"

    # RETIRER l'accord de l'autre : ni la question, ni le retrait direct
    assert nav.client.post(f"/portail/accords/{accord_autre}/retirer", data=pirate).status_code == 409
    r = nav.client.post(f"/portail/accords/{accord_autre}/retirer", data=pirate | {"confirme": "oui"})
    assert r.status_code == 409 and "Reçu" not in r.text
    assert statut(client, accord_autre) in ("confirmee", "remise")

    # Aucune action « web » n'a été écrite au journal pour les demandes de l'autre
    assert lignes_web(en_attente_autre) == []
    assert [e for (e,) in lignes_web(accord_autre)] == ["confirmation"]        # seulement SA confirmation (ussd)

    # Témoin : sa propre demande, elle, se confirme normalement par le web
    r = nav.client.post(f"/portail/attente/{a_moi}/confirmer", data={"csrf": nav.csrf})
    assert r.status_code == 200 and "Reçu" in r.text
    assert lignes_web(a_moi) == [("confirmation",)]


@respx.mock
def test_ussd_isolement_entre_citoyens(vrai_mediateur):
    client = vrai_mediateur
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    en_attente_autre, accord_autre, a_moi, _ = preparer(client)
    tel = Telephone("70000012")
    tel.connecter()

    def taper(reponse: str) -> str:            # avec un champ « sujet_ref » ajouté au formulaire
        tel.client.post("/", data={"csrf": tel.csrf, "reponse": reponse, "sujet_ref": AUTRE})
        return tel.ecran()

    # VOIR : une seule demande en attente, la sienne ; « 9 » (suivante) ne mène nulle part
    apercu = taper("1")
    assert "recevra" in apercu and "(1/" not in apercu and "9." not in apercu
    # CONFIRMER : seule SA demande est confirmée
    assert "Reçu" in taper("1")
    assert statut(client, a_moi) in ("confirmee", "remise") and statut(client, en_attente_autre) == "en_attente"
    # RETIRER : l'écran liste exactement SES accords (selon le médiateur), jamais celui de l'autre
    # (la base de test est partagée : un test précédent a pu laisser à BF-0012 un autre accord, lui aussi à lui)
    les_miens = [a["id_demande"] for a in client.get(f"/usagers/{MOI}/accords", headers=CANAL).json()]
    assert accord_autre not in les_miens and les_miens[0] == a_moi
    taper("0")
    accords = taper("3")
    assert sum(l[:2] in ("1.", "2.", "3.") for l in accords.splitlines()) == min(len(les_miens), 3), accords
    taper("1")                                   # le plus récent : a_moi
    assert "Accord retiré" in taper("1")
    assert statut(client, accord_autre) in ("confirmee", "remise")
    assert statut(client, a_moi) in ("retiree", "retiree_apres_remise")

    # Changer de numéro sans le PIN de l'autre : retour à l'écran du PIN, jamais à son menu
    tel.client.post("/allumer", data={"csrf": tel.csrf, "numero": "70000001"})
    assert "PIN" in tel.taper("*226#")
    assert "Demandes en attente" not in tel.taper("1")
    assert lignes_web(en_attente_autre) == []


@respx.mock
def test_mediateur_refuse_toute_action_sur_la_demande_d_un_autre(vrai_mediateur):
    """La seconde barrière seule : même un écran compromis qui enverrait le mauvais identifiant n'obtient rien."""
    client = vrai_mediateur
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    en_attente_autre, accord_autre, _, _ = preparer(client)
    for action in ("confirmer", "refuser", "retirer"):
        cible = accord_autre if action == "retirer" else en_attente_autre
        r = client.post(f"/demandes/{cible}/{action}", json={"sujet_ref": MOI}, headers=CANAL)
        assert r.status_code == 404, (action, r.text)
    assert statut(client, en_attente_autre) == "en_attente"
    assert statut(client, accord_autre) in ("confirmee", "remise")

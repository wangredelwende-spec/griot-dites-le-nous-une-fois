"""Journal du cadre : noms d'attributs seulement (demandés / transmis / refusés), identifiant de corrélation,
et GET /journal/verification (OK, ou numéro de la première ligne modifiée)."""
import sqlite3
import threading

import respx

from conftest import CHEMIN_JOURNAL, URL_REGISTRE, demande, mediateur
from test_mediateur import journal_de, registre_conforme
from tracabilite.journal import Journal


@respx.mock
def test_les_trois_listes_d_attributs_sont_des_noms_jamais_des_valeurs(client):
    respx.get(url__regex=URL_REGISTRE).mock(side_effect=registre_conforme())
    d = demande()
    r = client.post("/demandes", json=d).json()
    assert r["statut"] == "remise"
    lignes = [l for l in journal_de() if l["id_demande"] == d["id_demande"]]   # corrélation : une démarche = un id
    assert [l["evenement"] for l in lignes] == ["demande", "reponse-registre", "remise"]
    remise = lignes[-1]
    assert remise["attributs_demandes"] and remise["attributs_transmis"] == remise["attributs_demandes"]
    assert remise["attributs_refuses"] == ""
    assert lignes[0]["attributs_transmis"] == ""          # rien n'est transmis avant la remise
    for ligne in lignes:                                   # des noms (« majeur »…), pas « true », « 18 » ou « oui »
        for champ in ("attributs_demandes", "attributs_transmis", "attributs_refuses"):
            assert not {"true", "false", "oui", "non"} & set(ligne[champ].split("+")), ligne


@respx.mock
def test_un_refus_est_range_dans_attributs_refuses(client):
    import httpx
    respx.get(url__regex=URL_REGISTRE).mock(side_effect=httpx.ConnectError("injoignable"))
    d = demande()
    r = client.post("/demandes", json=d).json()
    assert r["statut"] == "indisponible"
    derniere = [l for l in journal_de() if l["id_demande"] == d["id_demande"]][-1]
    assert derniere["attributs_refuses"] == derniere["attributs_demandes"] != ""
    assert derniere["attributs_transmis"] == ""


def test_verification_ok_puis_premiere_ligne_modifiee(tmp_path, monkeypatch, client):
    """Journal de test à part (celui des autres tests est partagé) : on le falsifie directement dans SQLite."""
    chemin = tmp_path / "mediateur.sqlite3"
    base = sqlite3.connect(chemin, isolation_level=None, check_same_thread=False)
    base.row_factory = sqlite3.Row
    journal = Journal(base, threading.RLock())
    for i in range(4):
        journal.ecrire(agent="a", evenement="demande", resultat="ok", motif=f"ligne {i}")
    monkeypatch.setattr(mediateur, "DONNEES", tmp_path)

    r = client.get("/journal/verification")          # sans jeton : ni identifiant ni valeur dans la réponse
    assert r.status_code == 200
    assert r.json() | {"message": ""} == {"statut": "OK", "integre": True, "lignes": 4,
                                          "premiere_ligne_modifiee": None, "message": ""}

    base.execute("DROP TRIGGER journal_sans_modification")
    base.execute("UPDATE journal SET agent = 'intrus' WHERE n = 3")
    r = client.get("/journal/verification").json()
    assert r["statut"] == "ALTERE" and not r["integre"] and r["premiere_ligne_modifiee"] == 3


@respx.mock
def test_chaque_ligne_a_un_statut_et_l_agent(client):
    respx.get(url__regex=URL_REGISTRE).mock(side_effect=registre_conforme())
    d = demande()
    client.post("/demandes", json=d)
    lignes = [l for l in journal_de() if l["id_demande"] == d["id_demande"]]
    assert [l["statut"] for l in lignes] == ["autorisée", "réussie", "réussie"]
    assert {l["agent"] for l in lignes} == {"issa.sawadogo"}
    from tracabilite.journal import statut_de
    assert statut_de("demande", "refuse") == "refusée" and statut_de("reponse-registre", "indisponible") == "indisponible"
    assert statut_de("alerte", "refuse") == "échouée" and statut_de("retrait", "ok") == "refusée"

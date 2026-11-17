"""Accord par démarche : donné à la confirmation, valable une durée, retirable ; avec un accord valide, réponse immédiate."""
import time

import respx
from conftest import CANAL, URL_NATIONALITE, demande, mediateur
from test_mediateur import journal_de, registre_conforme

SUJET = "BF-0030"


def demander(client, sujet=SUJET):
    client.agent["nom"] = "awa.ouedraogo"            # CEFORE
    d = demande(demarche="test-nationalite", sujet=sujet)
    return d, client.post("/demandes", json=d).json()


def confirmer(client, d, sujet=SUJET):
    client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": sujet}, headers=CANAL)
    return client.get(f"/demandes/{d['id_demande']}").json()


@respx.mock
def test_premiere_demande_attend_l_usager_puis_la_suivante_est_immediate(client):
    respx.get(url__regex=URL_NATIONALITE).mock(side_effect=registre_conforme())
    d1, r1 = demander(client)
    assert r1["statut"] == "en_attente"                      # pas d'accord encore : l'usager voit l'aperçu et confirme
    assert confirmer(client, d1)["statut"] == "remise"
    d2, r2 = demander(client)
    assert r2["statut"] == "remise" and all(v["valeur"] is True for v in r2["volets"])     # accord valable : immédiat
    evenements = [l["evenement"] for l in journal_de() if l["id_demande"] == d2["id_demande"]]
    assert evenements == ["demande", "reponse-registre", "accord-valide", "remise"]


@respx.mock
def test_accord_retire_la_demande_suivante_attend_a_nouveau(client):
    respx.get(url__regex=URL_NATIONALITE).mock(side_effect=registre_conforme())
    d1, _ = demander(client, "BF-0031")
    confirmer(client, d1, "BF-0031")
    liste = client.get("/usagers/BF-0031/accords", headers=CANAL).json()
    assert liste[0]["accord_valide"] is True
    r = client.post(f"/demandes/{d1['id_demande']}/retirer", json={"sujet_ref": "BF-0031"}, headers=CANAL).json()
    assert r["statut"] == "retiree_apres_remise"
    d2, r2 = demander(client, "BF-0031")
    assert r2["statut"] == "en_attente"                      # accord retiré : on redemande à l'usager


@respx.mock
def test_accord_expire_la_demande_suivante_attend_a_nouveau(client):
    respx.get(url__regex=URL_NATIONALITE).mock(side_effect=registre_conforme())
    d1, _ = demander(client, "BF-0032")
    confirmer(client, d1, "BF-0032")
    with mediateur.VERROU:
        mediateur.base.execute("UPDATE accords SET expire_le = ? WHERE sujet = ?",
                               (time.time() - 1, mediateur.pseudonyme("BF-0032")))
    assert demander(client, "BF-0032")[1]["statut"] == "en_attente"


@respx.mock
def test_accord_propre_a_une_personne_et_a_un_service(client):
    respx.get(url__regex=URL_NATIONALITE).mock(side_effect=registre_conforme())
    d1, _ = demander(client, "BF-0033")
    confirmer(client, d1, "BF-0033")
    assert demander(client, "BF-0034")[1]["statut"] == "en_attente"      # une autre personne n'est pas concernée

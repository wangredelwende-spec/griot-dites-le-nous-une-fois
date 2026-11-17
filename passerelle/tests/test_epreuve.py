"""Une situation de l'épreuve du jury = un test : citoyen inconnu (404), registre lent ou éteint (503, « en attente »),
réponse non conforme (rejetée), hors catalogue (403), nouvelle adresse par configuration, clé API par administration.
Dans chaque cas : la réponse est propre (jamais de plantage) ET la ligne est au journal."""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import CANAL, TMP, URL_REGISTRE, demande, mediateur
from test_mediateur import journal_de, registre_qui_signe


def lignes_de(d: dict) -> list[dict]:
    return [l for l in journal_de() if l["id_demande"] == d["id_demande"]]


@respx.mock
def test_citoyen_inconnu_404_et_journal(client):
    respx.post(URL_REGISTRE).mock(return_value=httpx.Response(404))
    d = demande(sujet="BF-9999")
    r = client.post("/demandes", json=d)
    assert r.status_code == 404 and r.json()["code"] == "CITOYEN_INCONNU"
    derniere = lignes_de(d)[-1]
    assert derniere["resultat"] == "refuse" and derniere["motif"] == "citoyen inconnu"
    # Rejeu : même réponse, sans rappeler le registre
    assert client.post("/demandes", json=d).status_code == 404 and respx.calls.call_count == 1


@pytest.mark.parametrize("panne", [httpx.ReadTimeout("trop lent"), httpx.ConnectError("éteint")],
                         ids=["registre-lent", "registre-eteint"])
@respx.mock
def test_registre_lent_ou_eteint_503_en_attente_et_un_reessai(client, panne):
    respx.post(URL_REGISTRE).mock(side_effect=panne)
    d = demande()
    r = client.post("/demandes", json=d)
    assert r.status_code == 503
    assert r.json()["code"] == "REGISTRE_INDISPONIBLE" and r.json()["etat_demarche"] == "en_attente"
    assert "rien n'a été deviné" in r.json()["motif"]
    assert respx.calls.call_count == 2                      # un appel + UN réessai
    assert lignes_de(d)[-1]["resultat"] == "indisponible"
    assert client.get(f"/demandes/{d['id_demande']}").status_code == 503     # le suivi dit la même chose


@pytest.mark.parametrize("contenu", [{"x": 1}, {"jeton": 12}, "pas du json"], ids=["autre-forme", "jeton-numerique", "texte"])
@respx.mock
def test_reponse_non_conforme_rejetee_et_au_journal(client, contenu):
    respx.post(URL_REGISTRE).mock(return_value=httpx.Response(200, json=contenu) if isinstance(contenu, dict)
                                  else httpx.Response(200, text=contenu))
    d = demande()
    r = client.post("/demandes", json=d)
    assert r.json()["statut"] == "refuse" and "corrompue" in r.json()["motif"]
    assert [l["evenement"] for l in lignes_de(d)][-1] == "alerte"


@respx.mock
def test_hors_catalogue_403_et_journal(client):
    cas = {"démarche inconnue": {"demarche": "inventee"},
           "attribut hors catalogue": {"attributs": ["casier_vierge"]},
           "finalité non prévue": {"finalite": "curiosité"}}
    for nom, modif in cas.items():
        d = demande() | modif
        r = client.post("/demandes", json=d)
        assert r.status_code == 403 and r.json()["code"] == "HORS_CATALOGUE", nom
        assert lignes_de(d)[-1]["resultat"] == "refuse", nom
    assert respx.calls.call_count == 0                       # aucun registre n'a été interrogé


@respx.mock
def test_nouvelle_adresse_de_registre_par_configuration(client, monkeypatch):
    monkeypatch.setitem(mediateur.CAT["registres"]["etat-civil"], "url", "http://autre-etat-civil:9000")
    respx.post("http://autre-etat-civil:9000/attributs").mock(side_effect=registre_qui_signe())
    assert client.post("/demandes", json=demande()).json()["statut"] == "remise"


@respx.mock
def test_cle_api_du_registre_envoyee_si_configuree(client, monkeypatch):
    (TMP / "secrets/cle_registre_test").write_text("cle-du-registre\n")
    monkeypatch.setitem(mediateur.CAT["registres"]["etat-civil"], "en_tete_cle", "X-Test-Cle")
    monkeypatch.setitem(mediateur.CAT["registres"]["etat-civil"], "cle_secret", "cle_registre_test")
    appel = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.post("/demandes", json=demande())
    assert appel.calls[0].request.headers["X-Test-Cle"] == "cle-du-registre"


@respx.mock
def test_erreur_imprevue_ne_plante_pas(client, monkeypatch):
    async def casse(*a, **k):
        raise RuntimeError("bug imaginaire")
    monkeypatch.setattr(mediateur.registres, "appeler", casse)
    d = demande()
    r = client.post("/demandes", json=d)
    assert r.status_code == 503 and "rien n'a été deviné" in r.json()["motif"]
    assert lignes_de(d)[-1]["evenement"] == "alerte" and "RuntimeError" in lignes_de(d)[-1]["motif"]


@respx.mock
def test_cle_api_par_administration():
    """Sans jeton Keycloak : la clé API identifie l'administration (cefore), jamais le corps de la demande."""
    mediateur.app.dependency_overrides.clear()
    with TestClient(mediateur.app) as c:
        respx.post("http://registre-nationalite:8000/attributs").mock(side_effect=registre_qui_signe())
        d = demande(demarche="test-nationalite")
        assert c.post("/demandes", json=d, headers={"X-Cle-Api": "cle-demo-cefore"}).status_code == 200
        ligne = lignes_de(d)[0]
        assert ligne["agent"] == "api-cefore" and ligne["demandeur"] == "cefore"
        # On referme la demande en attente (sinon elle apparaîtrait dans les aperçus des autres tests)
        c.post(f"/demandes/{d['id_demande']}/refuser", json={"sujet_ref": "BF-0001"}, headers=CANAL)
        # La clé d'une AUTRE administration ne donne pas accès à cette démarche
        d2 = demande(demarche="test-nationalite")
        r = c.post("/demandes", json=d2, headers={"X-Cle-Api": "cle-demo-concours"})
        assert r.status_code == 403
        assert c.post("/demandes", json=demande(), headers={"X-Cle-Api": "mauvaise"}).status_code == 401

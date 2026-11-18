"""Une situation de l'épreuve du jury = un test : citoyen inconnu (404), registre lent ou éteint (503, « en attente »),
réponse non conforme (rejetée), hors catalogue (403), nouvelle adresse par configuration, clé API par administration.
Dans chaque cas : la réponse est propre (jamais de plantage) ET la ligne est au journal."""
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from conftest import (CANAL, TMP, URL_REGISTRE, brancher_les_registres_reels, demande, mediateur,
                      registre_conforme)
from test_mediateur import journal_de


def lignes_de(d: dict) -> list[dict]:
    return [l for l in journal_de() if l["id_demande"] == d["id_demande"]]


@respx.mock
def test_citoyen_inconnu_404_et_journal(client):
    respx.get(url__regex=URL_REGISTRE).mock(return_value=httpx.Response(404))
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
    respx.get(url__regex=URL_REGISTRE).mock(side_effect=panne)
    d = demande()
    r = client.post("/demandes", json=d)
    assert r.status_code == 503
    assert r.json()["code"] == "REGISTRE_INDISPONIBLE" and r.json()["etat_demarche"] == "en_attente"
    assert "rien n'a été deviné" in r.json()["motif"]
    assert respx.calls.call_count == 2                      # un appel + UN réessai
    assert lignes_de(d)[-1]["resultat"] == "indisponible"
    assert client.get(f"/demandes/{d['id_demande']}").status_code == 503     # le suivi dit la même chose


@pytest.mark.parametrize("contenu", [{"x": 1}, {"id": 5}, "pas du json"], ids=["autre-forme", "mauvais-type", "texte"])
@respx.mock
def test_reponse_non_conforme_rejetee_et_au_journal(client, contenu):
    respx.get(url__regex=URL_REGISTRE).mock(return_value=httpx.Response(200, json=contenu) if isinstance(contenu, dict)
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
    route = respx.get("http://autre-etat-civil:9000/etat-civil/BF-0001").mock(side_effect=registre_conforme())
    assert client.post("/demandes", json=demande()).json()["statut"] == "remise" and route.called


@respx.mock
def test_registre_d_une_autre_equipe_branche_par_configuration_seulement(client, monkeypatch):
    """L'épreuve : le registre d'une AUTRE équipe (autre adresse, autre route, autres noms de champs) est branché en
    changeant la configuration (annuaire, contrat, correspondance) : aucun code n'est touché."""
    autre_contrat = {"openapi": "3.1.0", "paths": {"/api/v2/personnes/{id}": {"get": {"responses": {"200": {
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Personne"}}}}}}}},
        "components": {"schemas": {"Personne": {
            "type": "object", "additionalProperties": False, "required": ["ref", "naissance", "deces"],
            "properties": {"ref": {"type": "string"}, "naissance": {"type": "string"},
                           "deces": {"type": ["string", "null"]}}}}}}
    monkeypatch.setattr(mediateur, "CONTRAT_CHARGE", autre_contrat)
    monkeypatch.setitem(mediateur.CAT["registres"], "etat-civil", {
        "url": "http://registre-autre-equipe:7000", "chemin": "/api/v2/personnes/{id}", "nom": "registre d'une autre équipe"})
    monkeypatch.setattr(mediateur, "CORRESPONDANCE", {"registres": {"etat-civil": {"date_naissance": "naissance",
                                                                                    "date_deces": "deces"}}})
    route = respx.get("http://registre-autre-equipe:7000/api/v2/personnes/BF-0001").mock(
        return_value=httpx.Response(200, json={"ref": "BF-0001", "naissance": "2001-03-14", "deces": None}))
    r = client.post("/demandes", json=demande()).json()
    assert route.called and r["statut"] == "remise" and r["volets"][0]["valeur"] is True
    # Et sa réponse est jugée sur SON contrat : une réponse qui ne le respecte pas est rejetée
    route.mock(return_value=httpx.Response(200, json={"ref": "BF-0001", "date_de_naissance": "2001-03-14"}))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and "non conforme au contrat" in r["motif"]


@respx.mock
def test_cle_api_du_registre_envoyee_si_configuree(client, monkeypatch):
    (TMP / "secrets/cle_registre_test").write_text("cle-du-registre\n")
    monkeypatch.setitem(mediateur.CAT["registres"]["etat-civil"], "en_tete_cle", "X-Test-Cle")
    monkeypatch.setitem(mediateur.CAT["registres"]["etat-civil"], "cle_secret", "cle_registre_test")
    appel = respx.get(url__regex=URL_REGISTRE).mock(side_effect=registre_conforme())
    client.post("/demandes", json=demande())
    assert appel.calls[0].request.headers["X-Test-Cle"] == "cle-du-registre"


@respx.mock
def test_erreur_imprevue_ne_plante_pas(client, monkeypatch):
    async def casse(*a, **k):
        raise RuntimeError("bug imaginaire")
    monkeypatch.setattr(mediateur.registres, "lire_fiche", casse)
    d = demande()
    r = client.post("/demandes", json=d)
    assert r.status_code == 503 and "rien n'a été deviné" in r.json()["motif"]
    assert lignes_de(d)[-1]["evenement"] == "alerte" and "RuntimeError" in lignes_de(d)[-1]["motif"]


# --- Les VRAIS registres simulés (selon le contrat), branchés en mémoire : de bout en bout ---

@respx.mock
def test_concours_de_bout_en_bout_par_cle_api_avec_les_vrais_registres():
    """La démarche concours, appelée par la clé API de la direction des concours (aucun jeton Keycloak), traverse la
    passerelle, les trois registres simulés réels, la minimisation et le journal : « oui, oui, oui » pour BF-0001."""
    brancher_les_registres_reels()
    mediateur.app.dependency_overrides.clear()
    cle = {"X-Cle-Api": "cle-demo-concours"}
    with TestClient(mediateur.app) as c:
        d = demande("concours-direct", sujet="BF-0001")
        r = c.post("/demandes", json=d, headers=cle)
        assert r.status_code == 200 and r.json()["statut"] == "remise"
        assert {v["attribut"]: v["valeur"] for v in r.json()["volets"]} == {
            "majeur": True, "nationalite_bf": True, "casier_vierge": True}
        ligne = [l for l in lignes_de(d) if l["evenement"] == "remise"][0]
        assert ligne["agent"] == "api-direction-concours"
        assert ligne["attributs_transmis"] == "majeur+nationalite_bf+casier_vierge"
        # Cas piégés du jeu de données, par la même voie : mineure, non burkinabè, casier chargé
        attendus = {"BF-0003": {"majeur": False}, "BF-0007": {"nationalite_bf": False}, "BF-0004": {"casier_vierge": False}}
        for sujet, difference in attendus.items():
            reponse = c.post("/demandes", json=demande("concours-direct", sujet=sujet), headers=cle).json()
            volets = {v["attribut"]: v.get("valeur") for v in reponse["volets"]}
            assert {k: volets[k] for k in difference} == difference, sujet
        decedee = c.post("/demandes", json=demande("concours-direct", sujet="BF-0009"), headers=cle).json()
        majeur = next(v for v in decedee["volets"] if v["attribut"] == "majeur")
        assert majeur["statut"] == "refuse" and "valeur" not in majeur and "décéd" not in json.dumps(decedee, ensure_ascii=False)
        assert c.post("/demandes", json=demande("concours-direct", sujet="BF-4242"), headers=cle).status_code == 404


@respx.mock
def test_pannes_des_vrais_registres_eteint_non_conforme_puis_retour_normal(client):
    reels = brancher_les_registres_reels()
    reels["etat-civil"].PANNE_DE_TEST = "eteint"
    r = client.post("/demandes", json=demande())
    assert r.status_code == 503 and r.json()["code"] == "REGISTRE_INDISPONIBLE"
    reels["etat-civil"].PANNE_DE_TEST = "non_conforme"
    r = client.post("/demandes", json=demande())
    assert r.json()["statut"] == "refuse" and "non conforme au contrat" in r.json()["motif"]
    reels["etat-civil"].PANNE_DE_TEST = "normal"
    assert client.post("/demandes", json=demande()).json()["statut"] == "remise"


@respx.mock
def test_cle_api_par_administration():
    """Sans jeton Keycloak : la clé API identifie l'administration (tribunal, ONI), jamais le corps de la demande."""
    brancher_les_registres_reels()
    mediateur.app.dependency_overrides.clear()
    with TestClient(mediateur.app) as c:
        d = demande(demarche="certificat-nationalite", sujet="BF-0001")
        r = c.post("/demandes", json=d, headers={"X-Cle-Api": "cle-demo-tribunal"})
        assert r.status_code == 200 and r.json()["statut"] == "en_attente"      # consentement : l'usager voit l'aperçu
        ligne = lignes_de(d)[0]
        assert ligne["agent"] == "api-tribunal" and ligne["demandeur"] == "tribunal"
        c.post(f"/demandes/{d['id_demande']}/refuser", json={"sujet_ref": "BF-0001"}, headers=CANAL)   # referme l'attente
        # ONI : mission légale, remise immédiate de l'identité, de la naissance et filiation, de la nationalité
        d = demande(demarche="carte-identite-oni", sujet="BF-0001")
        r = c.post("/demandes", json=d, headers={"X-Cle-Api": "cle-demo-oni"})
        volets = {v["attribut"]: v.get("valeur") for v in r.json()["volets"]}
        assert r.status_code == 200 and r.json()["statut"] == "remise" and lignes_de(d)[0]["agent"] == "api-oni"
        assert volets["nationalite_bf"] is True and volets["identite"] == {"nom": "KABORE", "prenoms": "Aminata"}
        assert set(volets["naissance_filiation"]) == {"date_naissance", "lieu_naissance", "pere", "mere"}
        # La clé d'une AUTRE administration ne donne pas accès à cette démarche
        r = c.post("/demandes", json=demande(demarche="carte-identite-oni"), headers={"X-Cle-Api": "cle-demo-concours"})
        assert r.status_code == 403
        assert c.post("/demandes", json=demande(), headers={"X-Cle-Api": "mauvaise"}).status_code == 401


def test_essai_a_blanc_registre_d_une_autre_equipe():
    """docs/brancher-un-registre.md : le registre d'une autre équipe (autre adresse, autre route, autres noms de champs,
    SON contrat) est branché en modifiant seulement annuaire.yaml et correspondance.yaml (sur une COPIE du catalogue),
    sans redémarrer la passerelle. Le script est lancé tel quel, dans un processus séparé."""
    import subprocess
    import sys
    from conftest import RACINE
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("GRIOT_CATALOGUE",)}
    r = subprocess.run([sys.executable, str(RACINE / "scripts/essai_a_blanc_autre_equipe.py"), "--auto", "--port", "0"],
                       capture_output=True, text=True, encoding="utf-8", env=env | {"PYTHONIOENCODING": "utf-8"},
                       timeout=120, cwd=RACINE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "8/8 vérifications" in r.stdout


@respx.mock
def test_reponse_au_mauvais_type_ne_laisse_pas_sa_valeur_au_journal(client):
    """Protection des données : quand un registre renvoie une valeur au mauvais type, le motif écrit au journal (en ajout
    seul) dit le CHAMP et le TYPE d'erreur, jamais la valeur reçue (jsonschema la recopie dans son message)."""
    fiche = {"id": "BF-0001", "nom": "KABORE", "prenoms": "Aminata", "date_naissance": 19980702,
             "lieu_naissance": "Ouagadougou", "pere": "Issaka KABORE", "mere": "Salimata KABORE", "date_deces": None,
             "nationalite": 4242, "nombre_condamnations": "2 (vol, 2019)"}
    respx.get(url__regex=URL_REGISTRE).mock(return_value=httpx.Response(200, json=fiche))
    d = demande()
    r = client.post("/demandes", json=d)
    tout = json.dumps(lignes_de(d), ensure_ascii=False) + json.dumps(r.json(), ensure_ascii=False)
    assert "non conforme au contrat" in tout and ": type" in tout          # le champ et le type d'erreur
    for valeur in ("19980702", "4242", "2 (vol, 2019)", "vol, 2019"):
        assert valeur not in tout, valeur

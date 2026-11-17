"""Registres simulés SELON LE CONTRAT : chaque registre répond comme le contrat l'écrit (fiche, 404), rien de plus, et les
pannes se pilotent par variable d'environnement. Les réponses sont jugées par le MÊME validateur que la passerelle."""
import os

import pytest
from conftest import ANNUAIRE_DE_TEST, CITOYENS_DE_TEST, CONTRAT_DE_TEST, brancher_les_registres_reels
from fastapi.testclient import TestClient

import respx
from app import contrat


def client(registre: str):
    return TestClient(brancher_les_registres_reels()[registre].app)


@pytest.fixture(autouse=True)
def pannes_remises_a_zero():
    with respx.mock:
        reels = brancher_les_registres_reels()
    yield
    for registre in ANNUAIRE_DE_TEST["registres"]:
        reels[registre].PANNE_DE_TEST = "normal"


@pytest.mark.parametrize("registre", list(ANNUAIRE_DE_TEST["registres"]))
def test_chaque_citoyen_est_conforme_au_contrat_dans_chaque_registre(registre):
    chemin = ANNUAIRE_DE_TEST["registres"][registre]["chemin"]
    c = client(registre)
    for sujet in CITOYENS_DE_TEST:
        r = c.get(chemin.replace("{id}", sujet))
        assert r.status_code == 200, (registre, sujet)
        assert contrat.erreurs_de_conformite(CONTRAT_DE_TEST, chemin, r.json()) == [], (registre, sujet, r.json())


@pytest.mark.parametrize("registre", list(ANNUAIRE_DE_TEST["registres"]))
def test_citoyen_inconnu_404(registre):
    chemin = ANNUAIRE_DE_TEST["registres"][registre]["chemin"]
    r = client(registre).get(chemin.replace("{id}", "BF-4242"))
    assert r.status_code == 404 and r.json() == {"detail": "citoyen inconnu"}


def test_un_registre_n_expose_que_ses_champs():
    """L'état civil ne dit rien de la nationalité ni du casier, et inversement."""
    chemin = ANNUAIRE_DE_TEST["registres"]["casier"]["chemin"].replace("{id}", "BF-0004")
    assert client("casier").get(chemin).json() == {"id": "BF-0004", "nombre_condamnations": 2}
    chemin = ANNUAIRE_DE_TEST["registres"]["nationalite"]["chemin"].replace("{id}", "BF-0007")
    assert client("nationalite").get(chemin).json() == {"id": "BF-0007", "nationalite": "malienne"}


def test_pannes_par_variable_d_environnement(monkeypatch):
    registre = brancher_les_registres_reels()["etat-civil"]
    chemin = ANNUAIRE_DE_TEST["registres"]["etat-civil"]["chemin"].replace("{id}", "BF-0001")
    c = TestClient(registre.app)
    registre.mode_de_panne = lambda: os.environ.get("PANNE", "normal")      # le vrai comportement : lire la variable d'environnement
    monkeypatch.setenv("PANNE", "eteint")
    assert c.get(chemin).status_code == 503
    monkeypatch.setenv("PANNE", "non_conforme")
    corps = c.get(chemin).json()
    assert contrat.erreurs_de_conformite(CONTRAT_DE_TEST, ANNUAIRE_DE_TEST["registres"]["etat-civil"]["chemin"], corps)
    monkeypatch.setenv("PANNE", "normal")
    assert c.get(chemin).status_code == 200


def test_validateur_rejette_ce_qui_n_est_pas_dans_le_contrat():
    chemin = ANNUAIRE_DE_TEST["registres"]["nationalite"]["chemin"]
    assert contrat.erreurs_de_conformite(CONTRAT_DE_TEST, chemin, {"id": "BF-0001", "nationalite": "burkinabe"}) == []
    for faux in ({"id": "BF-0001"}, {"id": "BF-0001", "nationalite": 3}, {"id": "BF-0001", "nationalite": "x", "age": 5}, [], None):
        assert contrat.erreurs_de_conformite(CONTRAT_DE_TEST, chemin, faux), faux
    assert contrat.erreurs_de_conformite(CONTRAT_DE_TEST, "/route-inconnue/{id}", {})       # route absente du contrat

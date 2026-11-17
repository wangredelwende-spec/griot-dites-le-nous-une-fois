"""Mooré préparé sans être activé : une langue n'est proposée que si TOUTES les phrases ET les finalités des
démarches actives sont traduites. Les textes « [mos] … » ci-dessous sont des marqueurs de test, pas du mooré."""
import copy

import pytest
from conftest import CANAL, RACINE

from app import main as mediateur
from consentement import catalogue


def catalogue_avec(monkeypatch, finalites: dict):
    """Catalogue en vigueur, avec finalite_mos ajoutée aux démarches données ({code: texte})."""
    demarches = copy.deepcopy(mediateur.CAT["demarches"])
    for code, texte in finalites.items():
        demarches[code]["finalite_mos"] = texte
    monkeypatch.setattr(mediateur, "CAT", {**mediateur.CAT, "demarches": demarches})


def test_catalogue_du_depot_sans_mooré(client):
    assert client.get("/catalogue/langues", headers=CANAL).json() == {"langues": []}


def test_une_finalite_manquante_et_le_moore_n_est_pas_complet(client, monkeypatch):
    codes = list(mediateur.CAT["demarches"])
    catalogue_avec(monkeypatch, {code: f"[mos] {code}" for code in codes[:-1]})
    assert client.get("/catalogue/langues", headers=CANAL).json() == {"langues": []}


def test_toutes_les_finalites_traduites(client, monkeypatch):
    catalogue_avec(monkeypatch, {code: f"[mos] {code}" for code in mediateur.CAT["demarches"]})
    assert client.get("/catalogue/langues", headers=CANAL).json() == {"langues": ["mos"]}


def test_route_reservee_au_canal_usager(client):
    assert client.get("/catalogue/langues").status_code == 401


def test_finalite_traduite_seulement_si_c_est_la_meme_finalite():
    d = {"finalite": "attribution de la bourse nationale", "finalite_mos": "[mos] entreprise"}
    assert mediateur.finalites_traduites(d, "attribution de la bourse nationale") == {"mos": "[mos] entreprise"}
    # Ligne écrite sous une ANCIENNE finalité : on ne lui colle pas la traduction de la nouvelle
    assert mediateur.finalites_traduites(d, "ancienne finalité") == {}


@pytest.mark.parametrize("valeur", ["", "   ", 12, None])
def test_finalite_mos_vide_ou_pas_un_texte_refusee(monkeypatch, tmp_path, valeur):
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    (dossier / "attributs.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/attributs.yaml").read_bytes())
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    ancre = "    finalite: immatriculation d'une entreprise individuelle au CEFORE\n"
    assert ancre in texte
    brut = texte.replace(ancre, ancre + f"    finalite_mos: {'null' if valeur is None else repr(valeur)}\n")
    with pytest.raises(catalogue.CatalogueInvalide, match="« finalite_mos » doit être un texte non vide"):
        catalogue.charger(brut.encode("utf-8"))


def test_finalite_mos_remplie_acceptee(monkeypatch, tmp_path):
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    (dossier / "attributs.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/attributs.yaml").read_bytes())
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    ancre = "    finalite: immatriculation d'une entreprise individuelle au CEFORE\n"
    brut = texte.replace(ancre, ancre + "    finalite_mos: \"[mos] entreprise\"\n")
    assert catalogue.charger(brut.encode("utf-8"))["demarches"]["entreprise-individuelle-cefore"]["finalite_mos"] == "[mos] entreprise"

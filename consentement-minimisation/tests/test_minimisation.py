"""Minimisation dans la passerelle : la fiche brute entre, seul ce qui est permis sort. Correspondance de TEST
(les vrais noms de champs viendront du contrat du jury : catalogue/correspondance.yaml)."""
from datetime import date

import pytest
import yaml
from conftest import RACINE

from regles_attributs import Refus
from regles_attributs.minimisation import minimiser

CORRESPONDANCE = {"registres": {
    "etat-civil": {"nom": "family_name", "prenoms": "given_names", "date_naissance": "birth", "lieu_naissance": "place",
                   "pere": "father", "mere": "mother", "date_deces": "death"},
    "nationalite": {"nationalite": "nat"}, "casier": {"nombre_condamnations": "convictions"}}}
FICHE = {"family_name": "KABORE", "given_names": "Aminata", "birth": "2001-03-14", "place": "Ouagadougou",
         "father": "Issaka KABORE", "mother": "Salimata KABORE", "death": ""}
AUJOURDHUI = date.today().isoformat()
MAJEUR = {"regle": "age_entre", "champ": "date_naissance"}
NAISSANCE = {"regle": "champs", "champs": ["date_naissance", "lieu_naissance", "pere", "mere"]}


def test_majeur_calcule_dans_la_passerelle_sans_date_en_sortie():
    sortie = minimiser(MAJEUR, "etat-civil", FICHE, CORRESPONDANCE, {"min": 18, "date_reference": AUJOURDHUI})
    assert sortie is True                                   # un booléen : ni date, ni âge
    mineur = FICHE | {"birth": f"{date.today().year - 10}-01-01"}
    assert minimiser(MAJEUR, "etat-civil", mineur, CORRESPONDANCE, {"min": 18, "date_reference": AUJOURDHUI}) is False


def test_tranche_d_age():
    p = {"min": 18, "max": 37, "date_reference": "2026-12-31"}
    assert minimiser(MAJEUR, "etat-civil", FICHE, CORRESPONDANCE, p) is True
    assert minimiser(MAJEUR, "etat-civil", FICHE | {"birth": "1980-01-01"}, CORRESPONDANCE, p) is False


def test_nationalite_et_casier():
    nat = {"regle": "egal", "champ": "nationalite", "valeur": "burkinabe"}
    assert minimiser(nat, "nationalite", {"nat": "Burkinabè"}, CORRESPONDANCE) is True
    assert minimiser(nat, "nationalite", {"nat": "ivoirienne"}, CORRESPONDANCE) is False
    casier = {"regle": "nombre_nul", "champ": "nombre_condamnations"}
    assert minimiser(casier, "casier", {"convictions": "0"}, CORRESPONDANCE) is True
    assert minimiser(casier, "casier", {"convictions": "2"}, CORRESPONDANCE) is False


def test_identite_seulement_nom_et_prenoms():
    sortie = minimiser({"regle": "champs", "champs": ["nom", "prenoms"]}, "etat-civil", FICHE, CORRESPONDANCE)
    assert sortie == {"nom": "KABORE", "prenoms": "Aminata"}      # ni date, ni parents


def test_naissance_et_filiation():
    assert minimiser(NAISSANCE, "etat-civil", FICHE, CORRESPONDANCE) == {
        "date_naissance": "2001-03-14", "lieu_naissance": "Ouagadougou", "pere": "Issaka KABORE", "mere": "Salimata KABORE"}


@pytest.mark.parametrize("fiche, motif", [
    (FICHE | {"birth": "vers 1990"}, "incomplète"),
    (FICHE | {"birth": "2001-03"}, "incomplète"),
    ({k: v for k, v in FICHE.items() if k != "father"}, "absent ou vide"),
    (FICHE | {"mother": " "}, "absent ou vide"),
])
def test_donnee_incomplete_refusee(fiche, motif):
    with pytest.raises(Refus, match=motif):
        minimiser(NAISSANCE, "etat-civil", fiche, CORRESPONDANCE)


def test_correspondance_du_depot_vide_refuse_sans_deviner():
    """Le fichier du dépôt n'est pas encore rempli (contrat du jury attendu) : tout est refusé, rien n'est deviné."""
    vide = yaml.safe_load((RACINE / "consentement-minimisation/catalogue/correspondance.yaml").read_text(encoding="utf-8"))
    with pytest.raises(Refus, match="correspondance non renseignée"):
        minimiser(MAJEUR, "etat-civil", FICHE, vide, {"min": 18, "date_reference": AUJOURDHUI})

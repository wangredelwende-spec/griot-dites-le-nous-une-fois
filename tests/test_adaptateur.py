"""Registre simulé : calcul de l'attribut minimal et cas à refuser (données fictives)."""
import importlib.util
from datetime import date

import pytest

from conftest import RACINE, TMP

spec = importlib.util.spec_from_file_location("adaptateur", RACINE / "registres_sim/app/adaptateur.py")
adaptateur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adaptateur)

# Même adaptateur que dans Docker, mais lisant le CSV du dépôt
yaml_test = TMP / "etat-civil.yaml"
yaml_test.write_text((RACINE / "adaptateurs/etat-civil.yaml").read_text(encoding="utf-8").replace(
    "/donnees/etat_civil.csv", str(RACINE / "registres_sim/donnees_fictives/etat_civil.csv").replace("\\", "/")),
    encoding="utf-8")
REGISTRE = adaptateur.Adaptateur(yaml_test)
FINALE = date(2026, 11, 16)


@pytest.mark.parametrize("sujet, majeur", [
    ("BF-0001", True), ("BF-0003", False), ("BF-0017", False),
    ("BF-0005", True), ("BF-0006", True),       # homonymes : le nip les distingue
    ("BF-0011", True),                          # année seule, mais conclusive
])
def test_majeur(sujet, majeur):
    assert REGISTRE.calculer("majeur", sujet, FINALE) == {"age_equal_or_over": {"18": majeur}}


@pytest.mark.parametrize("sujet, motif", [
    ("BF-0004", "donnée insuffisante"),         # « vers 1990 »
    ("BF-0010", "donnée insuffisante"),         # 2008-11 : ne permet pas de conclure
    ("BF-0007", "personne décédée"),
    ("BF-0019", "identité ambiguë"),            # deux fiches pour le même nip
    ("BF-0099", "introuvable"),
])
def test_refus(sujet, motif):
    with pytest.raises(adaptateur.Refus, match=motif):
        REGISTRE.calculer("majeur", sujet, FINALE)


def test_anniversaire_pendant_la_finale():
    assert REGISTRE.calculer("majeur", "BF-0009", date(2026, 11, 19)) == {"age_equal_or_over": {"18": False}}
    assert REGISTRE.calculer("majeur", "BF-0009", date(2026, 11, 20)) == {"age_equal_or_over": {"18": True}}


def test_la_reponse_ne_contient_que_l_attribut():
    reponse = REGISTRE.calculer("majeur", "BF-0001", FINALE)
    assert list(reponse) == ["age_equal_or_over"]      # ni nom, ni date de naissance, ni filiation


def test_attribut_inconnu_refuse():
    with pytest.raises(adaptateur.Refus, match="non disponible"):
        REGISTRE.calculer("casier_vierge", "BF-0001", FINALE)

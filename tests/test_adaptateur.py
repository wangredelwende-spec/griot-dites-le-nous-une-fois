"""Registre simulé : calcul de l'attribut minimal et cas à refuser (données fictives)."""
import importlib.util
from datetime import date

import pytest

from conftest import ADAPTATEUR_TEST, RACINE

spec = importlib.util.spec_from_file_location("adaptateur", RACINE / "registres_sim/app/adaptateur.py")
adaptateur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adaptateur)

REGISTRE = adaptateur.Adaptateur(ADAPTATEUR_TEST)
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


def charger(nom: str):
    """Adaptateur du dépôt, lisant le CSV fictif du dépôt (au lieu de /donnees dans Docker)."""
    from conftest import TMP
    chemin = TMP / f"{nom}.yaml"
    chemin.write_text((RACINE / f"adaptateurs/{nom}.yaml").read_text(encoding="utf-8").replace(
        "/donnees/", (RACINE / "registres_sim/donnees_fictives").as_posix() + "/"), encoding="utf-8")
    return adaptateur.Adaptateur(chemin)


NATIONALITE = charger("nationalite")
CASIER = charger("casier")


@pytest.mark.parametrize("sujet, burkinabe", [("BF-0001", True), ("BF-0006", True), ("BF-0018", False)])
def test_nationalite(sujet, burkinabe):
    assert NATIONALITE.calculer("nationalite_burkinabe", sujet) == {"nationalite_burkinabe": burkinabe}


@pytest.mark.parametrize("sujet, vierge", [("BF-0001", True), ("BF-0008", False), ("BF-0005", False), ("BF-0006", True)])
def test_casier(sujet, vierge):
    reponse = CASIER.calculer("casier_vierge", sujet)
    assert reponse == {"casier_judiciaire_vierge": vierge}       # jamais le détail des condamnations


@pytest.mark.parametrize("registre, attribut, sujet, motif", [
    ("nationalite", "nationalite_burkinabe", "BF-0013", "donnée insuffisante"),   # nationalité non renseignée
    ("casier", "casier_vierge", "BF-0015", "donnée insuffisante"),               # nombre vide
    ("casier", "casier_vierge", "BF-0003", "introuvable"),                       # absent : ce n'est PAS « vierge »
])
def test_refus_nationalite_casier(registre, attribut, sujet, motif):
    with pytest.raises(adaptateur.Refus, match=motif):
        {"nationalite": NATIONALITE, "casier": CASIER}[registre].calculer(attribut, sujet)


def test_personne_connue():
    assert REGISTRE.calculer("personne_connue", "BF-0001", FINALE) == {"personne_connue": True}
    for sujet, motif in (("BF-0099", "introuvable"), ("BF-0007", "décédée"), ("BF-0019", "ambiguë")):
        with pytest.raises(adaptateur.Refus, match=motif):
            REGISTRE.calculer("personne_connue", sujet, FINALE)


def test_casier_absence_vierge(tmp_path):
    """« absence: vierge » : une personne absente du casier est vierge (le médiateur a vérifié son existence)."""
    texte = (RACINE / "adaptateurs/casier.yaml").read_text(encoding="utf-8")
    assert "absence: refus" in texte                    # comportement par défaut du dépôt
    chemin = tmp_path / "casier.yaml"
    chemin.write_text(texte.replace("absence: refus", "absence: vierge").replace(
        "/donnees/casier.csv", (RACINE / "registres_sim/donnees_fictives/casier.csv").as_posix()), encoding="utf-8")
    casier = adaptateur.Adaptateur(chemin)
    assert casier.calculer("casier_vierge", "BF-0003") == {"casier_judiciaire_vierge": True}
    assert casier.calculer("casier_vierge", "BF-0008") == {"casier_judiciaire_vierge": False}
    chemin.write_text(texte.replace("absence: refus", "absence: peut-etre"), encoding="utf-8")
    with pytest.raises(ValueError, match="absence"):
        adaptateur.Adaptateur(chemin)

"""Registre simulé : calcul de l'attribut minimal et cas à refuser (données fictives)."""
import importlib.util
from datetime import date

import pytest

from conftest import ADAPTATEUR_TEST, RACINE

adaptateur = importlib.import_module("registre_app.adaptateur")     # paquet enregistré par conftest.py

REGISTRE = adaptateur.Adaptateur(ADAPTATEUR_TEST)
FINALE = date(2026, 11, 16)


def majeur(sujet: str, jour: date = FINALE) -> dict:
    return REGISTRE.calculer("age_entre", sujet, {"min": 18, "date_reference": jour.isoformat()})


def reponse_majeur(oui: bool, jour: date = FINALE) -> dict:
    return {"age_equal_or_over": {"18": oui}, "date_reference": jour.isoformat()}


@pytest.mark.parametrize("sujet, attendu", [
    ("BF-0001", True), ("BF-0003", False), ("BF-0017", False),
    ("BF-0005", True), ("BF-0006", True),       # homonymes : le nip les distingue
    ("BF-0011", True),                          # année seule, mais conclusive
])
def test_majeur(sujet, attendu):
    assert majeur(sujet) == reponse_majeur(attendu)


@pytest.mark.parametrize("sujet, motif", [
    ("BF-0004", "donnée insuffisante"),         # « vers 1990 »
    ("BF-0010", "donnée insuffisante"),         # 2008-11 : ne permet pas de conclure
    ("BF-0007", "personne décédée"),
    ("BF-0019", "identité ambiguë"),            # deux fiches pour le même nip
    ("BF-0099", "introuvable"),
])
def test_refus(sujet, motif):
    with pytest.raises(adaptateur.Refus, match=motif):
        majeur(sujet)


def test_anniversaire_pendant_la_finale():
    assert majeur("BF-0009", date(2026, 11, 19)) == reponse_majeur(False, date(2026, 11, 19))
    assert majeur("BF-0009", date(2026, 11, 20)) == reponse_majeur(True, date(2026, 11, 20))


def test_la_reponse_ne_contient_que_l_attribut():
    reponse = majeur("BF-0001")
    assert list(reponse) == ["age_equal_or_over", "date_reference"]   # ni nom, ni date de naissance, ni filiation


def test_attribut_inconnu_refuse():
    with pytest.raises(adaptateur.Refus, match="non disponible"):
        REGISTRE.calculer("casier_judiciaire_vierge", "BF-0001")


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
    reponse = CASIER.calculer("casier_judiciaire_vierge", sujet)
    assert reponse == {"casier_judiciaire_vierge": vierge}       # jamais le détail des condamnations


@pytest.mark.parametrize("registre, attribut, sujet, motif", [
    ("nationalite", "nationalite_burkinabe", "BF-0013", "donnée insuffisante"),   # nationalité non renseignée
    ("casier", "casier_judiciaire_vierge", "BF-0015", "donnée insuffisante"),               # nombre vide
    ("casier", "casier_judiciaire_vierge", "BF-0003", "introuvable"),                       # absent : ce n'est PAS « vierge »
])
def test_refus_nationalite_casier(registre, attribut, sujet, motif):
    with pytest.raises(adaptateur.Refus, match=motif):
        {"nationalite": NATIONALITE, "casier": CASIER}[registre].calculer(attribut, sujet)


def test_personne_connue():
    assert REGISTRE.calculer("personne_connue", "BF-0001") == {"personne_connue": True}
    for sujet, motif in (("BF-0099", "introuvable"), ("BF-0007", "décédée"), ("BF-0019", "ambiguë")):
        with pytest.raises(adaptateur.Refus, match=motif):
            REGISTRE.calculer("personne_connue", sujet)


def test_casier_absence_vierge(tmp_path):
    """« absence: vierge » : une personne absente du casier est vierge (le médiateur a vérifié son existence)."""
    texte = (RACINE / "adaptateurs/casier.yaml").read_text(encoding="utf-8")
    assert "absence: refus" in texte                    # comportement par défaut du dépôt
    chemin = tmp_path / "casier.yaml"
    chemin.write_text(texte.replace("absence: refus", "absence: vierge").replace(
        "/donnees/casier.csv", (RACINE / "registres_sim/donnees_fictives/casier.csv").as_posix()), encoding="utf-8")
    casier = adaptateur.Adaptateur(chemin)
    assert casier.calculer("casier_judiciaire_vierge", "BF-0003") == {"casier_judiciaire_vierge": True}
    assert casier.calculer("casier_judiciaire_vierge", "BF-0008") == {"casier_judiciaire_vierge": False}
    assert casier.calculer("interdiction_sortie_territoire", "BF-0003") == {"interdiction_sortie_territoire": False}
    chemin.write_text(texte.replace("absence: refus", "absence: peut-etre"), encoding="utf-8")
    with pytest.raises(ValueError, match="absence"):
        adaptateur.Adaptateur(chemin)


CONCOURS = {"min": 18, "max": 37, "date_reference": "2026-12-31"}


@pytest.mark.parametrize("sujet, ages", [
    ("BF-0001", {"18": True, "38": False}),     # née en 2001 : 25 ans au 31/12/2026
    ("BF-0003", {"18": False, "38": False}),    # mineure
    ("BF-0011", {"18": True, "38": False}),     # année seule (2004) : 22 ans au 31/12/2026, quel que soit le jour
])
def test_age_entre_18_et_37_ans(sujet, ages):
    assert REGISTRE.calculer("age_entre", sujet, CONCOURS) == {"age_equal_or_over": ages,
                                                                "date_reference": "2026-12-31"}


def test_age_entre_trop_age():
    # « vers 1990 » ne permet pas de conclure ; une date exacte, si
    with pytest.raises(adaptateur.Refus, match="donnée insuffisante"):
        REGISTRE.calculer("age_entre", "BF-0004", CONCOURS)


@pytest.mark.parametrize("parametres", [{}, {"min": "dix-huit", "date_reference": "2026-12-31"},
                                        {"min": 18, "max": 10, "date_reference": "2026-12-31"},
                                        {"min": 18, "date_reference": "demain"}])
def test_age_entre_parametres_invalides(parametres):
    with pytest.raises(adaptateur.Refus, match="paramètres invalides"):
        REGISTRE.calculer("age_entre", "BF-0001", parametres)


def test_double_cle_declaree_par_le_registre():
    assert REGISTRE.autorise("age_entre", "mairie")
    assert not REGISTRE.autorise("personne_connue", "mairie")
    assert CASIER.autorise("casier_judiciaire_vierge", "direction-concours")
    assert CASIER.autorise("casier_judiciaire_vierge", "service-passeport")   # repli du jour J (sans peine complémentaire)
    assert not CASIER.autorise("casier_judiciaire_vierge", "service-bourses")


# --- Passeport : interdiction de sortie du territoire (peine complémentaire), plus minimal que « casier vierge » ---

def casier_du_depot(tmp_path):
    chemin = tmp_path / "casier.yaml"
    chemin.write_text((RACINE / "adaptateurs/casier.yaml").read_text(encoding="utf-8").replace(
        "/donnees/casier.csv", (RACINE / "registres_sim/donnees_fictives/casier.csv").as_posix()), encoding="utf-8")
    return adaptateur.Adaptateur(chemin)


@pytest.mark.parametrize("sujet, interdiction", [
    ("BF-0001", False),
    ("BF-0005", False),     # condamné pour vol, SANS interdiction : l'ONI n'en apprend rien
    ("BF-0008", True),      # interdiction de sortie du territoire inscrite
])
def test_interdiction_sortie_territoire(tmp_path, sujet, interdiction):
    reponse = casier_du_depot(tmp_path).calculer("interdiction_sortie_territoire", sujet)
    assert reponse == {"interdiction_sortie_territoire": interdiction}


@pytest.mark.parametrize("sujet, motif", [("BF-0015", "donnée insuffisante"), ("BF-0003", "introuvable")])
def test_interdiction_sortie_territoire_refus(tmp_path, sujet, motif):
    with pytest.raises(adaptateur.Refus, match=motif):
        casier_du_depot(tmp_path).calculer("interdiction_sortie_territoire", sujet)

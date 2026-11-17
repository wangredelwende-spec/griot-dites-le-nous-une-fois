"""Le banc de pannes n'utilise jamais la citoyenne de la démonstration (BF-0001) et seulement des citoyens de la liste
(ou un identifiant volontairement inconnu) ; il couvre chaque situation de l'épreuve."""
import re

from conftest import CITOYENS_DE_TEST, RACINE

SOURCE = (RACINE / "resilience/banc_de_pannes.py").read_text(encoding="utf-8")


def test_banc_sans_la_citoyenne_de_la_demo():
    assert "BF-0001" not in SOURCE


def test_banc_avec_les_citoyens_de_la_liste_seulement():
    utilises = set(re.findall(r"BF-\d{4}", SOURCE)) - {"BF-4242"}       # BF-4242 : inconnu, exprès
    assert utilises <= set(CITOYENS_DE_TEST) and "BF-4242" not in CITOYENS_DE_TEST


def test_chaque_situation_de_l_epreuve_est_au_banc():
    for situation in ("Citoyen inconnu", "Registre lent", "Registre éteint", "non conforme", "hors catalogue",
                      "Nouvelle URL", "journal modifiée", "majeur : oui", "CEFORE", "Certificat de nationalité"):
        assert situation in SOURCE, situation

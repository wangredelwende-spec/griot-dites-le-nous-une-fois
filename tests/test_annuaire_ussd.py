"""scripts/annuaire_ussd.py : un numéro fictif et un PIN de démo pour chaque citoyen de l'état civil.

Vérifié avec l'identifiant simple (nip) ET avec une clé composée (pas d'identifiant commun) : l'identifiant écrit
dans l'annuaire est retrouvé par le registre, sinon le téléphone ne verrait pas les demandes de l'usager.
"""
import csv
import subprocess
import sys

import yaml
from conftest import RACINE

DONNEES = RACINE / "registres/donnees_fictives"


def lancer(tmp_path, adaptateur=None):
    commande = [sys.executable, str(RACINE / "scripts/annuaire_ussd.py"), "--donnees", str(DONNEES),
                "--sortie", str(tmp_path), "--pin", "4321"]
    if adaptateur:
        commande += ["--yaml", str(adaptateur)]
    r = subprocess.run(commande, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    abonnes = yaml.safe_load((tmp_path / "abonnes.yaml").read_text(encoding="utf-8"))
    with open(tmp_path / "annuaire_ussd.csv", encoding="utf-8-sig") as f:
        tableau = list(csv.reader(f, delimiter=";"))[1:]
    return abonnes, tableau


def test_chaque_citoyen_a_un_numero(tmp_path):
    abonnes, tableau = lancer(tmp_path)
    sujets = [a["sujet_ref"] for a in abonnes.values()]
    assert len(sujets) == len(set(sujets)) == 21                    # 22 fiches, dont un doublon BF-0019
    assert {a["pin"] for a in abonnes.values()} == {"4321"}
    assert abonnes["71000001"] == {"sujet_ref": "BF-0001", "pin": "4321"}
    assert ["BF-0001", "KABORE Aminata", "71000001", "4321", ""] in tableau
    assert any(l[0] == "BF-0019" and "identité ambiguë" in l[4] for l in tableau)


def test_cle_composee(tmp_path):
    adaptateur = tmp_path / "etat-civil.yaml"
    adaptateur.write_text((RACINE / "registres/adaptateurs/etat-civil.yaml").read_text(encoding="utf-8").replace(
        "identite: nip", 'identite: {colonnes: [nom, prenoms, date_naissance], separateur: "|"}'), encoding="utf-8")
    abonnes, tableau = lancer(tmp_path, adaptateur)
    sujets = {a["sujet_ref"] for a in abonnes.values()}
    assert "KABORE|Aminata|2001-03-14" in sujets
    # Homonymes (Salif Compaoré) nés à des dates différentes : la date les départage, deux numéros
    compaore = [l for l in tableau if l[0].startswith("COMPAORE|Salif")]
    assert [l[0] for l in compaore] == ["COMPAORE|Salif|1985-11-30", "COMPAORE|Salif|1992-02-08"]
    assert all(l[2] and not l[4] for l in compaore)
    # BF-0019 (même nip, deux dates) : avec la clé composée, ce sont deux identifiants différents
    assert len([l for l in tableau if l[0].startswith("SANOU|Jean|")]) == 2

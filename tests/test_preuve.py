"""Preuve de minimisation : la recherche des témoins trouve bien une fuite quand il y en a une."""
import importlib.util
import sqlite3

from conftest import RACINE

spec = importlib.util.spec_from_file_location("preuve", RACINE / "scripts/preuve_minimisation.py")
preuve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preuve)

LECTURE = {"identite": "nip", "vocabulaire": ["nationalite_burkinabe", "age_entre", "age_equal_or_over"],
           "fiches": [{"nip": "BF-0001", "nom": "KABORE", "sexe": "F", "date_naissance": "2001-03-14",
                       "lieu_naissance": "Ouagadougou", "pere": "Issaka KABORE", "nationalite": "burkinabe"}]}


def test_temoins_sans_identifiant_ni_vocabulaire():
    temoins = preuve.temoins_du_registre(LECTURE)
    assert "nip" not in temoins                 # l'identifiant circule : c'est la question posée
    assert "sexe" not in temoins                # trop court
    assert "nationalite" not in temoins         # « burkinabe » fait partie du nom de l'attribut
    assert temoins["date_naissance"] == ["2001-03-14", "14/03/2001", "14-03-2001", "20010314"]


def test_fuite_trouvee_dans_une_base_sqlite(tmp_path):
    temoins = preuve.temoins_du_registre(LECTURE)
    base = sqlite3.connect(tmp_path / "fuite.sqlite3")
    base.execute("CREATE TABLE t (x TEXT)")
    base.execute("INSERT INTO t VALUES ('né le 14/03/2001 à Ouagadougou')")
    base.commit()
    base.close()
    trouves = preuve.chercher(temoins, (tmp_path / "fuite.sqlite3").read_bytes())
    assert "date_naissance « 14/03/2001 »" in trouves and "lieu_naissance « Ouagadougou »" in trouves


def test_reponse_minimale_sans_fuite():
    temoins = preuve.temoins_du_registre(LECTURE)
    reponse = b'{"sub": "BF-0001", "age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31"}'
    assert preuve.chercher(temoins, reponse) == []

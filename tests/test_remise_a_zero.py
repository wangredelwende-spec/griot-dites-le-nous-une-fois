"""remise_a_zero.py : un catalogue modifié pendant une répétition est signalé, et restauré seulement si on le veut."""
import importlib.util
import subprocess

import pytest
from conftest import RACINE

_spec = importlib.util.spec_from_file_location("remise_a_zero", RACINE / "scripts/remise_a_zero.py")
remise = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remise)


@pytest.fixture
def depot(tmp_path, monkeypatch):
    """Petit dépôt git jetable avec un catalogue committé."""
    (tmp_path / "catalogue").mkdir()
    fichier = tmp_path / "catalogue/demarches.yaml"
    fichier.write_text("demarches:\n  a: {}\n", encoding="utf-8")
    for commande in (["git", "init", "-q"], ["git", "add", "."],
                     ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(commande, cwd=tmp_path, check=True)
    monkeypatch.setattr(remise, "RACINE", tmp_path)
    return fichier


def test_catalogue_identique_rien_a_dire(depot, capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["remise_a_zero.py", "--oui"])
    remise.verifier_catalogue("D")
    assert capsys.readouterr().out == ""


def test_catalogue_modifie_signale_et_garde_sans_accord(depot, capsys, monkeypatch):
    depot.write_text("demarches:\n  a: {}\n  aide-transport-etudiant: {}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["remise_a_zero.py", "--oui"])          # pas de terminal : on ne restaure pas
    remise.verifier_catalogue("D")
    sortie = capsys.readouterr().out
    assert "diffère de la version committée" in sortie and "+  aide-transport-etudiant" in sortie
    assert "aide-transport-etudiant" in depot.read_text(encoding="utf-8")


def test_catalogue_restaure_avec_copie(depot, monkeypatch):
    depot.write_text("demarches:\n  a: {}\n  ajoutee: {}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["remise_a_zero.py", "--oui", "--restaurer-catalogue"])
    remise.verifier_catalogue("D")
    assert depot.read_text(encoding="utf-8").replace("\r\n", "\n") == "demarches:\n  a: {}\n"
    assert "ajoutee" in (depot.parent / "demarches-avant-remise-D.yaml.bak").read_text(encoding="utf-8")


def test_terminal_sans_saisie_ne_plante_pas(depot, capsys, monkeypatch):
    """Git Bash : stdin ressemble à un terminal mais ne donne rien (EOF) -> on garde le catalogue, sans planter."""
    depot.write_text("demarches:\n  a: {}\n  ajoutee: {}\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["remise_a_zero.py", "--oui"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)

    def sans_saisie(_question):
        raise EOFError
    monkeypatch.setattr("builtins.input", sans_saisie)
    remise.verifier_catalogue("D")
    assert "Catalogue gardé tel quel" in capsys.readouterr().out
    assert "ajoutee" in depot.read_text(encoding="utf-8")

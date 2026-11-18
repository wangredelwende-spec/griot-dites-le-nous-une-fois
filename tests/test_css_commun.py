"""Les trois copies de la feuille commune doivent rester identiques."""
import hashlib

from conftest import RACINE

COPIES = (
    RACINE / "espace-usager/portail/app/static/griot.css",
    RACINE / "guichet-agent/app/static/griot.css",
    RACINE / "espace-usager/ussd/app/static/griot.css",
)


def test_trois_copies_identiques():
    empreintes = {hashlib.sha256(copie.read_bytes()).hexdigest() for copie in COPIES}
    assert len(empreintes) == 1, f"copies divergentes : {empreintes}"


def test_feuille_sans_ressource_externe():
    css = COPIES[0].read_text(encoding="utf-8")
    assert "url(" not in css and "@import" not in css and "http" not in css

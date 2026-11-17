"""Guichet des agents : pages protégées, aucune ressource externe. Les tests « pile » s'exécutent contre la pile qui
tourne (https://guichet.griot.test, certificat interne de Caddy) et sont ignorés si elle est arrêtée."""
import re
from pathlib import Path

import httpx
import pytest

RACINE = Path(__file__).resolve().parents[2]
GUICHET = "https://guichet.griot.test"


def test_gabarits_sans_script_ni_ressource_externe():
    """Règle 4 (aucune dépendance à Internet) et 8 (pas de JavaScript) : lues dans les gabarits eux-mêmes."""
    for gabarit in (RACINE / "guichet-agent/app/templates").glob("*.html"):
        texte = gabarit.read_text(encoding="utf-8")
        assert "<script" not in texte, gabarit.name
        assert not re.search(r'(src|href)="https?://', texte), gabarit.name
        assert "@import" not in texte and "cdn" not in texte.lower(), gabarit.name


@pytest.fixture(scope="module")
def pile():
    try:
        return httpx.Client(verify=False, follow_redirects=False, timeout=5)
    except Exception as e:                                           # pragma: no cover
        pytest.skip(f"client indisponible : {e}")


def get(pile, chemin):
    try:
        return pile.get(GUICHET + chemin)
    except httpx.HTTPError:
        pytest.skip("pile arrêtée (guichet.griot.test injoignable)")


def test_pile_sante(pile):
    r = get(pile, "/sante")
    assert r.status_code == 200 and r.text == "ok"


def test_pile_pages_protegees_renvoient_vers_la_connexion(pile):
    for chemin in ("/", "/controle", "/demandes/00000000-0000-4000-8000-000000000000"):
        r = get(pile, chemin)
        assert r.status_code in (302, 303, 307) and "/connexion" in r.headers["location"], chemin


def test_pile_connexion_envoie_vers_keycloak(pile):
    r = get(pile, "/connexion")
    assert r.status_code in (302, 303, 307) and r.headers["location"].startswith("https://auth.griot.test/realms/griot/")

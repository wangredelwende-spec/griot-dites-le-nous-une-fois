"""Le banc de pannes n'utilise jamais un citoyen de la démo (limite de 5 demandes / 24 h, historique propre)."""
import re

from conftest import RACINE

DEMO = {"BF-0012", "BF-0005", "BF-0015"}     # Aïssata (bourse), Salif (passeport), Karim (casier incomplet)


def test_banc_sans_citoyen_de_la_demo():
    source = (RACINE / "scripts/banc_de_pannes.py").read_text(encoding="utf-8")
    declares = re.search(r"CITOYENS_DE_LA_DEMO = (\{[^}]*\})", source).group(1)
    assert eval(declares) == DEMO                    # la liste du banc est bien celle de la démo
    code = source.replace(declares, "")              # en dehors de cette liste, aucun identifiant de la démo
    assert not DEMO & set(re.findall(r"BF-\d{4}", code))

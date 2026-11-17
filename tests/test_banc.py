"""Le banc de pannes n'utilise jamais un citoyen de la démo (limite de 5 demandes / 24 h, historique propre)."""
import re

from conftest import RACINE

DEMO = {"BF-0012", "BF-0005", "BF-0015", "BF-0001"}   # Aïssata (bourse), Salif (passeport), Karim (casier
                                                       # incomplet), Aminata (passeport et concours)


def test_citoyen_reserve_au_banc_present_dans_les_trois_registres():
    for fichier in ("etat_civil", "nationalite", "casier"):
        lignes = (RACINE / f"registres_sim/donnees_fictives/{fichier}.csv").read_text(encoding="utf-8").splitlines()
        assert sum(l.startswith("BF-0021;") for l in lignes) == 1, fichier


def test_banc_sans_citoyen_de_la_demo():
    source = (RACINE / "scripts/banc_de_pannes.py").read_text(encoding="utf-8")
    declares = re.search(r"CITOYENS_DE_LA_DEMO = (\{[^}]*\})", source).group(1)
    assert eval(declares) == DEMO                    # la liste du banc est bien celle de la démo
    code = source.replace(declares, "")              # en dehors de cette liste, aucun identifiant de la démo
    assert not DEMO & set(re.findall(r"BF-\d{4}", code))

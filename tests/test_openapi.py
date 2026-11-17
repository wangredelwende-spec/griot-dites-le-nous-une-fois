"""Le contrat d'API commité (openapi.yaml de chaque couche) est EXACTEMENT celui que le code produit.

Une route ajoutée, retirée ou changée sans relancer scripts/generer_openapi.py fait échouer ce test : la
documentation donnée aux coéquipiers et au jury ne peut pas diverger du code."""
import importlib.util

import pytest

from conftest import RACINE

spec = importlib.util.spec_from_file_location("generer_openapi", RACINE / "scripts/generer_openapi.py")
generer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generer)


@pytest.mark.parametrize("couche", list(generer.COUCHES))
def test_openapi_commite_egal_openapi_genere(couche):
    commite = (RACINE / generer.COUCHES[couche][0]).read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert generer.generer_dans_un_processus(couche) == commite, (
        f"{generer.COUCHES[couche][0]} ne correspond plus au code : lancer "
        f".venv\\Scripts\\python scripts\\generer_openapi.py --couche {couche}")

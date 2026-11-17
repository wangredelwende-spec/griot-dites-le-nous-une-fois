"""Tests GÉNÉRÉS depuis le contrat (Schemathesis, MIT) contre les 3 registres simulés.

Le contrat est celui de GRIOT_CONTRAT (aujourd'hui le PROVISOIRE ; demain celui du jury, sans changer ce fichier).
Pour chaque route du contrat servie par un registre, Schemathesis fabrique des identifiants (quelconques, longs,
accentués…) et vérifie que CHAQUE réponse a un code prévu par le contrat (200 ou 404) et un corps conforme à son schéma.
"""
import schemathesis
from hypothesis import settings
from conftest import ANNUAIRE_DE_TEST, CHEMIN_CONTRAT, registres_reels

schemathesis.experimental.OPEN_API_3_1.enable()        # le contrat est en OpenAPI 3.1

REELS = registres_reels()
SCHEMAS = {registre: schemathesis.from_path(str(CHEMIN_CONTRAT), app=REELS[registre].app).include(path=r["chemin"])
           for registre, r in ANNUAIRE_DE_TEST["registres"].items()}


def verifier(case):
    reponse = case.call_asgi()
    case.validate_response(reponse)          # code documenté, Content-Type, schéma de la réponse


@SCHEMAS["etat-civil"].parametrize()
@settings(max_examples=30, deadline=None)
def test_etat_civil_conforme_au_contrat(case):
    verifier(case)


@SCHEMAS["nationalite"].parametrize()
@settings(max_examples=30, deadline=None)
def test_nationalite_conforme_au_contrat(case):
    verifier(case)


@SCHEMAS["casier"].parametrize()
@settings(max_examples=30, deadline=None)
def test_casier_conforme_au_contrat(case):
    verifier(case)

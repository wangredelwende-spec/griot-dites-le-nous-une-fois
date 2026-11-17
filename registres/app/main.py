"""Registre simulé SELON LE CONTRAT : une route, la fiche d'un citoyen par son identifiant, 404 s'il est inconnu.

Un seul code, une instance par registre (état civil, nationalité, casier). Tout vient de la configuration :
- GRIOT_CONTRAT  : le contrat OpenAPI (registres/contrat/contrat-registres.yaml) ;
- GRIOT_CITOYENS : la liste des citoyens fictifs (registres/donnees/citoyens-fictifs.yaml) ;
- REGISTRE_CHEMIN : la route que CETTE instance sert (ex. /etat-civil/{id}) : ses champs sont ceux du schéma de sa
  réponse 200 dans le contrat. Rien d'autre ne sort de la fiche du citoyen.
- PANNE : normal | lent | eteint | non_conforme (lue à chaque appel ; resilience/panne.py la change).

DÉSACTIVÉ le 17/11 (voir LIMITES.md) : plus de jeton Keycloak de l'agent, plus de signature Ed25519, plus de double
trace côté registre. Cet ancien code est conservé dans ancien_main.py, adaptateur.py et sources.py.
Joignable uniquement par le réseau Docker « registres » (la passerelle seulement).
"""
import asyncio
import os
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

CONTRAT = Path(os.environ.get("GRIOT_CONTRAT", "/contrat/contrat.yaml"))
CITOYENS = Path(os.environ.get("GRIOT_CITOYENS", "/donnees/citoyens.yaml"))
CHEMIN = os.environ.get("REGISTRE_CHEMIN", "/etat-civil/{id}")
DELAI_PANNE_LENTE = float(os.environ.get("DELAI_PANNE_LENTE", "10"))      # secondes (la passerelle abandonne à 2 s)


def schema_de_la_reponse(contrat: dict, chemin: str) -> dict:
    """Schéma de la réponse 200 de la route, avec ses $ref locaux résolus (un seul niveau suffit pour ce contrat)."""
    schema = contrat["paths"][chemin]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    if "$ref" in schema:
        schema = contrat["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


CHAMPS = list(schema_de_la_reponse(yaml.safe_load(CONTRAT.read_text(encoding="utf-8")), CHEMIN)["properties"])
FICHES = {str(c["id"]): c for c in yaml.safe_load(CITOYENS.read_text(encoding="utf-8"))["citoyens"]}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, title="Registre simulé (selon le contrat)")


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


def mode_de_panne() -> str:
    return os.environ.get("PANNE", "normal").strip().lower()


@app.get(CHEMIN)
async def lire_fiche(id: str):
    panne = mode_de_panne()
    if panne == "eteint":
        return JSONResponse({"detail": "registre éteint (panne simulée)"}, status_code=503)
    if panne == "lent":
        await asyncio.sleep(DELAI_PANNE_LENTE)             # bien au-delà du délai de la passerelle
    fiche = FICHES.get(id)
    if fiche is None:
        return JSONResponse({"detail": "citoyen inconnu"}, status_code=404)
    if panne == "non_conforme":
        return {"reponse": "non conforme au contrat"}      # ne respecte pas le schéma : la passerelle doit la rejeter
    return {champ: fiche.get(champ) for champ in CHAMPS}   # exactement les champs du contrat, rien d'autre

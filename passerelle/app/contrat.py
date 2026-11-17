"""Le contrat OpenAPI des registres, indiqué en CONFIGURATION (GRIOT_CONTRAT) : la passerelle y lit la forme exacte
d'une réponse valide pour chaque route. Une réponse qui n'y est pas conforme est REJETÉE (règle d'or : on ne devine pas).

Remplacer le contrat (celui du jury, ou d'une autre équipe) = remplacer ce fichier, sans toucher au code.
Bibliothèque : jsonschema (MIT) ; aucune validation écrite à la main.
"""
import yaml
from jsonschema import Draft202012Validator

from .config import CONTRAT


class ContratIllisible(Exception):
    pass


def charger(chemin=CONTRAT) -> dict:
    try:
        return yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ContratIllisible(f"contrat illisible ({chemin}) : {str(e)[:200]}")


def erreurs_de_conformite(contrat: dict, route: str, corps) -> list[str]:
    """Écarts entre la réponse 200 d'un registre et le schéma du contrat pour cette route (liste vide = conforme).
    Route absente du contrat, ou sans réponse 200 JSON : aucune réponse ne peut être jugée conforme."""
    try:
        schema = contrat["paths"][route]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    except (KeyError, TypeError):
        return [f"route « {route} » ou sa réponse 200 absente du contrat"]
    racine = dict(schema) | {"components": contrat.get("components", {})}      # les « $ref » locaux se résolvent ici
    return [f"{'/'.join(map(str, e.absolute_path)) or 'réponse'} : {e.message[:120]}"
            for e in Draft202012Validator(racine).iter_errors(corps)]

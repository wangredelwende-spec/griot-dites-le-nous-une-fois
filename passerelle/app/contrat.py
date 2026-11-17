"""Le contrat OpenAPI des registres, indiqué en CONFIGURATION (GRIOT_CONTRAT) : la passerelle y lit la forme exacte
d'une réponse valide pour chaque route. Une réponse qui n'y est pas conforme est REJETÉE (règle d'or : on ne devine pas).

Par défaut : NOTRE contrat des registres (registres/contrat/contrat-registres.yaml). Le registre d'une AUTRE équipe
est jugé sur SON contrat : « contrat: contrats/<fichier>.yaml » dans son bloc d'annuaire.yaml (chemin relatif au
catalogue), le fichier OpenAPI publié par cette équipe, copié tel quel (docs/brancher-un-registre.md).
Bibliothèque : jsonschema (MIT) ; aucune validation écrite à la main.
"""
import yaml
from jsonschema import Draft202012Validator

from .config import CATALOGUE, CONTRAT


class ContratIllisible(Exception):
    pass


def charger(chemin=CONTRAT) -> dict:
    try:
        return yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ContratIllisible(f"contrat illisible ({chemin}) : {str(e)[:200]}")


def chemin_du_contrat(registre: dict):
    """Le contrat qui juge CE registre : le sien (« contrat » dans annuaire.yaml, relatif au catalogue), sinon le nôtre."""
    return CATALOGUE / registre["contrat"] if registre.get("contrat") else CONTRAT


_CONTRATS = {}      # chemin -> (date de modification, contrat) : relu seulement si le fichier change


def contrat_du_registre(registre: dict, defaut: dict) -> dict:
    """Contrat d'un registre d'une autre équipe (relu s'il change), ou « defaut » (notre contrat chargé au démarrage)."""
    if not registre.get("contrat"):
        return defaut
    chemin = chemin_du_contrat(registre)
    try:
        date = chemin.stat().st_mtime
    except OSError as e:
        raise ContratIllisible(f"contrat illisible ({chemin}) : {e}")
    if _CONTRATS.get(chemin, (None,))[0] != date:
        _CONTRATS[chemin] = (date, charger(chemin))
    return _CONTRATS[chemin][1]


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

"""Minimisation dans la PASSERELLE : à partir de la fiche brute d'un registre (selon le contrat du jury), on calcule
ce qui est permis (« majeur : oui », « nationalité burkinabè : oui », « casier vierge : oui », identité, naissance et
filiation) et RIEN d'autre. La fiche brute ne sort jamais de cette fonction.

Les noms de champs du contrat ne sont écrits qu'UNE fois, dans catalogue/correspondance.yaml. Règle d'or : champ
non renseigné dans la correspondance, absent de la fiche ou vide -> refus, on ne devine pas.
(Hypothèse à confirmer avec le contrat : la fiche est un objet JSON « à plat », un champ = une valeur.)
"""
from datetime import date

from .ages import age_entre
from .refus import Refus
from .regles import calculer


def champ_du_contrat(correspondance: dict, registre: str, nom: str) -> str:
    """Nom du champ dans la réponse du registre, d'après la correspondance. Vide : refus."""
    champ = ((correspondance.get("registres") or {}).get(registre) or {}).get(nom)
    if not champ:
        raise Refus(f"correspondance non renseignée pour {registre}.{nom} (contrat du jury à reporter)")
    return champ


def lire(brut: dict, correspondance: dict, registre: str, nom: str) -> str:
    valeur = brut.get(champ_du_contrat(correspondance, registre, nom))
    if valeur is None or not str(valeur).strip():
        raise Refus(f"donnée insuffisante : « {nom} » absent ou vide")
    return str(valeur).strip()


def lire_ou_vide(brut: dict, correspondance: dict, registre: str, nom: str) -> str:
    """Comme lire(), mais un champ absent ou vide donne « » (ex. date de décès : vivant). Correspondance non
    renseignée : refus (on ne sait pas lire ce champ, donc on ne conclut pas)."""
    return str(brut.get(champ_du_contrat(correspondance, registre, nom)) or "").strip()


def valeur_date_complete(texte: str) -> str:
    try:
        return date.fromisoformat(texte).isoformat()
    except ValueError:
        raise Refus("donnée insuffisante : date de naissance incomplète")


def minimiser(attribut: dict, registre: str, brut: dict, correspondance: dict, parametres: dict | None = None):
    """Renvoie un booléen (oui/non) ou, pour identité et naissance/filiation, un dict des seules cases permises.
    « attribut » : sa déclaration (registres/adaptateurs/<registre>.yaml : regle, champ ou champs, valeur…)."""
    regle = attribut["regle"]
    if regle == "champs":
        utiles = {}
        for nom in attribut["champs"]:
            valeur = lire(brut, correspondance, registre, nom)
            if nom == "date_naissance":                    # date complète exigée : « né vers 1990 » -> refus
                valeur = valeur_date_complete(valeur)
            utiles[nom] = valeur
        return utiles
    valeur = lire(brut, correspondance, registre, attribut["champ"])
    parametres = parametres or {}
    if regle == "age_entre":
        ages = age_entre(valeur, "age", parametres)["age"]      # {"18": True} ou {"18": True, "38": False}
        seuils = [str(parametres["min"])] + ([str(parametres["max"] + 1)] if parametres.get("max") is not None else [])
        return ages[seuils[0]] and not (len(seuils) == 2 and ages[seuils[1]])
    return calculer(attribut | {"claim": "resultat"}, valeur, parametres)["resultat"]

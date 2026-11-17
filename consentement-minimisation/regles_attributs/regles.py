"""Règles de calcul d'un attribut à partir d'UNE case de la fiche. Une règle = un mot dans l'adaptateur YAML.

existe        : la fiche existe (identité confirmée)             -> oui
age_entre     : âge entre « min » et « max » ans à une date      -> {"age_equal_or_over": {"18": oui, "38": non}}
egal          : la case est égale à « valeur » (nationalité…)    -> oui / non
contient      : la case contient une « mention » (peine…)        -> oui / non
nombre_nul    : la case est le nombre 0 (condamnations…)         -> oui / non
Une case vide ou illisible n'est ni « oui » ni « non » : refus.
"""
import unicodedata

from .ages import age_entre
from .refus import Refus


def normaliser_texte(valeur: str) -> str:
    """Pour comparer des valeurs écrites différemment : « Burkinabè » = « BURKINABE » = « burkinabe »."""
    sans_accents = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
    return " ".join(sans_accents.casefold().split())


def egal(valeur: str, regle: dict) -> bool:
    """Nationalité, par exemple. Sans accents ni majuscules. Plusieurs valeurs « a ; b » (double nationalité) :
    oui si l'une d'elles convient.
    - sans « correspondances » : égal à « valeur » -> oui ; toute autre valeur renseignée -> non ;
    - avec « correspondances: {oui: [...], non: [...]} » : une valeur qui n'est dans AUCUNE des deux listes
      -> refus (on ne devine pas ce que veut dire « BF » si personne ne l'a écrit)."""
    morceaux = [normaliser_texte(m) for m in valeur.split(";") if m.strip()]
    correspondances = regle.get("correspondances")
    if not correspondances:
        return normaliser_texte(str(regle["valeur"])) in morceaux
    oui = {normaliser_texte(str(v)) for v in correspondances.get("oui", [])}
    non = {normaliser_texte(str(v)) for v in correspondances.get("non", [])}
    if any(m in oui for m in morceaux):
        return True
    if all(m in non for m in morceaux):
        return False
    raise Refus("donnée insuffisante : valeur non reconnue (à ajouter dans « correspondances »)")


def calculer(regle: dict, valeur: str, parametres: dict, format_date=None) -> dict:
    """Réponse minimale pour UNE règle. « valeur » = la case de la fiche, déjà lue par l'adaptateur
    (inutilisée pour « existe »). Renvoie par exemple {"nationalite_burkinabe": True}."""
    nom, claim = regle["regle"], regle["claim"]
    if nom == "existe":
        return {claim: True}                # une seule fiche, personne vivante : identité confirmée
    if nom == "age_entre":
        return age_entre(valeur, claim, parametres, format_date)
    if not valeur:
        raise Refus("donnée insuffisante : champ vide")       # vide n'est ni « oui » ni « non »
    if nom == "egal":
        return {claim: egal(valeur, regle)}
    if nom == "contient":
        # ex. peines complémentaires : « interdiction de sortie du territoire (5 ans) » -> true ;
        # « aucune » ou une autre peine -> false ; vide -> refus (plus haut)
        return {claim: regle["mention"].lower() in valeur.lower()}
    if nom == "nombre_nul":
        # ex. casier : nombre de condamnations « 0 » -> vierge ; « 2 » -> non vierge ; autre -> refus
        if not valeur.isdigit():
            raise Refus("donnée insuffisante : nombre illisible")
        return {claim: int(valeur) == 0}
    raise Refus("règle inconnue dans l'adaptateur")

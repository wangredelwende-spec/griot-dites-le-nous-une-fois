"""Âges et dates de naissance, y compris incomplètes. Règle d'or : si la date ne permet pas de conclure, on REFUSE."""
import calendar
import re
from datetime import date, datetime

from .refus import Refus


def bornes_de_naissance(texte: str, format_date: str | list | None = None) -> tuple[date, date]:
    """Date de naissance -> (date la plus ancienne possible, date la plus récente possible).

    « 2001-03-14 » : date exacte.  « 2008-11 » : du 1er au 30 novembre 2008.  « 2004 » : du 1er janvier
    au 31 décembre 2004.  Avec « format_date: "%d/%m/%Y" » dans l'adaptateur : « 14/03/2001 » aussi.
    « vers 1990 », vide ou illisible : refus (on ne connaît pas l'écart).
    """
    t = texte.strip()
    for forme in ([format_date] if isinstance(format_date, str) else format_date or []):
        try:
            exacte = datetime.strptime(t, forme).date()
            return exacte, exacte
        except ValueError:
            pass        # autre format, ou date partielle (« 2004 ») : on essaie les formes suivantes
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        exacte = date.fromisoformat(t)
        return exacte, exacte
    if m := re.fullmatch(r"(\d{4})-(\d{2})", t):
        annee, mois = int(m[1]), int(m[2])
        return date(annee, mois, 1), date(annee, mois, calendar.monthrange(annee, mois)[1])
    if re.fullmatch(r"\d{4}", t):
        return date(int(t), 1, 1), date(int(t), 12, 31)
    raise Refus("donnée insuffisante : date de naissance approximative ou illisible")


def age_le(naissance: date, jour: date) -> int:
    """Âge en années révolues au jour donné."""
    return jour.year - naissance.year - ((jour.month, jour.day) < (naissance.month, naissance.day))


def age_minimum_atteint(texte_naissance: str, age: int, jour: date, format_date=None) -> bool:
    plus_ancienne, plus_recente = bornes_de_naissance(texte_naissance, format_date)
    if age_le(plus_recente, jour) >= age:     # même né le plus tard possible, il a l'âge
        return True
    if age_le(plus_ancienne, jour) < age:     # même né le plus tôt possible, il n'a pas l'âge
        return False
    raise Refus("donnée insuffisante : la date de naissance ne permet pas de conclure")


def normaliser(parametres: dict, aujourdhui: date) -> dict:
    """Forme comparable : « aujourd'hui » devient la date du jour, max absent devient None."""
    reference = str(parametres.get("date_reference"))
    if reference == "aujourd'hui":
        reference = aujourdhui.isoformat()
    return {"min": parametres.get("min"), "max": parametres.get("max"), "date_reference": reference}


def age_entre(naissance: str, claim: str, parametres: dict, format_date=None) -> dict:
    """Âge entre « min » et « max » ans (max facultatif) à la date « date_reference ».

    Réponse : {"age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31"}
    = « a au moins 18 ans » et « n'a pas encore 38 ans » (donc 37 ans au plus). Jamais la date de naissance.
    """
    try:
        mini = int(parametres["min"])
        maxi = None if parametres.get("max") is None else int(parametres["max"])
        reference = date.fromisoformat(str(parametres["date_reference"]))
    except (KeyError, TypeError, ValueError):
        raise Refus("paramètres invalides (min, max, date_reference attendus)")
    if not 0 <= mini <= 150 or (maxi is not None and not mini <= maxi <= 150):
        raise Refus("paramètres invalides (âges hors limites)")
    ages = {str(mini): age_minimum_atteint(naissance, mini, reference, format_date)}
    if maxi is not None:
        ages[str(maxi + 1)] = age_minimum_atteint(naissance, maxi + 1, reference, format_date)
    return {claim: ages, "date_reference": reference.isoformat()}

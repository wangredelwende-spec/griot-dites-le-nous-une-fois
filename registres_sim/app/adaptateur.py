"""Lecture d'un registre décrite par un fichier YAML (adaptateurs/<registre>.yaml).

On branche un nouveau registre en écrivant un fichier YAML, sans changer ce code.
Règle d'or : si la donnée ne permet pas de conclure, on REFUSE avec un motif ; on ne devine jamais.
"""
import calendar
import csv
import json
import re
from datetime import date
from pathlib import Path

import yaml


class Refus(Exception):
    """Le registre ne peut pas répondre : le motif est renvoyé tel quel au médiateur."""


def lire_source(source: dict) -> list[dict]:
    chemin = Path(source["chemin"])
    # « utf-8-sig » : accepte le marqueur BOM qu'ajoute Excel
    with open(chemin, encoding="utf-8-sig", newline="") as fichier:
        if source["type"] == "csv":
            return list(csv.DictReader(fichier, delimiter=source.get("separateur", ";")))
        if source["type"] == "json":
            return json.load(fichier)
    raise ValueError(f"type de source inconnu : {source['type']}")


def bornes_de_naissance(texte: str) -> tuple[date, date]:
    """Date de naissance -> (date la plus ancienne possible, date la plus récente possible).

    « 2001-03-14 » : date exacte.  « 2008-11 » : du 1er au 30 novembre 2008.  « 2004 » : du 1er janvier
    au 31 décembre 2004.  « vers 1990 » ou illisible : refus (on ne connaît pas l'écart).
    """
    t = texte.strip()
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


def age_minimum_atteint(texte_naissance: str, age: int, aujourdhui: date) -> bool:
    plus_ancienne, plus_recente = bornes_de_naissance(texte_naissance)
    if age_le(plus_recente, aujourdhui) >= age:     # même né le plus tard possible, il a l'âge
        return True
    if age_le(plus_ancienne, aujourdhui) < age:     # même né le plus tôt possible, il n'a pas l'âge
        return False
    raise Refus("donnée insuffisante : la date de naissance ne permet pas de conclure")


class Adaptateur:
    def __init__(self, chemin: Path):
        conf = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        self.registre = conf["registre"]
        self.emetteur = conf["emetteur"]
        self.identite = conf["identite"]
        self.champs = conf.get("champs", {})
        self.refuser_si_decede = conf.get("refuser_si_decede", False)
        # Seul motif de refus envoyé hors du registre (signé) : il ne révèle rien de la fiche
        self.motif_refus_public = conf["motif_refus_public"]
        self.attributs = conf["attributs"]
        self.lignes = lire_source(conf["source"])

    def valeur(self, ligne: dict, nom: str) -> str:
        return (ligne.get(self.champs[nom]) or "").strip()

    def trouver(self, sujet_ref: str) -> dict:
        fiches = [l for l in self.lignes if (l.get(self.identite) or "").strip() == sujet_ref]
        if not fiches:
            raise Refus("introuvable")
        if len(fiches) > 1:
            raise Refus("identité ambiguë : plusieurs fiches pour cet identifiant")
        return fiches[0]

    def calculer(self, attribut: str, sujet_ref: str, aujourdhui: date | None = None) -> dict:
        """Renvoie UNIQUEMENT la réponse minimale, par exemple {"age_equal_or_over": {"18": True}}."""
        regle = self.attributs.get(attribut)
        if regle is None:
            raise Refus("attribut non disponible dans ce registre")
        fiche = self.trouver(sujet_ref)
        if self.refuser_si_decede and "date_deces" in self.champs and self.valeur(fiche, "date_deces"):
            raise Refus("personne décédée")
        if regle["regle"] == "age_minimum":
            age = int(regle["age"])
            atteint = age_minimum_atteint(self.valeur(fiche, regle["champ"]), age, aujourdhui or date.today())
            return {regle["claim"]: {str(age): atteint}}
        valeur = self.valeur(fiche, regle["champ"])
        if not valeur:
            raise Refus("donnée insuffisante : champ vide")       # vide n'est ni « oui » ni « non »
        if regle["regle"] == "egal":
            # ex. nationalité : « burkinabe » -> true ; toute autre nationalité renseignée -> false
            return {regle["claim"]: valeur.lower() == str(regle["valeur"]).lower()}
        if regle["regle"] == "nombre_nul":
            # ex. casier : nombre de condamnations « 0 » -> vierge ; « 2 » -> non vierge ; autre -> refus
            if not valeur.isdigit():
                raise Refus("donnée insuffisante : nombre illisible")
            return {regle["claim"]: int(valeur) == 0}
        raise Refus("règle inconnue dans l'adaptateur")

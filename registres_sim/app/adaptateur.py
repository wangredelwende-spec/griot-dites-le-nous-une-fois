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


def age_minimum_atteint(texte_naissance: str, age: int, jour: date) -> bool:
    plus_ancienne, plus_recente = bornes_de_naissance(texte_naissance)
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
        self.groupes = conf.get("groupes", {})     # groupe Keycloak -> code du service
        # Personne absente du registre : « refus » (par défaut) ou « vierge » (casier réel : une personne jamais
        # condamnée n'y figure pas). Avec « vierge », le MÉDIATEUR vérifie d'abord à l'état civil que la
        # personne existe : sinon, un identifiant inventé obtiendrait « casier vierge ».
        self.absence = conf.get("absence", "refus")
        if self.absence not in ("refus", "vierge"):
            raise ValueError(f"{chemin.name} : absence doit valoir « refus » ou « vierge »")
        if self.absence == "vierge" and any(r["regle"] not in ("nombre_nul", "contient") for r in self.attributs.values()):
            raise ValueError(f"{chemin.name} : « absence: vierge » n'a de sens que pour les règles nombre_nul et contient")
        self.lignes = lire_source(conf["source"])

    def valeur(self, ligne: dict, nom: str) -> str:
        return (ligne.get(self.champs[nom]) or "").strip()

    def fiches(self, sujet_ref: str) -> list[dict]:
        return [l for l in self.lignes if (l.get(self.identite) or "").strip() == sujet_ref]

    def trouver(self, sujet_ref: str) -> dict:
        fiches = self.fiches(sujet_ref)
        if not fiches:
            raise Refus("introuvable")
        if len(fiches) > 1:
            raise Refus("identité ambiguë : plusieurs fiches pour cet identifiant")
        return fiches[0]

    def autorise(self, attribut: str, service: str) -> bool:
        """Double clé : le registre décide LUI-MÊME quels services peuvent demander quel attribut
        (« services » de l'attribut), même si le médiateur a laissé passer la demande."""
        return service in self.attributs.get(attribut, {}).get("services", [])

    def parametres_autorises(self, attribut: str, service: str, parametres: dict, aujourdhui: date) -> bool:
        """Double clé sur les PARAMÈTRES : seuls les seuils et dates déclarés pour CE service sont acceptés
        (empêche de reconstituer une date de naissance avec des seuils différents)."""
        autorisations = self.attributs.get(attribut, {}).get("services", [])
        if isinstance(autorisations, list):              # attribut sans paramètre
            return not parametres
        demande = normaliser(parametres, aujourdhui)
        return any(normaliser(p, aujourdhui) == demande for p in autorisations.get(service) or [])

    def calculer(self, attribut: str, sujet_ref: str, parametres: dict | None = None) -> dict:
        """Renvoie UNIQUEMENT la réponse minimale, par exemple {"nationalite_burkinabe": True}."""
        parametres = parametres or {}
        regle = self.attributs.get(attribut)
        if regle is None:
            raise Refus("attribut non disponible dans ce registre")
        if self.absence == "vierge" and not self.fiches(sujet_ref):
            # jamais condamné = absent du casier (existence vérifiée avant) : casier vierge = oui ;
            # aucune mention possible (ex. interdiction de sortie du territoire) = non
            return {regle["claim"]: regle["regle"] == "nombre_nul"}
        fiche = self.trouver(sujet_ref)
        if self.refuser_si_decede and "date_deces" in self.champs and self.valeur(fiche, "date_deces"):
            raise Refus("personne décédée")
        if regle["regle"] == "existe":
            return {regle["claim"]: True}       # une seule fiche, personne vivante : identité confirmée
        if regle["regle"] == "age_entre":
            return self.age_entre(fiche, regle, parametres)
        valeur = self.valeur(fiche, regle["champ"])
        if not valeur:
            raise Refus("donnée insuffisante : champ vide")       # vide n'est ni « oui » ni « non »
        if regle["regle"] == "egal":
            # ex. nationalité : « burkinabe » -> true ; toute autre nationalité renseignée -> false
            return {regle["claim"]: valeur.lower() == str(regle["valeur"]).lower()}
        if regle["regle"] == "contient":
            # ex. peines complémentaires : « interdiction de sortie du territoire (5 ans) » -> true ;
            # « aucune » ou une autre peine -> false ; vide -> refus (plus haut)
            return {regle["claim"]: regle["mention"].lower() in valeur.lower()}
        if regle["regle"] == "nombre_nul":
            # ex. casier : nombre de condamnations « 0 » -> vierge ; « 2 » -> non vierge ; autre -> refus
            if not valeur.isdigit():
                raise Refus("donnée insuffisante : nombre illisible")
            return {regle["claim"]: int(valeur) == 0}
        raise Refus("règle inconnue dans l'adaptateur")

    def age_entre(self, fiche: dict, regle: dict, parametres: dict) -> dict:
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
        naissance = self.valeur(fiche, regle["champ"])
        ages = {str(mini): age_minimum_atteint(naissance, mini, reference)}
        if maxi is not None:
            ages[str(maxi + 1)] = age_minimum_atteint(naissance, maxi + 1, reference)
        return {regle["claim"]: ages, "date_reference": reference.isoformat()}

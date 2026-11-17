"""Lecture d'un registre décrite par un fichier YAML (registres/adaptateurs/<registre>.yaml).

On branche un nouveau registre en écrivant un fichier YAML, sans changer ce code.
Règle d'or : si la donnée ne permet pas de conclure, on REFUSE avec un motif ; on ne devine jamais.
"""
import calendar
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import yaml

from .sources import (SourceIndisponible, empreinte_fichier, interroger_api,  # noqa: F401 (SourceIndisponible : main.py)
                      lire_source)


def normaliser_texte(valeur: str) -> str:
    """Pour comparer des valeurs écrites différemment : « Burkinabè » = « BURKINABE » = « burkinabe »."""
    sans_accents = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
    return " ".join(sans_accents.casefold().split())


class Refus(Exception):
    """Le registre ne peut pas répondre : le motif est renvoyé tel quel au médiateur."""


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


class Adaptateur:
    def __init__(self, chemin: Path):
        conf = yaml.safe_load(chemin.read_text(encoding="utf-8"))
        self.registre = conf["registre"]
        self.emetteur = conf["emetteur"]
        # Clé d'identité : UNE colonne (« identite: nip », comparée telle quelle), ou une CLÉ COMPOSÉE quand les
        # registres n'ont pas d'identifiant commun :
        #   identite: {colonnes: [nom, prenoms, date_naissance], separateur: "|"}
        # L'identifiant de l'usager est alors « KABORE|Aminata|2001-03-14 » : chaque morceau est comparé à la
        # colonne correspondante, sans accents, majuscules ni espaces en trop, dates ramenées à 2001-03-14.
        # Comparaison EXACTE : jamais de rapprochement approximatif. Plusieurs fiches -> refus « homonymes ».
        identite = conf["identite"]
        self.cle_composee = isinstance(identite, dict)
        self.identite = identite["colonnes"] if self.cle_composee else identite
        self.separateur_cle = identite.get("separateur", "|") if self.cle_composee else None
        self.champs = conf.get("champs", {})
        self.refuser_si_decede = conf.get("refuser_si_decede", False)
        # Seul motif de refus envoyé hors du registre (signé) : il ne révèle rien de la fiche
        self.motif_refus_public = conf["motif_refus_public"]
        self.attributs = conf["attributs"]
        self.groupes = conf.get("groupes", {})     # groupe Keycloak -> code du service
        # Base juridique acceptée PAR SERVICE : {service: {"consentement": true, "base_legale": [références]}}
        self.bases = conf.get("bases") or {}
        for service, modes in self.bases.items():
            if not isinstance(modes, dict) or set(modes) - {"consentement", "base_legale"} or (
                    "consentement" in modes and type(modes["consentement"]) is not bool) or not all(
                    isinstance(r, str) and r.strip() for r in modes.get("base_legale", []) or []):
                raise ValueError(f"{chemin.name} : bases.{service} mal formé (consentement: true, "
                                 "base_legale: [références de textes])")
        # Personne absente du registre : « refus » (par défaut) ou « vierge » (casier réel : une personne jamais
        # condamnée n'y figure pas). Avec « vierge », le MÉDIATEUR vérifie d'abord à l'état civil que la
        # personne existe : sinon, un identifiant inventé obtiendrait « casier vierge ».
        self.absence = conf.get("absence", "refus")
        if self.absence not in ("refus", "vierge"):
            raise ValueError(f"{chemin.name} : absence doit valoir « refus » ou « vierge »")
        if self.absence == "vierge" and any(r["regle"] not in ("nombre_nul", "contient") for r in self.attributs.values()):
            raise ValueError(f"{chemin.name} : « absence: vierge » n'a de sens que pour les règles nombre_nul et contient")
        # Format(s) des dates du registre (ex. "%d/%m/%Y" ou une liste) ; absent : ISO (2001-03-14, 2008-11, 2004)
        self.format_date = conf.get("format_date")
        # Fichier : lu une fois au démarrage (illisible -> le registre refuse de démarrer).
        # API du jury : interrogée à chaque demande (voir fiches()).
        self.source = conf["source"]
        self.lignes = None if self.source["type"] == "api" else lire_source(self.source)
        # Empreinte du fichier lu (écrite dans les logs au démarrage) : on sait quelle version des données a servi
        self.empreinte_source = "" if self.lignes is None else empreinte_fichier(self.source["chemin"])

    def valeur(self, ligne: dict, nom: str) -> str:
        return (ligne.get(self.champs[nom]) or "").strip()

    def morceau_de_cle(self, valeur: str) -> str:
        """Forme comparable d'un morceau de clé composée : date -> 2001-03-14, sinon texte sans accents ni
        majuscules. Une date incomplète (« vers 1990 ») reste du texte : elle ne correspond à aucune date tapée."""
        try:
            debut, fin = bornes_de_naissance(valeur, self.format_date)
            if debut == fin:
                return debut.isoformat()
        except Refus:
            pass
        return normaliser_texte(valeur)

    def cle_de_la_fiche(self, ligne: dict) -> list[str] | None:
        morceaux = [(ligne.get(c) or "").strip() for c in self.identite]
        return None if not all(morceaux) else [self.morceau_de_cle(m) for m in morceaux]   # case vide : jamais

    def fiches(self, sujet_ref: str) -> list[dict]:
        # API : peut lever SourceIndisponible (registre indisponible, rien n'est deviné ni signé)
        lignes = interroger_api(self.source, sujet_ref) if self.lignes is None else self.lignes
        if not self.cle_composee:
            # Même avec une API, on ne garde que les fiches dont l'identifiant est EXACTEMENT celui demandé
            return [l for l in lignes if (l.get(self.identite) or "").strip() == sujet_ref]
        morceaux = [m.strip() for m in sujet_ref.split(self.separateur_cle)]
        if len(morceaux) != len(self.identite) or not all(morceaux):
            return []                                       # identifiant mal formé : introuvable
        cle = [self.morceau_de_cle(m) for m in morceaux]
        return [l for l in lignes if self.cle_de_la_fiche(l) == cle]

    def trouver(self, sujet_ref: str) -> dict:
        fiches = self.fiches(sujet_ref)
        if not fiches:
            raise Refus("introuvable")
        if len(fiches) > 1:
            raise Refus("identité ambiguë : homonymes (plusieurs fiches pour la même clé)" if self.cle_composee
                        else "identité ambiguë : plusieurs fiches pour cet identifiant")
        return fiches[0]

    def autorise(self, attribut: str, service: str) -> bool:
        """Double clé : le registre décide LUI-MÊME quels services peuvent demander quel attribut
        (« services » de l'attribut), même si le médiateur a laissé passer la demande."""
        return service in self.attributs.get(attribut, {}).get("services", [])

    def base_autorisee(self, service: str, base: str, texte: str) -> bool:
        """Double clé sur le MODE : consentement seulement s'il est déclaré pour ce service ; base légale seulement
        si le texte cité contient une référence que le registre a déclarée pour ce service."""
        modes = self.bases.get(service) or {}
        if base == "consentement":
            return modes.get("consentement") is True
        if base == "base_legale":
            return any(reference in (texte or "") for reference in modes.get("base_legale") or [])
        return False                                     # base absente ou inconnue : on ne devine pas

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
            return {regle["claim"]: self.egal(valeur, regle)}
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

    @staticmethod
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
        ages = {str(mini): age_minimum_atteint(naissance, mini, reference, self.format_date)}
        if maxi is not None:
            ages[str(maxi + 1)] = age_minimum_atteint(naissance, maxi + 1, reference, self.format_date)
        return {regle["claim"]: ages, "date_reference": reference.isoformat()}

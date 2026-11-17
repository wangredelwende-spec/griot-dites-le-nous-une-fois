"""Lecture d'un registre décrite par un fichier YAML (registres/adaptateurs/<registre>.yaml).

On branche un nouveau registre en écrivant un fichier YAML, sans changer ce code.
Règle d'or : si la donnée ne permet pas de conclure, on REFUSE avec un motif ; on ne devine jamais.

Partage des rôles : ce fichier RETROUVE la fiche (source, clé d'identité, homonymes, décès) et applique la double
clé ; le CALCUL de l'attribut minimal vient de la couche « consentement et minimisation »
(consentement-minimisation/regles_attributs/, copié dans l'image du registre : la fiche ne sort jamais d'ici).
"""
from datetime import date
from pathlib import Path

import yaml

# Couche consentement et minimisation, copiée dans l'image du registre (Refus : repris par main.py et les tests)
from regles_attributs import Refus, bornes_de_naissance, normaliser, normaliser_texte
from regles_attributs import calculer as calculer_regle

from .sources import (SourceIndisponible, empreinte_fichier, interroger_api,  # noqa: F401 (SourceIndisponible : main.py)
                      lire_source)


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

    def champs_utiles(self, fiche: dict, noms: list[str]) -> dict:
        """Règle « champs » (identité, naissance et filiation) : les cases listées dans l'adaptateur, et RIEN d'autre.
        Case vide : refus (on ne devine pas). Date de naissance : complète exigée (« né vers 1990 » : refus)."""
        utiles = {}
        for nom in noms:
            valeur = self.valeur(fiche, nom)
            if not valeur:
                raise Refus(f"donnée insuffisante : « {nom} » vide")
            if nom == "date_naissance":
                debut, fin = bornes_de_naissance(valeur, self.format_date)
                if debut != fin:
                    raise Refus("donnée insuffisante : date de naissance incomplète")
                valeur = debut.isoformat()
            utiles[nom] = valeur
        return utiles

    def calculer(self, attribut: str, sujet_ref: str, parametres: dict | None = None) -> dict:
        """Renvoie UNIQUEMENT la réponse minimale, par exemple {"nationalite_bf": True}."""
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
        if regle["regle"] == "champs":
            return {regle["claim"]: self.champs_utiles(fiche, regle["champs"])}
        # Seule la case utile est lue ; le calcul (couche consentement et minimisation) ne voit qu'elle
        valeur = "" if regle["regle"] == "existe" else self.valeur(fiche, regle["champ"])
        return calculer_regle(regle, valeur, parametres, self.format_date)

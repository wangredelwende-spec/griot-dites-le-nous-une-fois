"""Catalogue des démarches : chargé et VALIDÉ au démarrage, puis à chaque modification du fichier.
Aucune démarche n'est écrite dans le code.

Trois sources, toutes en lecture seule :
- consentement-minimisation/catalogue/annuaire.yaml  : les services demandeurs et les registres ;
- consentement-minimisation/catalogue/attributs.yaml : les attributs PERMIS (majeur, nationalite_bf…), pour quels services,
  et comment la passerelle les calcule depuis la fiche du registre (noms de champs logiques ; ceux du contrat sont
  dans correspondance.yaml) ;
- consentement-minimisation/catalogue/demarches.yaml : les démarches (service, finalité, base, attributs et leurs paramètres).
Un catalogue invalide est REFUSÉ avec toutes ses raisons : on ne devine pas une règle manquante. Le médiateur
garde alors le dernier catalogue valide et continue de tourner (main.surveiller_catalogue).
"""
import hashlib
import re
from datetime import date, datetime, timezone

import yaml

from app.config import CATALOGUE, CONTRAT      # chemins de la passerelle (même processus)

BASES = ("consentement", "base_legale")
AUJOURDHUI = "aujourd'hui"


class CatalogueInvalide(Exception):
    pass


def parametres_invalides(regle: str, parametres: dict) -> str:
    """Renvoie le problème trouvé dans les paramètres d'un attribut, ou « » s'ils sont corrects."""
    if regle != "age_entre":
        return "cet attribut n'accepte aucun paramètre" if parametres else ""
    if set(parametres) - {"min", "max", "date_reference"}:
        return "paramètres inconnus (attendus : min, max, date_reference)"
    mini, maxi, reference = parametres.get("min"), parametres.get("max"), parametres.get("date_reference")
    if type(mini) is not int or not 0 <= mini <= 150:
        return "« min » (âge minimal, nombre entier) est obligatoire"
    if maxi is not None and (type(maxi) is not int or not mini <= maxi <= 150):
        return "« max » doit être un nombre entier supérieur ou égal à « min »"
    if reference != AUJOURDHUI and not isinstance(reference, date):
        try:
            date.fromisoformat(str(reference))
        except ValueError:
            return "« date_reference » doit être une date (2026-12-31) ou « aujourd'hui »"
    return ""


def valider(demarches: dict, services: dict, attributs: dict) -> list[str]:
    """Liste TOUTES les erreurs du catalogue (liste vide = catalogue valide)."""
    erreurs = []
    if not demarches:
        erreurs.append("aucune démarche dans le catalogue")
    for code, d in (demarches or {}).items():
        if not isinstance(d, dict):
            erreurs.append(f"démarche « {code} » : mal formée")
            continue
        problemes = []
        if not d.get("libelle"):
            problemes.append("libellé manquant")
        if not d.get("finalite"):
            problemes.append("finalité manquante")
        # Traductions facultatives de la finalité : finalite_mos (mooré)… Si le champ est là, il doit être rempli.
        for cle, valeur in d.items():
            if cle.startswith("finalite_") and not (isinstance(valeur, str) and valeur.strip()):
                problemes.append(f"« {cle} » doit être un texte non vide (ou être retiré)")
        if d.get("base") not in BASES:
            problemes.append("base manquante ou inconnue (consentement | base_legale)")
        if d.get("base") == "consentement" and (type(d.get("duree_accord_heures")) is not int
                                                or not 1 <= d["duree_accord_heures"] <= 8760):
            problemes.append("consentement sans « duree_accord_heures » (nombre entier d'heures, 1 à 8760)")
        if d.get("base") == "base_legale" and not d.get("texte"):
            problemes.append("base légale sans texte cité")
        if not d.get("services") or any(s not in services for s in d["services"]):
            problemes.append("services manquants ou inconnus de l'annuaire")
        demandes = d.get("attributs") or []
        if not demandes:
            problemes.append("aucun attribut demandé")
        codes = []
        for a in demandes:
            nom = a.get("attribut") if isinstance(a, dict) else None
            if nom not in attributs:
                problemes.append(f"attribut inconnu « {nom} » (aucun registre ne le déclare)")
                continue
            codes.append(nom)
            if not a.get("libelle"):
                problemes.append(f"attribut « {nom} » sans libellé")
            if probleme := parametres_invalides(attributs[nom]["regle"], a.get("parametres") or {}):
                problemes.append(f"attribut « {nom} » : {probleme}")
            if type(a.get("attendu", True)) is not bool:
                problemes.append(f"attribut « {nom} » : « attendu » doit valoir true ou false")
            if not isinstance(a.get("si_non", ""), str):
                problemes.append(f"attribut « {nom} » : « si_non » doit être un texte")
        if len(codes) != len(set(codes)):
            problemes.append("un même attribut est demandé deux fois")
        erreurs += [f"démarche « {code} » : {p}" for p in problemes]
    return erreurs


def charger(brut: bytes | None = None) -> dict:
    """Charge et valide le catalogue. « brut » : contenu de demarches.yaml déjà lu (sinon, lu sur le disque).
    Lève CatalogueInvalide avec TOUTES les raisons trouvées."""
    try:
        annuaire = yaml.safe_load((CATALOGUE / "annuaire.yaml").read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise CatalogueInvalide(f"  - annuaire.yaml illisible : {e}")
    if brut is None:
        brut = (CATALOGUE / "demarches.yaml").read_bytes()
    try:
        demarches = (yaml.safe_load(brut) or {}).get("demarches") or {}
    except (yaml.YAMLError, AttributeError) as e:
        raise CatalogueInvalide(f"  - demarches.yaml illisible (YAML cassé) : {str(e)[:300]}")
    if not isinstance(demarches, dict):
        raise CatalogueInvalide("  - demarches.yaml : « demarches » doit contenir des blocs nommés")

    # Attributs permis (attributs.yaml) : chacun dit quel registre le fournit, comment le calculer, pour quels services
    try:
        declares = (yaml.safe_load((CATALOGUE / "attributs.yaml").read_text(encoding="utf-8")) or {}).get("attributs") or {}
    except (OSError, yaml.YAMLError) as e:
        raise CatalogueInvalide(f"  - attributs.yaml illisible : {str(e)[:300]}")
    attributs = {}
    problemes_registres = []
    for code, a in declares.items():
        if a.get("registre") not in annuaire["registres"]:
            problemes_registres.append(f"attribut « {code} » : registre « {a.get('registre')} » absent de l'annuaire")
            continue
        attributs[code] = {"registre": a["registre"], "regle": a["regle"], "champ": a.get("champ"),
                           "valeur": a.get("valeur"), "services": a.get("services", []),
                           "champs": a.get("champs") or []}      # règle « champs » : cases renvoyées, rien d'autre
    # Chaque registre de l'annuaire doit avoir sa route DANS LE CONTRAT (le contrat se remplace par configuration)
    try:
        routes = (yaml.safe_load(CONTRAT.read_text(encoding="utf-8")) or {}).get("paths") or {}
    except (OSError, yaml.YAMLError) as e:
        raise CatalogueInvalide(f"  - contrat illisible ({CONTRAT}) : {str(e)[:300]}")
    for code, r in annuaire["registres"].items():
        if r.get("chemin") not in routes:
            problemes_registres.append(f"registre « {code} » : route « {r.get('chemin')} » absente du contrat")
    absence_vierge = set()          # (ancien réglage du casier simulé, désactivé : un citoyen inconnu = 404 = refus)

    identifiant = annuaire.get("identifiant_usager") or {"format": r"^[A-Za-z0-9-]{1,64}$", "exemple": "BF-0001"}
    erreurs = problemes_registres + valider(demarches, annuaire["services"], attributs)
    try:
        if not re.fullmatch(identifiant["format"], str(identifiant["exemple"])):
            erreurs.append("annuaire : l'exemple d'identifiant ne respecte pas son propre format")
    except (re.error, KeyError, TypeError) as e:
        erreurs.append(f"annuaire : format d'identifiant illisible ({e})")
    if erreurs:
        raise CatalogueInvalide("\n".join(f"  - {e}" for e in erreurs))

    # Attributs permis (services ET paramètres) : une démarche qui demanderait ce que son service n'a pas le droit
    # d'obtenir est refusée dès le chargement, au lieu d'apparaître au guichet puis d'échouer à chaque demande.
    for code, d in demarches.items():
        for a in d["attributs"]:
            a["parametres"] = {k: v.isoformat() if isinstance(v, date) else v
                               for k, v in (a.get("parametres") or {}).items()}
            autorisations = attributs[a["attribut"]]["services"]
            registre = attributs[a["attribut"]]["registre"]
            for service in d["services"]:
                if service not in autorisations:
                    erreurs.append(f"démarche « {code} » : attributs.yaml n'autorise pas {service} "
                                   f"à demander « {a['attribut']} » (double clé)")
                elif isinstance(autorisations, dict) and not any(
                        comparable(p) == comparable(a["parametres"]) for p in autorisations[service] or []):
                    erreurs.append(f"démarche « {code} » : attributs.yaml n'autorise pas ces paramètres "
                                   f"pour {service} (seuil ou date non déclaré, double clé)")
    erreurs = list(dict.fromkeys(erreurs))          # une même erreur par registre, pas une par attribut
    if erreurs:
        raise CatalogueInvalide("\n".join(f"  - {e}" for e in erreurs))
    return {"services": annuaire["services"], "registres": annuaire["registres"], "attributs": attributs,
            "demarches": demarches, "absence_vierge": absence_vierge,
            "identifiant": identifiant,
            "empreinte": hashlib.sha256(brut).hexdigest()}


def base_declaree(modes: dict, base: str, texte: str) -> bool:
    """Même règle que le registre (Adaptateur.base_autorisee) : consentement déclaré pour ce service, ou base
    légale dont le texte cité contient une référence déclarée pour ce service."""
    if base == "consentement":
        return modes.get("consentement") is True
    return base == "base_legale" and any(r in (texte or "") for r in modes.get("base_legale") or [])


def comparable(parametres: dict) -> dict:
    reference = parametres.get("date_reference")
    return {"min": parametres.get("min"), "max": parametres.get("max"),
            "date_reference": reference.isoformat() if isinstance(reference, date) else str(reference)}


def resoudre(parametres: dict) -> dict:
    """« aujourd'hui » devient la date du jour (UTC = heure de Ouagadougou) au moment de la demande."""
    if parametres.get("date_reference") == AUJOURDHUI:
        return parametres | {"date_reference": datetime.now(timezone.utc).date().isoformat()}
    return parametres

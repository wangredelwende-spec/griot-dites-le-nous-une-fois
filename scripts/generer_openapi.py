"""Écrit le contrat d'API (openapi.yaml) de chaque couche, GÉNÉRÉ depuis le code : il ne peut pas mentir.

    .venv\\Scripts\\python scripts\\generer_openapi.py                       # réécrit les 6 fichiers
    .venv\\Scripts\\python scripts\\generer_openapi.py --couche registres -   # affiche un seul contrat

Le test tests/test_openapi.py vérifie que chaque openapi.yaml commité est exactement celui que le code produit :
une route ajoutée ou changée sans régénérer le contrat fait échouer les tests.

Aucun conteneur n'est lancé : chaque application est importée hors Docker, avec des secrets et des dossiers
temporaires (comme dans les tests), dans un processus Python séparé par couche (elles ont toutes un paquet « app »).
La passerelle d'échange fait tourner trois couches dans un seul processus : ses routes portent l'étiquette de
leur couche, et chaque contrat ne garde que les siennes.
"""
import argparse
import contextlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]

# couche -> (fichier écrit, titre, description). Vocabulaire du sujet.
COUCHES = {
    "registres": ("registres/openapi.yaml", "Registres (état civil, nationalité, casier)",
                  "Chaque registre expose la fiche d'un citoyen par son identifiant (404 si inconnu), selon le contrat "
                  "commun de nos registres (registres/contrat/contrat-registres.yaml). "
                  "Appelé par la passerelle d'échange seulement (réseau « registres »), jamais publié."),
    "passerelle": ("passerelle/openapi.yaml", "Passerelle d'échange",
                   "Fait circuler les pièces entre administrations : demande d'un agent (jeton Keycloak), appel des "
                   "registres en parallèle avec délai, validation des réponses contre le contrat, minimisation, remise au guichet. "
                   "Réseau interne seulement, jamais publiée par Caddy."),
    "consentement-minimisation": ("consentement-minimisation/openapi.yaml", "Consentement et minimisation",
                                  "Ce que l'usager voit AVANT l'envoi (aperçu exact) et ce qu'il décide : confirmer, "
                                  "refuser, retirer un accord. Appelé par les écrans de l'espace usager avec le secret "
                                  "de leur canal (en-tête X-Cle-Canal)."),
    "journal": ("journal/openapi.yaml", "Journal de traçabilité",
                "Qui a consulté quoi, quand et pourquoi (jamais la valeur), et vérification de la chaîne "
                "d'empreintes. Historique lu par l'espace usager ; vérification par le contrôleur (lecture seule)."),
    "espace-usager": ("espace-usager/openapi.yaml", "Espace usager (USSD simulé et portail web)",
                      "Écrans du citoyen, rendus côté serveur, sans JavaScript : USSD *226# à la racine, portail web "
                      "sous /portail. Formulaires HTML ; ils n'utilisent que l'API de la couche consentement et "
                      "minimisation et l'historique du journal."),
    "guichet": ("guichet-agent/openapi.yaml", "Guichet agent",
                "Écran de l'agent (Keycloak : mot de passe + TOTP) : choix de la démarche, envoi, résultat signé "
                "et revérifié ; page /controle en lecture seule pour le rôle controleur. Formulaires HTML."),
}
# Étiquettes des routes de la passerelle (passerelle/app/main.py et consentement/usager.py)
ETIQUETTES = {"passerelle": "passerelle d'échange", "consentement-minimisation": "consentement et minimisation",
              "journal": "journal de traçabilité"}


def charger(nom: str, fichier: Path):
    """Charge un fichier Python sous un nom choisi (plusieurs applications s'appellent « app »)."""
    spec = importlib.util.spec_from_file_location(nom, fichier,
                                                  submodule_search_locations=[str(fichier.parent)]
                                                  if fichier.name == "__init__.py" else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


def preparer_dossiers() -> Path:
    """Secrets et dossiers de travail jetables (jamais les vrais secrets de .env)."""
    tmp = Path(tempfile.mkdtemp(prefix="griot-openapi-"))
    for dossier in ("secrets", "donnees", "publiques", "cles", "publique", "trace"):
        (tmp / dossier).mkdir()
    for secret in ("sujet_hmac", "canal_usager", "canal_web", "guichet_oidc"):
        (tmp / "secrets" / secret).write_text("secret-jetable-pour-openapi")
    os.environ.update(GRIOT_SECRETS=str(tmp / "secrets"), GRIOT_DONNEES=str(tmp / "donnees"),
                      GRIOT_PUBLIQUES=str(tmp / "publiques"),
                      GRIOT_CATALOGUE=str(RACINE / "consentement-minimisation/catalogue"),
                      GRIOT_ADAPTATEURS=str(RACINE / "registres/adaptateurs"),
                      GRIOT_CONTRAT=str(RACINE / "registres/contrat/contrat-registres.yaml"),
                      GRIOT_VERIFIER=str(RACINE / "journal/verifier.py"))
    return tmp


def routes_de(couche: str) -> list:
    """Routes FastAPI de la couche (importée ici, hors Docker)."""
    tmp = preparer_dossiers()
    if couche == "registres":
        adaptateur = tmp / "etat-civil.yaml"
        adaptateur.write_text((RACINE / "registres/adaptateurs/etat-civil.yaml").read_text(encoding="utf-8").replace(
            "/donnees/", (RACINE / "registres/donnees_fictives").as_posix() + "/"), encoding="utf-8")
        os.environ.update(ADAPTATEUR=str(adaptateur), CLES=str(tmp / "cles"), PUBLIQUE=str(tmp / "publique"),
                          TRACE=str(tmp / "trace"), PANNE=str(tmp / "panne"))
        sys.path.insert(0, str(RACINE / "consentement-minimisation"))
        charger("app", RACINE / "registres/app/__init__.py")
        return charger("app.main", RACINE / "registres/app/main.py").app.routes
    if couche in ETIQUETTES:
        for dossier in ("passerelle", "consentement-minimisation", "journal"):
            sys.path.insert(0, str(RACINE / dossier))
        from app import main      # passerelle/app (le même processus que dans le conteneur)
        return main.app.routes    # toutes les couches ; garder_la_couche() ne laisse que les siennes
    if couche == "espace-usager":
        os.environ.update(ABONNES=str(RACINE / "espace-usager/ussd/abonnes.yaml"))
        os.environ["TEXTES"] = str(RACINE / "traduction-moore/phrases-ussd.csv")
        ussd = charger("ussd_app", RACINE / "espace-usager/ussd/app/main.py")
        os.environ["TEXTES"] = str(RACINE / "traduction-moore/phrases-portail.csv")
        portail = charger("portail_app", RACINE / "espace-usager/portail/app/main.py")
        return ussd.app.routes + portail.app.routes       # /… pour l'USSD, /portail/… pour le portail
    if couche == "guichet":
        # Le guichet lit des chemins fixes (/run/secrets, /catalogue…) : on les remplace AVANT d'importer main
        os.chdir(RACINE / "guichet-agent")                     # StaticFiles et gabarits : chemins relatifs à guichet-agent/
        sys.path.insert(0, str(RACINE / "guichet-agent"))
        from app import config
        config.lire_secret = lambda nom: (tmp / "secrets" / nom).read_text().strip()
        config.CATALOGUE = RACINE / "consentement-minimisation/catalogue"
        config.ADAPTATEURS = RACINE / "registres/adaptateurs"
        from app import main
        return main.app.routes
    raise SystemExit(f"couche inconnue : {couche}")


def garder_la_couche(schema: dict, etiquette: str) -> dict:
    """Passerelle : ne garde que les opérations portant l'étiquette de la couche, et les schémas qu'elles citent."""
    chemins = {}
    for chemin, operations in schema["paths"].items():
        gardees = {m: op for m, op in operations.items() if etiquette in op.get("tags", [])}
        if gardees:
            chemins[chemin] = gardees
    schema["paths"] = chemins
    tous = schema.get("components", {}).get("schemas", {})
    cites, a_voir = set(), [chemins]
    while a_voir:                                     # références « $ref », de proche en proche
        objet = a_voir.pop()
        if isinstance(objet, list):
            a_voir.extend(objet)
        elif isinstance(objet, dict):
            ref = objet.get("$ref", "")
            nom = ref.removeprefix("#/components/schemas/")
            if ref and nom in tous and nom not in cites:
                cites.add(nom)
                a_voir.append(tous[nom])
            a_voir.extend(objet.values())
    if tous:
        schema["components"]["schemas"] = {n: s for n, s in tous.items() if n in cites}
        if not schema["components"]["schemas"]:
            del schema["components"]
    return schema


def contrat(couche: str) -> str:
    from fastapi.openapi.utils import get_openapi
    _, titre, description = COUCHES[couche]
    if couche == "registres":
        # Le contrat des registres EST leur OpenAPI : on le publie tel quel (c'est lui, pas le code, qui fait foi)
        schema = yaml.safe_load((RACINE / "registres/contrat/contrat-registres.yaml").read_text(encoding="utf-8"))
        schema["info"] = {"title": f"Griot : {titre}", "version": "1.0", "description": description}
        entete = ("# Contrat d'API de la couche « Registres ». GÉNÉRÉ par scripts/generer_openapi.py à partir de\n"
                  "# registres/contrat/contrat-registres.yaml : ne pas modifier à la main.\n")
        return entete + yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=120)
    schema = get_openapi(title=f"Griot : {titre}", version="1.0", description=description, routes=routes_de(couche))
    if couche in ETIQUETTES:
        schema = garder_la_couche(schema, ETIQUETTES[couche])
    entete = (f"# Contrat d'API de la couche « {titre} ». GÉNÉRÉ par scripts/generer_openapi.py : ne pas modifier\n"
              "# à la main (tests/test_openapi.py vérifie qu'il correspond au code).\n")
    return entete + yaml.safe_dump(schema, allow_unicode=True, sort_keys=False, width=120)


def generer_dans_un_processus(couche: str) -> str:
    """Chaque couche dans un processus neuf : elles ont toutes un paquet nommé « app »."""
    r = subprocess.run([sys.executable, __file__, "--couche", couche, "-"], capture_output=True, cwd=RACINE)
    if r.returncode != 0:
        raise RuntimeError(f"{couche} : {r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8")


if __name__ == "__main__":
    lecteur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lecteur.add_argument("--couche", choices=COUCHES)
    lecteur.add_argument("sortie", nargs="?", help="« - » : afficher au lieu d'écrire le fichier")
    args = lecteur.parse_args()
    if args.couche and args.sortie == "-":
        with contextlib.redirect_stdout(sys.stderr):     # messages de démarrage des applications : pas dans le contrat
            texte = contrat(args.couche)
        sys.stdout.buffer.write(texte.encode("utf-8"))
        sys.exit(0)
    for code in [args.couche] if args.couche else COUCHES:
        chemin = RACINE / COUCHES[code][0]
        chemin.write_bytes(generer_dans_un_processus(code).encode("utf-8"))
        print(f"écrit : {chemin.relative_to(RACINE)}")

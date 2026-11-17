"""Préparation des tests : dossiers temporaires, secrets de test, faux registres selon le contrat.

La passerelle est testée SANS Docker : les registres sont remplacés par respx (faux serveur HTTP) qui répondent
comme le contrat (fiche JSON d'un citoyen, 404 s'il est inconnu). Le contrat et la liste des citoyens sont ceux du dépôt
(PROVISOIRES) : les remplacer par ceux du jury et relancer les tests suffit (README.md).
"""
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RACINE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="griot-tests-"))
for dossier in ("secrets", "donnees", "publiques"):
    (TMP / dossier).mkdir()
(TMP / "secrets/sujet_hmac").write_text("secret-de-test-pseudonyme")
(TMP / "secrets/canal_usager").write_text("secret-de-test-canal")
(TMP / "secrets/canal_web").write_text("secret-de-test-canal-web")
os.environ.update(GRIOT_SECRETS=str(TMP / "secrets"), GRIOT_DONNEES=str(TMP / "donnees"),
                  GRIOT_PUBLIQUES=str(TMP / "publiques"), GRIOT_CATALOGUE=str(RACINE / "consentement-minimisation/catalogue"),
                  GRIOT_ADAPTATEURS=str(RACINE / "registres/adaptateurs"),
                  GRIOT_CONTRAT=os.environ.get("GRIOT_CONTRAT", str(RACINE / "registres/contrat/contrat-provisoire.yaml")),
                  LIMITE_PAR_CITOYEN="1000", LIMITE_SUJETS="1000",   # des tests dédiés baissent les limites
                  DELAI_REGISTRE="0.5", GRIOT_VERIFIER=str(RACINE / "journal/verifier.py"))

CLE_REGISTRE = Ed25519PrivateKey.generate()
# Pour simplifier, les trois faux registres signent avec la même clé de test
for registre in ("etat-civil", "nationalite", "casier"):
    (TMP / "publiques" / registre).mkdir()
    (TMP / "publiques" / registre / "cle.pem").write_bytes(CLE_REGISTRE.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
# Routes des registres (expressions régulières pour respx : « respx.get(url__regex=URL_REGISTRE) »)
ANNUAIRE_DE_TEST = yaml.safe_load((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_text(encoding="utf-8"))


def _regex_de(registre: str) -> str:
    r = ANNUAIRE_DE_TEST["registres"][registre]
    return "^" + r["url"].replace(".", r"\.") + r["chemin"].replace(".", r"\.").replace("{id}", ".+")


URL_REGISTRE, URL_NATIONALITE, URL_CASIER = (_regex_de(r) for r in ("etat-civil", "nationalite", "casier"))
CANAL = {"X-Cle-Canal": "secret-de-test-canal"}
CHEMIN_JOURNAL = TMP / "donnees/mediateur.sqlite3"

# Le registre est enregistré sous le nom de paquet « registre_app » (le médiateur occupe déjà le nom « app »)
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("registre_app", RACINE / "registres/app/__init__.py",
                                               submodule_search_locations=[str(RACINE / "registres/app")])
sys.modules["registre_app"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sys.modules["registre_app"])

# Même processus que dans le conteneur : passerelle (paquet app) + couches consentement et journal
for _couche in ("passerelle", "consentement-minimisation", "journal"):
    sys.path.insert(0, str((RACINE / _couche).resolve()))
from app import main as mediateur  # noqa: E402
from app.agents import agent_connecte  # noqa: E402


# Démarches DE TEST (jamais dans le catalogue du dépôt) : les scénarios d'un seul attribut, ou à consentement, que
# les trois démarches actives ne permettent pas. Ajoutées au catalogue en mémoire, après son chargement.
DEMARCHES_DE_TEST = {
    "test-majorite": {"libelle": "Vérifier la majorité (test)", "services": ["direction-concours"],
                      "finalite": "vérification de la majorité civile", "base": "base_legale",
                      "texte": "Code des personnes et de la famille, loi n°012-2025/ALT (majorité civile à 18 ans accomplis)",
                      "attributs": [{"attribut": "majeur", "parametres": {"min": 18, "date_reference": "aujourd'hui"},
                                     "libelle": "majeur (18 ans accomplis)"}]},
    "test-nationalite": {"libelle": "Nationalité (test, consentement)", "services": ["cefore"],
                         "finalite": "vérification de la nationalité", "base": "consentement", "duree_accord_heures": 24,
                         "attributs": [{"attribut": "nationalite_bf", "libelle": "nationalité burkinabè"}]},
}
for _d in DEMARCHES_DE_TEST.values():
    for _a in _d["attributs"]:
        _a.setdefault("parametres", {})          # le chargeur du catalogue le fait pour les vraies démarches
mediateur.CAT["demarches"].update(DEMARCHES_DE_TEST)

# --- Faux registres selon le contrat (PROVISOIRE) ---

# Le contrat et la liste des citoyens : ceux du dépôt (PROVISOIRES), ou ceux désignés par GRIOT_CONTRAT / GRIOT_CITOYENS
CHEMIN_CONTRAT = Path(os.environ["GRIOT_CONTRAT"])
CHEMIN_CITOYENS = Path(os.environ.get("GRIOT_CITOYENS", RACINE / "registres/donnees/citoyens-provisoires.yaml"))
CONTRAT_DE_TEST = yaml.safe_load(CHEMIN_CONTRAT.read_text(encoding="utf-8"))
CITOYENS_DE_TEST = {str(c["id"]): c for c in yaml.safe_load(CHEMIN_CITOYENS.read_text(encoding="utf-8"))["citoyens"]}
def champs_de_la_route(chemin: str) -> list[str]:
    """Champs de la réponse 200 d'une route du contrat (les « $ref » locaux sont résolus)."""
    schema = CONTRAT_DE_TEST["paths"][chemin]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    if "$ref" in schema:
        schema = CONTRAT_DE_TEST["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return list(schema["properties"])


CHAMPS_PAR_REGISTRE = {registre: champs_de_la_route(r["chemin"]) for registre, r in ANNUAIRE_DE_TEST["registres"].items()}


def fiche_de(sujet: str, registre: str, **modifs) -> dict:
    """La fiche que renverrait le registre : celle du citoyen s'il est dans la liste, sinon la fiche de BF-0001 au nom de
    ce sujet (les tests utilisent des identifiants quelconques : CUR-1, BF-0020…). « modifs » : champs remplacés ;
    une valeur « ... » retire le champ ; un champ inconnu du contrat est ajouté (réponse non conforme)."""
    source = CITOYENS_DE_TEST.get(sujet) or CITOYENS_DE_TEST["BF-0001"] | {"id": sujet}
    fiche = {champ: source.get(champ) for champ in CHAMPS_PAR_REGISTRE[registre]} | modifs
    return {c: v for c, v in fiche.items() if v is not ...}


def registre_qui_repond(registre: str, **modifs):
    """Faux registre pour respx : renvoie la fiche du citoyen demandé (identifiant = dernier morceau de l'adresse)."""
    import httpx

    def repondre(requete):
        return httpx.Response(200, json=fiche_de(requete.url.path.rsplit("/", 1)[1], registre, **modifs))
    return repondre


_REGISTRES_REELS = {}


def registres_reels() -> dict:
    """Les VRAIS registres simulés (registres/app/main.py, selon le contrat), un par route du contrat, en mémoire :
    {registre: TestClient}. Chaque instance a sa propre panne (module.PANNE_DE_TEST = normal | lent | eteint | non_conforme)."""
    if not _REGISTRES_REELS:
        for registre, r in ANNUAIRE_DE_TEST["registres"].items():
            chemin = r["chemin"]
            os.environ.update(GRIOT_CONTRAT=str(CHEMIN_CONTRAT), GRIOT_CITOYENS=str(CHEMIN_CITOYENS), REGISTRE_CHEMIN=chemin)
            nom = "registre_reel_" + registre.replace("-", "_")
            spec = importlib.util.spec_from_file_location(nom, RACINE / "registres/app/main.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.PANNE_DE_TEST = "normal"
            module.mode_de_panne = lambda m=module: m.PANNE_DE_TEST
            _REGISTRES_REELS[registre] = module
    return _REGISTRES_REELS


def brancher_les_registres_reels():
    """À appeler dans un test décoré par @respx.mock : les routes des registres sont servies par le vrai code."""
    import httpx
    import respx
    reels = registres_reels()

    def vers(registre):
        async def repondre(requete):
            # Transport ASGI de httpx : appelle le code du registre sans réseau (et sans repasser par respx)
            transport = httpx.ASGITransport(app=reels[registre].app)
            async with httpx.AsyncClient(transport=transport, base_url="http://registre") as c:
                r = await c.get(requete.url.path)
            return httpx.Response(r.status_code, json=r.json())
        return repondre
    for registre, url in (("etat-civil", URL_REGISTRE), ("nationalite", URL_NATIONALITE), ("casier", URL_CASIER)):
        respx.get(url__regex=url).mock(side_effect=vers(registre))
    return reels


PREFIXES = {registre: r["chemin"].split("{id}")[0] for registre, r in ANNUAIRE_DE_TEST["registres"].items()}


def registre_conforme(**modifs):
    """Faux registre pour respx, quelle que soit la route : la fiche conforme au contrat (champs de « modifs » remplacés)."""
    import httpx

    def repondre(requete):
        chemin = requete.url.path
        registre = next(r for r, prefixe in PREFIXES.items() if chemin.startswith(prefixe))
        return httpx.Response(200, json=fiche_de(chemin.rsplit("/", 1)[1], registre, **modifs))
    return repondre


def faux_registres(**modifs_par_registre):
    """Les trois registres répondent normalement (à utiliser dans un test décoré par @respx.mock)."""
    import respx
    return {registre: respx.get(url__regex=url).mock(side_effect=registre_qui_repond(registre, **modifs_par_registre.get(registre, {})))
            for registre, url in (("etat-civil", URL_REGISTRE), ("nationalite", URL_NATIONALITE), ("casier", URL_CASIER))}


# Adaptateur de l'état civil lisant le CSV du dépôt (au lieu de /donnees dans Docker)
ADAPTATEUR_TEST = TMP / "etat-civil.yaml"
ADAPTATEUR_TEST.write_text((RACINE / "registres/adaptateurs/etat-civil.yaml").read_text(encoding="utf-8").replace(
    "/donnees/etat_civil.csv", (RACINE / "registres/donnees_fictives/etat_civil.csv").as_posix()),
    encoding="utf-8")


JETON_AGENT = "jeton-keycloak-de-test"     # transmis tel quel aux registres (qui le vérifient eux-mêmes)
AGENTS = {
    "awa.ouedraogo": ["CEFORE – guichet des entreprises"],
    "issa.sawadogo": ["Direction des concours – ministère des Serviteurs du peuple"],
    "agent.curieux": ["CEFORE – guichet des entreprises"],
    "moussa.kone": ["Tribunal – certificats de nationalité"],
}


@pytest.fixture(autouse=True)
def accords_vides():
    """La base de test est partagée : un accord donné dans un test ne doit pas rendre immédiate la demande d'un autre."""
    with mediateur.VERROU:
        mediateur.base.execute("DELETE FROM accords")
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    agent = {"nom": "issa.sawadogo"}
    mediateur.app.dependency_overrides[agent_connecte] = lambda: {"nom": agent["nom"], "jeton": JETON_AGENT,
                                                                 "groupes": AGENTS[agent["nom"]]}
    with TestClient(mediateur.app) as c:
        c.agent = agent     # c.agent["nom"] = "awa.ouedraogo" pour changer d'agent
        yield c
    mediateur.app.dependency_overrides.clear()


FINALITES = {code: d["finalite"] for code, d in
             yaml.safe_load((RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8"))["demarches"].items()}
FINALITES.update({code: d["finalite"] for code, d in DEMARCHES_DE_TEST.items()})


def demande(demarche="test-majorite", sujet="BF-0001", **modifs) -> dict:
    d = {"id_demande": str(uuid.uuid4()), "demarche": demarche, "sujet_ref": sujet, "finalite": FINALITES[demarche]}
    d.update(modifs)
    return d

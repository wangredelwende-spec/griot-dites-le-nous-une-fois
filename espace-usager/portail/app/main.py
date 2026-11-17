"""Portail web usager (https://usager.griot.test/portail) : les trois écrans du *226#, dans un navigateur.

- Il passe UNIQUEMENT par l'API usager du médiateur (docs/API_USAGER.md), avec SON secret de canal
  (/run/secrets/canal_web) : le médiateur écrit donc « canal = web » au journal, sans croire le portail sur parole.
  Aucune règle ici, aucun accès aux registres ni au journal.
- Connexion : numéro + PIN, mêmes règles que l'USSD (même annuaire, blocage 5 minutes après 3 PIN faux).
- Rendu serveur, aucun JavaScript, aucune ressource externe : pages de quelques Ko pour un téléphone en 3G.
- Textes dans traduction-moore/phrases-portail.csv ; une langue n'est utilisée que si elle est complète.
- Conteneur séparé : « docker compose stop portail » l'arrête sans toucher à l'USSD ni au reste.
"""
import csv
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

ICI = Path(__file__).parent
MEDIATEUR = os.environ.get("MEDIATEUR", "http://mediateur:8000")
FICHIER_ABONNES = Path(os.environ.get("ABONNES", "/app/abonnes.yaml"))     # le même annuaire que l'USSD
FICHIER_TEXTES = Path(os.environ.get("TEXTES", "/app/phrases-portail.csv"))
SECRETS = Path(os.environ.get("GRIOT_SECRETS", "/run/secrets"))
# Cookie de session réservé à HTTPS (toujours dans Docker). « 0 » SEULEMENT pour la démonstration locale sans HTTPS
# (scripts/demo_locale.py).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"

RACINE = "/portail"      # Caddy envoie ici tout ce qui commence par /portail (le reste va à l'USSD)
ESSAIS_PIN = 3           # mêmes règles que l'USSD
BLOCAGE = 300            # 5 minutes de blocage après 3 PIN faux
DUREE_SESSION = 600      # déconnexion après 10 minutes sans activité
PAR_PAGE = 10            # lignes d'historique par page
# Événements montrés dans « Qui a consulté mes données » : les mêmes que l'USSD (les étapes internes sont omises)
EVENEMENTS = {"confirmation": "etat_confirmation", "remise": "etat_remise", "refus-usager": "etat_refuse",
              "expiration": "etat_expiration", "alerte": "etat_alerte", "retrait": "etat_retrait"}


def charger_textes(chemin: Path) -> dict[str, dict[str, str]]:
    """{code de langue: {clé: texte}} pour les langues COMPLÈTES seulement (le français l'est toujours)."""
    with open(chemin, encoding="utf-8-sig", newline="") as fichier:
        lecteur = csv.DictReader(fichier, delimiter=";")
        langues = [c for c in lecteur.fieldnames if c not in ("cle", "ecran")]
        lignes = list(lecteur)
    return {code: {l["cle"]: l[code].strip() for l in lignes}
            for code in langues if all((l[code] or "").strip() for l in lignes)}


ABONNES = yaml.safe_load(FICHIER_ABONNES.read_text(encoding="utf-8"))
TEXTES = charger_textes(FICHIER_TEXTES)
# Le français seulement pour l'instant : les noms des services et des attributs viennent du catalogue,
# écrit en français ; un écran « en mooré » en serait à moitié français (même règle qu'au sprint).
T = TEXTES["fr"]
SECRET_CANAL = (SECRETS / "canal_web").read_text().strip()

SESSIONS: dict[str, dict] = {}       # sessions en mémoire ; le cookie ne contient qu'un numéro aléatoire
ECHECS_PIN: dict[str, list] = {}     # numéro -> [nombre d'échecs, bloqué jusqu'à]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32), session_cookie="portail_session",
                   path=RACINE, https_only=COOKIE_SECURE, same_site="lax", max_age=3600)
app.mount(f"{RACINE}/static", StaticFiles(directory=ICI / "static"), name="static")
templates = Jinja2Templates(directory=ICI / "templates")


class MediateurInjoignable(Exception):
    pass


async def mediateur(methode: str, chemin: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(base_url=MEDIATEUR, timeout=5, headers={"X-Cle-Canal": SECRET_CANAL}) as client:
            r = await client.request(methode, chemin, **kwargs)
    except httpx.HTTPError as e:
        raise MediateurInjoignable from e
    if r.status_code >= 500 or r.status_code == 401:
        raise MediateurInjoignable
    return r


@app.exception_handler(MediateurInjoignable)
async def injoignable(request: Request, _):
    return page(request, "message.html", {"titre": T["indisponible_titre"], "texte": T["indisponible"]}, 503)


# --- Outils d'affichage ---

def format_recu(empreinte: str) -> str:
    """Reçu = 16 premiers caractères de l'empreinte, en 4 groupes : « 9035 47b3 1c2e 9f04 » (comme l'USSD)."""
    return " ".join(empreinte[i:i + 4] for i in range(0, 16, 4))


def date_ligne(ts: str) -> str:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m/%Y %Hh%M")


def heure(horodatage: float) -> str:
    """Heure de Ouagadougou = UTC."""
    return datetime.fromtimestamp(horodatage, timezone.utc).strftime("%Hh%M")


def page(request: Request, gabarit: str, contexte: dict, code: int = 200):
    s = session_de(request)
    return templates.TemplateResponse(request, gabarit, {"t": T, "csrf": jeton_csrf(request), "connecte": bool(s),
                                                         "racine": RACINE, **contexte}, status_code=code)


# --- Session, CSRF ---

def jeton_csrf(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def verifier_csrf(request: Request, jeton: str):
    attendu = request.session.get("csrf", "")
    if not attendu or not secrets.compare_digest(jeton.encode(), attendu.encode()):
        raise HTTPException(403, "Jeton de formulaire invalide")


def session_de(request: Request) -> dict | None:
    sid = request.session.get("sid", "")
    s = SESSIONS.get(sid)
    if s and time.time() - s["vu_le"] > DUREE_SESSION:
        SESSIONS.pop(sid, None)
        return None
    if s:
        s["vu_le"] = time.time()
    return s


def usager(request: Request) -> dict:
    """Usager connecté, sinon retour à la page de connexion."""
    s = session_de(request)
    if s is None:
        raise HTTPException(303, headers={"Location": RACINE})
    return s


def ref(s: dict) -> str:
    return quote(s["sujet_ref"], safe="")


# --- Connexion ---

@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


async def nombre_de_consultations(s: dict) -> int:
    """Compteur de l'accueil : les mêmes lignes que « Qui a consulté mes données »."""
    return len(await historique_de(s))


async def badge_journal() -> dict:
    """Badge « journal intègre » : la passerelle recalcule toute la chaîne (GET /journal/verification). Si la
    vérification est impossible, on le dit : jamais de faux « intègre »."""
    try:
        v = (await mediateur("GET", "/journal/verification")).json()
    except (MediateurInjoignable, ValueError):
        return {"etat": "indisponible", "texte": T["journal_indispo"]}
    if v.get("integre"):     # sans le nombre de lignes : l'heure de la vérification suffit à l'usager
        return {"etat": "ok", "texte": T["journal_ok"].format(
            heure=datetime.fromtimestamp(time.time(), timezone.utc).strftime("%H h %M"))}
    return {"etat": "ko", "texte": T["journal_ko"].format(n=v.get("premiere_ligne_modifiee"))}


@app.get(RACINE)
async def accueil(request: Request, page_n: int = 0):
    """Après la connexion, tout sur une page : « Bonjour », le compteur et la liste des consultations (qui, quoi,
    quand, pourquoi, statut ; détail au clic), puis les accords (retirables), puis les accords à donner."""
    s = session_de(request)
    if s is None:
        return page(request, "connexion.html", {})
    attente = (await mediateur("GET", f"/usagers/{ref(s)}/en-attente")).json()
    for d in attente:
        d["jusqu_a"] = heure(d["expire_le"])
    lignes = await historique_de(s)
    page_n = max(0, page_n)
    debut = page_n * PAR_PAGE
    return page(request, "accueil.html", {
        "prenom": s.get("prenom", ""), "consultations": len(lignes), "lignes": lignes[debut:debut + PAR_PAGE],
        "page_n": page_n, "suite": debut + PAR_PAGE < len(lignes), "journal": await badge_journal(),
        "accords": (await mediateur("GET", f"/usagers/{ref(s)}/accords")).json(), "demandes": attente,
        "accueil": True})


@app.post(f"{RACINE}/connexion")
def connexion(request: Request, csrf: str = Form(...), numero: str = Form(""), pin: str = Form("")):
    """Mêmes règles que l'USSD : 3 PIN faux -> numéro bloqué 5 minutes. Numéro inconnu et PIN faux donnent
    le même message (on ne révèle pas qui est inscrit)."""
    verifier_csrf(request, csrf)
    numero = "".join(c for c in numero if c.isdigit())[:12]
    if numero not in ABONNES:
        return page(request, "connexion.html", {"erreur": T["connexion_refusee"]}, 401)
    echecs = ECHECS_PIN.setdefault(numero, [0, 0.0])
    if time.time() < echecs[1]:
        return page(request, "connexion.html", {"erreur": T["bloque"]}, 429)
    if not secrets.compare_digest(pin.encode(), str(ABONNES[numero]["pin"]).encode()):
        echecs[0] += 1
        if echecs[0] >= ESSAIS_PIN:
            ECHECS_PIN[numero] = [0, time.time() + BLOCAGE]
            return page(request, "connexion.html", {"erreur": T["bloque"]}, 429)
        return page(request, "connexion.html",
                    {"erreur": T["pin_faux"].format(n=ESSAIS_PIN - echecs[0])}, 401)
    ECHECS_PIN.pop(numero, None)
    SESSIONS.pop(request.session.get("sid", ""), None)
    sid = secrets.token_urlsafe(32)
    # Prénom de l'annuaire de démo (affiché « Bonjour, … ») : l'espace usager ne lit jamais les registres
    SESSIONS[sid] = {"sujet_ref": ABONNES[numero]["sujet_ref"], "prenom": str(ABONNES[numero].get("prenom", "")),
                     "vu_le": time.time()}
    request.session["sid"] = sid
    request.session["csrf"] = secrets.token_urlsafe(32)      # nouveau jeton après connexion
    return RedirectResponse(RACINE, status_code=303)


@app.post(f"{RACINE}/deconnexion")
def deconnexion(request: Request, csrf: str = Form(...)):
    verifier_csrf(request, csrf)
    SESSIONS.pop(request.session.pop("sid", ""), None)
    return RedirectResponse(RACINE, status_code=303)


# --- 1. Accords à donner : voir AVANT, puis confirmer ou refuser ---

@app.get(f"{RACINE}/attente")
async def attente(request: Request):
    s = usager(request)
    demandes = (await mediateur("GET", f"/usagers/{ref(s)}/en-attente")).json()
    for d in demandes:
        d["jusqu_a"] = heure(d["expire_le"])
    return page(request, "attente.html", {"demandes": demandes})


@app.post(f"{RACINE}/attente/{{id_demande}}/{{action}}")
async def repondre(request: Request, id_demande: str, action: str, csrf: str = Form(...)):
    verifier_csrf(request, csrf)
    s = usager(request)
    if action not in ("confirmer", "refuser"):
        raise HTTPException(404)
    r = await mediateur("POST", f"/demandes/{quote(id_demande, safe='')}/{action}", json={"sujet_ref": s["sujet_ref"]})
    if r.status_code != 200:
        return page(request, "message.html", {"titre": T["deja_traitee_titre"], "texte": T["deja_traitee"]}, 409)
    if action == "confirmer":
        return page(request, "message.html", {"titre": T["confirme_titre"], "texte": T["confirme"],
                                              "recu": format_recu(r.json()["empreinte"])})
    return page(request, "message.html", {"titre": T["refuse_titre"], "texte": T["refuse"]})


# --- 2. Qui a consulté mes données : liste puis détail (finalité, base, reçu) ---

async def historique_de(s: dict) -> list[dict]:
    lignes = (await mediateur("GET", f"/usagers/{ref(s)}/historique")).json()
    montrees = [l for l in lignes if l["evenement"] in EVENEMENTS
                or (l["evenement"] == "demande" and l["resultat"] == "refuse")]
    for l in montrees:
        l["date"] = date_ligne(l["ts"])
        l["etat"] = T[EVENEMENTS.get(l["evenement"], "etat_refuse")]
    return montrees


@app.get(f"{RACINE}/historique")
async def historique(request: Request, page_n: int = 0):
    s = usager(request)
    lignes = await historique_de(s)
    page_n = max(0, page_n)
    debut = page_n * PAR_PAGE
    return page(request, "historique.html", {"lignes": lignes[debut:debut + PAR_PAGE], "page_n": page_n,
                                             "suite": debut + PAR_PAGE < len(lignes), "journal": await badge_journal(),
                                             "consultations": len(lignes)})


@app.get(f"{RACINE}/historique/{{n}}")
async def detail(request: Request, n: int):
    s = usager(request)
    # On ne montre que SES lignes : la ligne est cherchée dans son propre historique
    ligne = next((l for l in await historique_de(s) if l["n"] == n), None)
    if ligne is None:
        raise HTTPException(404, "Consultation introuvable")
    return page(request, "detail.html", {"l": ligne, "recu": format_recu(ligne["empreinte"])})


# --- 3. Retirer un accord ---

@app.get(f"{RACINE}/accords")
async def accords(request: Request):
    s = usager(request)
    return page(request, "accords.html", {"accords": (await mediateur("GET", f"/usagers/{ref(s)}/accords")).json()})


@app.post(f"{RACINE}/accords/{{id_demande}}/retirer")
async def retirer(request: Request, id_demande: str, csrf: str = Form(...), confirme: str = Form("")):
    """Deux temps, comme l'USSD : la question (« Retirer votre accord à … ? »), puis le retrait."""
    verifier_csrf(request, csrf)
    s = usager(request)
    if confirme != "oui":
        accord = next((a for a in (await mediateur("GET", f"/usagers/{ref(s)}/accords")).json()
                       if a["id_demande"] == id_demande), None)
        if accord is None:
            return page(request, "message.html", {"titre": T["deja_traitee_titre"], "texte": T["deja_traitee"]}, 409)
        return page(request, "retrait.html", {"a": accord})
    r = await mediateur("POST", f"/demandes/{quote(id_demande, safe='')}/retirer", json={"sujet_ref": s["sujet_ref"]})
    if r.status_code != 200:
        return page(request, "message.html", {"titre": T["deja_traitee_titre"], "texte": T["deja_traitee"]}, 409)
    texte = T["retrait_apres"] if r.json()["transmis"] else T["retrait_fait"]
    return page(request, "message.html", {"titre": T["retrait_titre"], "texte": texte,
                                          "recu": format_recu(r.json()["empreinte"])})

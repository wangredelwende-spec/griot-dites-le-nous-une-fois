"""USSD simulé (*226#) : un téléphone simple pour que l'usager VOIE AVANT et VÉRIFIE APRÈS.

- Écrans de 160 caractères au plus (comme un vrai écran USSD), rendu serveur, aucun JavaScript.
- Branché sur l'API usager du médiateur (docs/API_USAGER.md), comme le serait la passerelle USSD
  d'un opérateur. Ce service authentifie l'usager (numéro + PIN) et ne transmet que SON identifiant.
- Textes dans traduction-moore/phrases-ussd.csv ; une langue n'est proposée que si elle est complète.
"""
import csv
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

ICI = Path(__file__).parent
MEDIATEUR = os.environ.get("MEDIATEUR", "http://mediateur:8000")
FICHIER_ABONNES = Path(os.environ.get("ABONNES", "/app/abonnes.yaml"))
FICHIER_TEXTES = Path(os.environ.get("TEXTES", "/app/phrases-ussd.csv"))
SECRETS = Path(os.environ.get("GRIOT_SECRETS", "/run/secrets"))

CODE_USSD = "*226#"
LIMITE = 160            # caractères par écran
PAR_ECRAN = 3           # lignes d'historique par écran
DUREE_SESSION = 180     # une session USSD se ferme après 3 minutes sans réponse
ESSAIS_PIN = 3
BLOCAGE = 300           # 5 minutes de blocage après 3 PIN faux
# Événements montrés dans « Qui a consulté mes données » (les étapes internes sont omises)
EVENEMENTS = {"remise": "etat_remise", "refus-usager": "etat_refuse", "expiration": "etat_expiration",
              "alerte": "etat_alerte"}


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
SECRET_CANAL = (SECRETS / "canal_usager").read_text().strip()

# Sessions USSD en mémoire (le cookie ne contient qu'un numéro de session aléatoire)
SESSIONS: dict[str, dict] = {}
ECHECS_PIN: dict[str, list] = {}     # numéro -> [nombre d'échecs, bloqué jusqu'à]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32), session_cookie="ussd_session",
                   https_only=True, same_site="lax", max_age=3600)
app.mount("/static", StaticFiles(directory=ICI / "static"), name="static")
templates = Jinja2Templates(directory=ICI / "templates")


def t(s: dict, cle: str, **valeurs) -> str:
    return TEXTES[s["langue"]][cle].format(**valeurs)


def ecran(*lignes: str) -> str:
    """Assemble un écran ; au-delà de 160 caractères, on coupe (ne devrait jamais arriver en français)."""
    texte = "\n".join(l for l in lignes if l)
    return texte if len(texte) <= LIMITE else texte[:LIMITE - 1] + "…"


def menu(s: dict) -> str:
    s["etape"] = "menu"
    return ecran(t(s, "menu_attente"), t(s, "menu_historique"),
                 t(s, "menu_langue") if len(TEXTES) > 1 else "", t(s, "menu_quitter"))


async def mediateur(methode: str, chemin: str, **kwargs):
    async with httpx.AsyncClient(base_url=MEDIATEUR, timeout=5, headers={"X-Cle-Canal": SECRET_CANAL}) as client:
        return await client.request(methode, chemin, **kwargs)


# --- Écrans ---

def ecran_attente(s: dict) -> str:
    if not s["liste"]:
        s["etape"] = "info"
        return ecran(t(s, "aucune_demande"), t(s, "retour_menu"))
    d = s["liste"][s["index"]]
    service = TEXTES[s["langue"]].get(f"service_long_{d['code_service']}", d["service"])
    attribut = TEXTES[s["langue"]].get(f"attribut_{d['code_attribut']}", d["attribut"])
    rang = f"({s['index'] + 1}/{len(s['liste'])}) " if len(s["liste"]) > 1 else ""
    suivante = t(s, "suivante") + " " if s["index"] + 1 < len(s["liste"]) else ""
    return ecran(rang + t(s, "apercu", service=service, attribut=attribut, valeur=t(s, d["valeur"])),
                 t(s, "confirmer_refuser"), suivante + t(s, "retour"))


def ligne_historique(s: dict, l: dict) -> str:
    """« 16/11 11h54 Concours majeur transmis 038672c3 » : date, qui, quoi, résultat, reçu (8 caractères)."""
    date = datetime.strptime(l["ts"], "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m %Hh%M")
    service = TEXTES[s["langue"]].get(f"service_court_{l['code_service']}", l["code_service"][:8])
    attribut = TEXTES[s["langue"]].get(f"attribut_{l['attribut']}", l["attribut"][:8])
    etat = t(s, EVENEMENTS.get(l["evenement"], "etat_refuse"))
    return f"{date} {service} {attribut} {etat} {l['empreinte'][:8]}"


def ecran_historique(s: dict) -> str:
    if not s["liste"]:
        s["etape"] = "info"
        return ecran(t(s, "historique_vide"), t(s, "retour_menu"))
    debut = s["page"] * PAR_ECRAN
    lignes = [ligne_historique(s, l) for l in s["liste"][debut:debut + PAR_ECRAN]]
    pied = t(s, "suite") if debut + PAR_ECRAN < len(s["liste"]) else t(s, "retour")
    return ecran(*lignes, pied)


async def traiter(s: dict, reponse: str) -> str:
    """Machine à états d'une session USSD : renvoie le texte du prochain écran."""
    etape = s["etape"]
    if etape == "composer":
        if reponse != CODE_USSD:
            return ecran(t(s, "code_inconnu"))
        if s["numero"] not in ABONNES:
            return ecran(t(s, "non_inscrit"))
        s["etape"] = "pin"
        return ecran(t(s, "pin"))

    if etape == "pin":
        echecs = ECHECS_PIN.setdefault(s["numero"], [0, 0.0])
        if time.time() < echecs[1]:
            return ecran(t(s, "bloque"))
        if not secrets.compare_digest(reponse.encode(), str(ABONNES[s["numero"]]["pin"]).encode()):
            echecs[0] += 1
            if echecs[0] >= ESSAIS_PIN:
                ECHECS_PIN[s["numero"]] = [0, time.time() + BLOCAGE]
                return ecran(t(s, "bloque"))
            return ecran(t(s, "pin_faux", n=ESSAIS_PIN - echecs[0]))
        ECHECS_PIN.pop(s["numero"], None)
        s["sujet_ref"] = ABONNES[s["numero"]]["sujet_ref"]
        return menu(s)

    if etape == "menu":
        try:
            if reponse == "1":
                r = await mediateur("GET", f"/usagers/{s['sujet_ref']}/en-attente")
                r.raise_for_status()
                s.update(etape="attente", liste=r.json(), index=0)
                return ecran_attente(s)
            if reponse == "2":
                r = await mediateur("GET", f"/usagers/{s['sujet_ref']}/historique")
                r.raise_for_status()
                lignes = [l for l in r.json() if l["evenement"] in EVENEMENTS
                          or (l["evenement"] == "demande" and l["resultat"] == "refuse")]
                s.update(etape="historique", liste=lignes, page=0)
                return ecran_historique(s)
        except httpx.HTTPError:
            s["etape"] = "info"
            return ecran(t(s, "indisponible"), t(s, "retour_menu"))
        if reponse == "3" and len(TEXTES) > 1:
            s["etape"] = "langue"
            choix = [f"{i}. {TEXTES[code]['nom_langue']}" for i, code in enumerate(TEXTES, start=1)]
            return ecran(t(s, "langue"), *choix, t(s, "retour"))
        if reponse == "0":
            s["etape"] = "fin"
            return ecran(t(s, "au_revoir"))
        return ecran(t(s, "choix_invalide"), menu(s))

    if etape == "attente":
        if reponse == "0":
            return menu(s)
        if reponse == "9" and s["index"] + 1 < len(s["liste"]):
            s["index"] += 1
            return ecran_attente(s)
        if reponse in ("1", "2"):
            d = s["liste"][s["index"]]
            action = "confirmer" if reponse == "1" else "refuser"
            try:
                r = await mediateur("POST", f"/demandes/{d['id_demande']}/{action}", json={"sujet_ref": s["sujet_ref"]})
            except httpx.HTTPError:
                s["etape"] = "info"
                return ecran(t(s, "indisponible"), t(s, "retour_menu"))
            s["etape"] = "info"
            if r.status_code != 200:
                return ecran(t(s, "deja_traitee"), t(s, "retour_menu"))
            if action == "confirmer":
                return ecran(t(s, "confirme", recu=r.json()["empreinte"][:8]), t(s, "retour_menu"))
            return ecran(t(s, "refuse"), t(s, "retour_menu"))
        return ecran(t(s, "choix_invalide"), ecran_attente(s))

    if etape == "historique":
        if reponse == "9" and (s["page"] + 1) * PAR_ECRAN < len(s["liste"]):
            s["page"] += 1
            return ecran_historique(s)
        return menu(s) if reponse == "0" else ecran_historique(s)

    if etape == "langue":
        codes = list(TEXTES)
        if reponse.isdigit() and 1 <= int(reponse) <= len(codes):
            s["langue"] = codes[int(reponse) - 1]
        return menu(s)

    # « info » (message + « 0. Menu ») : toute réponse ramène au menu
    return menu(s)


# --- Pages ---

def session_de(request: Request) -> dict | None:
    s = SESSIONS.get(request.session.get("sid", ""))
    if s and time.time() - s["vu_le"] > DUREE_SESSION and s["etape"] not in ("composer", "fin"):
        # Comme un vrai réseau USSD : sans réponse pendant 3 minutes, la session se ferme
        s.update(etape="composer", ecran=ecran(t(s, "session_expiree"), t(s, "composer")), sujet_ref=None)
    return s


def verifier_csrf(request: Request, jeton: str):
    attendu = request.session.get("csrf", "")
    if not attendu or not secrets.compare_digest(jeton.encode(), attendu.encode()):
        raise HTTPException(403, "Jeton de formulaire invalide")


@app.get("/sante", include_in_schema=False)
def sante():
    return PlainTextResponse("ok")


@app.get("/")
def telephone(request: Request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    s = session_de(request)
    langue = s["langue"] if s else "fr"
    return templates.TemplateResponse(request, "telephone.html", {
        "s": s, "csrf": request.session["csrf"], "textes": TEXTES[langue], "limite": LIMITE})


@app.post("/allumer")
def allumer(request: Request, csrf: str = Form(...), numero: str = Form("")):
    verifier_csrf(request, csrf)
    numero = "".join(c for c in numero if c.isdigit())[:12]
    sid = secrets.token_urlsafe(32)
    s = {"numero": numero, "langue": "fr", "etape": "composer", "sujet_ref": None, "vu_le": time.time()}
    s["ecran"] = ecran(t(s, "composer"))
    SESSIONS[sid] = s
    request.session["sid"] = sid
    return RedirectResponse("/", status_code=303)


@app.post("/")
async def saisir(request: Request, csrf: str = Form(...), reponse: str = Form("")):
    verifier_csrf(request, csrf)
    s = session_de(request)
    if s is None:
        return RedirectResponse("/", status_code=303)
    if s["etape"] == "fin":
        s["etape"] = "composer"
    s["ecran"] = await traiter(s, reponse.strip()[:20])
    s["vu_le"] = time.time()
    return RedirectResponse("/", status_code=303)


@app.post("/raccrocher")
def raccrocher(request: Request, csrf: str = Form(...)):
    verifier_csrf(request, csrf)
    SESSIONS.pop(request.session.pop("sid", ""), None)
    return RedirectResponse("/", status_code=303)

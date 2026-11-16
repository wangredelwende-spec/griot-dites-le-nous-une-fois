"""Guichet des agents : rendu serveur, aucun JavaScript.

Accès protégé par Keycloak (OIDC, client « guichet », mot de passe + TOTP) : seul le rôle agent-guichet entre.
Le service de l'agent vient de son jeton, jamais d'un formulaire.
Le guichet ne reçoit que la réponse minimale SIGNÉE par le registre, et revérifie lui-même la signature.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
import jwt
import yaml
from authlib.integrations.starlette_client import OAuth, OAuthError
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import (CLES_PUBLIQUES, CLIENT_ID, FICHIER_REGLES, GUICHET_URL, KEYCLOAK_INTERNE, KEYCLOAK_PUBLIC,
                     MEDIATEUR, REALM, ROLE_AGENT, lire_secret)

SECRET_OIDC = lire_secret("guichet_oidc")
REGLES = yaml.safe_load(FICHIER_REGLES.read_text(encoding="utf-8"))

# Jetons Keycloak des agents connectés, gardés EN MÉMOIRE côté serveur (trop gros pour un cookie).
# Le cookie de session ne contient qu'un numéro de session aléatoire.
JETONS: dict[str, dict] = {}
# Résultats déjà vérifiés, pour pouvoir réafficher la page (le médiateur ne remet la réponse qu'une fois)
RESULTATS: dict[str, dict] = {}

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
# Clé de session tirée à chaque démarrage : redémarrer le guichet déconnecte les agents.
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32), session_cookie="guichet_session",
                   https_only=True, same_site="lax", max_age=8 * 3600)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

oauth = OAuth()
oauth.register(
    "keycloak",
    client_id=CLIENT_ID,
    client_secret=SECRET_OIDC,
    # Le navigateur va sur l'adresse publique ; l'échange du code et les clés passent par le réseau interne
    authorize_url=f"{KEYCLOAK_PUBLIC}/realms/{REALM}/protocol/openid-connect/auth",
    access_token_url=f"{KEYCLOAK_INTERNE}/realms/{REALM}/protocol/openid-connect/token",
    jwks_uri=f"{KEYCLOAK_INTERNE}/realms/{REALM}/protocol/openid-connect/certs",
    issuer=f"{KEYCLOAK_PUBLIC}/realms/{REALM}",
    client_kwargs={"scope": "openid profile", "code_challenge_method": "S256"},
)


class NonConnecte(Exception):
    pass


@app.exception_handler(NonConnecte)
async def vers_connexion(_request, _exc):
    return RedirectResponse("/connexion", status_code=303)


def exiger_agent(request: Request) -> dict:
    session = JETONS.get(request.session.get("sid", ""))
    if not session:
        raise NonConnecte()
    return session


def verifier_csrf(request: Request, jeton: str):
    attendu = request.session.get("csrf", "")
    if not attendu or not secrets.compare_digest(jeton.encode(), attendu.encode()):
        raise HTTPException(403, "Jeton de formulaire invalide")


def page(request: Request, modele: str, statut: int = 200, **contexte):
    session = JETONS.get(request.session.get("sid", ""), {})
    contexte |= {"agent": session.get("nom"), "service": session.get("service_nom"),
                 "csrf": request.session.get("csrf")}
    return templates.TemplateResponse(request, modele, contexte, status_code=statut)


def service_de(groupes: list[str]) -> tuple[str, str] | None:
    """Groupe Keycloak -> (code, nom) du service, à partir des mêmes règles que le médiateur."""
    services = [(code, s["nom"]) for code, s in REGLES["services"].items() if s["groupe"] in groupes]
    return services[0] if len(services) == 1 else None


# --- Connexion ---

@app.get("/sante", include_in_schema=False)
async def sante():
    return PlainTextResponse("ok")


@app.get("/connexion")
async def connexion(request: Request):
    return await oauth.keycloak.authorize_redirect(request, f"{GUICHET_URL}/auth/callback")


@app.get("/auth/callback")
async def retour_keycloak(request: Request):
    try:
        jeton = await oauth.keycloak.authorize_access_token(request)
    except OAuthError as e:
        # Raison précise dans les logs du guichet (docker compose logs guichet), JAMAIS le jeton ni le code.
        # Cas typique : « mismatching_state » = le cookie de session ne correspond plus (guichet redémarré
        # entre le départ vers Keycloak et le retour, ou onglet trop ancien).
        print(f"connexion OIDC échouée : {type(e).__name__} : {e.error} : {e.description or ''}", flush=True)
        if e.error == "mismatching_state":
            return page(request, "erreur.html", 400, message="Votre session de connexion a expiré (le guichet a "
                        "peut-être redémarré). Revenez à l'accueil pour vous reconnecter.")
        return page(request, "erreur.html", 400, message="La connexion a échoué. Veuillez réessayer.")
    except httpx.HTTPError as e:
        print(f"connexion OIDC échouée : Keycloak injoignable ({type(e).__name__})", flush=True)
        return page(request, "erreur.html", 502, message="Le service de connexion est injoignable. Réessayez "
                    "dans un instant.")
    except Exception as e:      # ex. jeton d'identité refusé (horloge, émetteur) : on note le type, pas le jeton
        print(f"connexion OIDC échouée : {type(e).__name__} : {str(e)[:200]}", flush=True)
        return page(request, "erreur.html", 400, message="La connexion a échoué. Veuillez réessayer.")
    infos = jeton["userinfo"]
    request.session.clear()
    service = service_de(infos.get("groups", []))
    if ROLE_AGENT not in infos.get("roles", []) or service is None:
        return page(request, "erreur.html", 403, message="Accès réservé aux agents de guichet rattachés à un service.")
    sid = secrets.token_urlsafe(32)
    JETONS[sid] = {"nom": infos.get("preferred_username", infos["sub"]), "service": service[0],
                   "service_nom": service[1], "acces": jeton["access_token"], "id_token": jeton["id_token"]}
    request.session.update(sid=sid, csrf=secrets.token_urlsafe(32))
    return RedirectResponse("/", status_code=303)


@app.post("/deconnexion")
async def deconnexion(request: Request, csrf: str = Form(...)):
    verifier_csrf(request, csrf)
    session = JETONS.pop(request.session.get("sid", ""), {})
    parametres = {"client_id": CLIENT_ID, "post_logout_redirect_uri": f"{GUICHET_URL}/",
                  "id_token_hint": session.get("id_token", "")}
    request.session.clear()
    return RedirectResponse(f"{KEYCLOAK_PUBLIC}/realms/{REALM}/protocol/openid-connect/logout?"
                            f"{urlencode(parametres)}", status_code=303)


# --- Demandes ---

def demarches_du_service(service: str) -> dict:
    return {code: d for code, d in REGLES["demarches"].items() if d["service"] == service}


async def mediateur(methode: str, chemin: str, session: dict, **kwargs) -> dict:
    """Appel du médiateur avec le jeton de l'agent. Jeton expiré : on repasse par Keycloak
    (la session Keycloak est encore ouverte, donc sans retaper le mot de passe)."""
    async with httpx.AsyncClient(base_url=MEDIATEUR, timeout=10) as client:
        r = await client.request(methode, chemin, headers={"Authorization": f"Bearer {session['acces']}"}, **kwargs)
    if r.status_code == 401:
        raise NonConnecte()
    r.raise_for_status()
    return r.json()


def heure(horodatage: int) -> str:
    """1794838200 -> « 14 h 13 » (heure de Ouagadougou = UTC)."""
    t = datetime.fromtimestamp(horodatage, timezone.utc)
    return f"{t.hour} h {t.minute:02d}"


def empreinte_cle(cle_publique_pem: bytes) -> str:
    """Empreinte courte de la clé publique du registre (SHA-256 de sa forme DER). La même s'affiche
    au démarrage du registre (docker compose logs registre-etat-civil) : on peut comparer."""
    der = serialization.load_pem_public_key(cle_publique_pem).public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    h = hashlib.sha256(der).hexdigest()[:16]
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def verifier_reponse(jeton: str, demarche: dict, service: str, id_demande: str) -> dict:
    """Le guichet NE FAIT PAS confiance au médiateur : il revérifie la signature du registre, avec la clé
    lue dans le volume du registre (monté en lecture seule ; le médiateur ne peut ni la fournir ni la remplacer)."""
    attribut = REGLES["attributs"][demarche["attribut"]]
    registre = REGLES["registres"][attribut["registre"]]
    cle_publique = (CLES_PUBLIQUES / attribut["registre"] / "cle.pem").read_bytes()
    infos = jwt.decode(jeton, cle_publique, algorithms=["EdDSA"], audience=service, issuer=registre["emetteur"],
                       options={"require": ["iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut"]})
    if infos["demande"] != id_demande:
        raise jwt.InvalidTokenError("réponse émise pour une autre demande")
    commun = {"registre": registre["nom"], "cle": empreinte_cle(cle_publique)}
    if infos["statut"] == "refus":
        return commun | {"refus": str(infos["motif"])}
    valeur = infos[attribut["claim"]]
    if attribut.get("cle") is not None:
        valeur = valeur[attribut["cle"]]
    if infos["statut"] != "ok" or type(valeur) is not bool:
        raise jwt.InvalidTokenError("valeur inattendue")
    return commun | {"attribut": attribut["libelle"], "valeur": "oui" if valeur else "non",
                     "jusqu_a": heure(infos["exp"])}


@app.get("/")
async def accueil(request: Request, session: dict = Depends(exiger_agent)):
    return page(request, "accueil.html", demarches=demarches_du_service(session["service"]))


@app.post("/demandes")
async def envoyer(request: Request, csrf: str = Form(...), demarche: str = Form(""), sujet_ref: str = Form(""),
                  autre_finalite: str = Form(""), session: dict = Depends(exiger_agent)):
    verifier_csrf(request, csrf)
    demarches = demarches_du_service(session["service"])
    if demarche not in demarches or not sujet_ref.strip():
        return page(request, "accueil.html", 400, demarches=demarches, erreur="Choisissez une démarche et "
                    "indiquez l'identifiant de l'usager.")
    regle = demarches[demarche]
    id_demande = str(uuid.uuid4())
    corps = {"id_demande": id_demande, "demarche": demarche, "attribut": regle["attribut"],
             "sujet_ref": sujet_ref.strip(), "finalite": autre_finalite.strip() or regle["finalite"]}
    try:
        etat = await mediateur("POST", "/demandes", session, json=corps)
    except httpx.HTTPError:
        return page(request, "erreur.html", 502, message="Médiateur injoignable ou demande invalide : "
                    "rien n'a été transmis, rien n'a été deviné.")
    RESULTATS[id_demande] = {"agent": session["nom"], "sujet_ref": corps["sujet_ref"], "demarche": demarche}
    # Base légale : la réponse signée arrive tout de suite, et le médiateur ne la remet qu'une fois
    noter(RESULTATS[id_demande], etat, session, id_demande)
    return RedirectResponse(f"/demandes/{id_demande}", status_code=303)


def noter(suivi: dict, etat: dict, session: dict, id_demande: str):
    """Garde l'état reçu du médiateur ; si la réponse signée est là, la vérifie avant tout affichage."""
    suivi["etat"] = etat
    if etat.get("jeton"):
        try:
            suivi["resultat"] = verifier_reponse(etat["jeton"], REGLES["demarches"][suivi["demarche"]],
                                                 session["service"], id_demande)
        except (jwt.PyJWTError, KeyError, TypeError, FileNotFoundError) as e:
            suivi["etat"] = {"statut": "refuse", "motif": f"signature du registre non vérifiée au guichet ({e})"}


@app.get("/demandes/{id_demande}")
async def suivre(request: Request, id_demande: uuid.UUID, session: dict = Depends(exiger_agent)):
    id_demande = str(id_demande)
    suivi = RESULTATS.get(id_demande)
    if suivi is None or suivi["agent"] != session["nom"]:
        raise HTTPException(404, "Demande introuvable")
    regle = REGLES["demarches"][suivi["demarche"]]
    # On ne réinterroge le médiateur que tant que l'usager n'a pas répondu
    if suivi["etat"]["statut"] in ("en_attente", "confirmee"):
        try:
            noter(suivi, await mediateur("GET", f"/demandes/{id_demande}", session), session, id_demande)
        except httpx.HTTPError:
            return page(request, "erreur.html", 502, message="Médiateur injoignable : rien n'a été deviné. "
                        "Réessayez dans un instant.")
    etat = suivi["etat"]
    return page(request, "demande.html", suivi=suivi, regle=regle, etat=etat, resultat=suivi.get("resultat"),
                expire=heure(etat["expire_le"]) if etat.get("expire_le") else None)

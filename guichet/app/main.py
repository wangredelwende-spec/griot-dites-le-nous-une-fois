"""Guichet des agents : rendu serveur, aucun JavaScript.

Accès protégé par Keycloak (OIDC, client « guichet », mot de passe + TOTP) :
seul le rôle agent-guichet entre. Le service de l'agent vient de son jeton, jamais d'un formulaire.
"""
import secrets
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import CLIENT_ID, GUICHET_URL, KEYCLOAK_INTERNE, KEYCLOAK_PUBLIC, REALM, ROLE_AGENT, lire_secret

SECRET_OIDC = lire_secret("guichet_oidc")

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


def exiger_agent(request: Request) -> str:
    agent = request.session.get("agent")
    if not agent:
        raise NonConnecte()
    return agent


def verifier_csrf(request: Request, jeton: str):
    attendu = request.session.get("csrf", "")
    if not attendu or not secrets.compare_digest(jeton.encode(), attendu.encode()):
        raise HTTPException(403, "Jeton de formulaire invalide")


def page(request: Request, modele: str, statut: int = 200, **contexte):
    contexte |= {"agent": request.session.get("agent"), "csrf": request.session.get("csrf")}
    return templates.TemplateResponse(request, modele, contexte, status_code=statut)


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
    except OAuthError:
        return page(request, "erreur.html", 400, message="La connexion a échoué. Veuillez réessayer.")
    infos = jeton["userinfo"]
    request.session.clear()
    if ROLE_AGENT not in infos.get("roles", []):
        return page(request, "erreur.html", 403, message="Accès réservé aux agents de guichet.")
    request.session.update(agent=infos.get("preferred_username", infos["sub"]), id_token=jeton["id_token"],
                           csrf=secrets.token_urlsafe(32))
    return RedirectResponse("/", status_code=303)


@app.post("/deconnexion")
async def deconnexion(request: Request, csrf: str = Form(...)):
    verifier_csrf(request, csrf)
    parametres = {"client_id": CLIENT_ID, "post_logout_redirect_uri": f"{GUICHET_URL}/",
                  "id_token_hint": request.session.get("id_token", "")}
    request.session.clear()
    return RedirectResponse(f"{KEYCLOAK_PUBLIC}/realms/{REALM}/protocol/openid-connect/logout?"
                            f"{urlencode(parametres)}", status_code=303)

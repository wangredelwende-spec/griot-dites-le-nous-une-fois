"""Guichet des agents : rendu serveur, aucun JavaScript.

Accès protégé par Keycloak (OIDC, client « guichet », mot de passe + TOTP) : seul le rôle agent-guichet entre.
Le service de l'agent vient de son jeton, jamais d'un formulaire.
Le guichet ne reçoit que la réponse minimale SIGNÉE par le registre, et revérifie lui-même la signature.
"""
import hashlib
import secrets
import uuid
from datetime import date, datetime, timezone
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

from .config import (ADAPTATEURS, CATALOGUE, CLES_PUBLIQUES, CLIENT_ID, GUICHET_URL, KEYCLOAK_INTERNE, KEYCLOAK_PUBLIC,
                     MEDIATEUR, REALM, ROLE_AGENT, lire_secret)

SECRET_OIDC = lire_secret("guichet_oidc")
# Mêmes fichiers que le médiateur, en lecture seule : annuaire, catalogue des démarches,
# et attributs déclarés par chaque registre (adaptateurs/<registre>.yaml).
ANNUAIRE = yaml.safe_load((CATALOGUE / "annuaire.yaml").read_text(encoding="utf-8"))
DEMARCHES = yaml.safe_load((CATALOGUE / "demarches.yaml").read_text(encoding="utf-8"))["demarches"]
ATTRIBUTS = {}
for _registre in ANNUAIRE["registres"]:
    _conf = yaml.safe_load((ADAPTATEURS / f"{_registre}.yaml").read_text(encoding="utf-8"))
    ATTRIBUTS |= {code: a | {"registre": _registre} for code, a in _conf["attributs"].items()}

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
    """Groupe Keycloak -> (code, nom) du service, à partir du même annuaire que le médiateur."""
    services = [(code, s["nom"]) for code, s in ANNUAIRE["services"].items() if s["groupe"] in groupes]
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
    """Le guichet ne propose QUE les démarches du catalogue ouvertes au service de l'agent."""
    return {code: d for code, d in DEMARCHES.items() if service in d["services"]}


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


def verifier_volet(jeton: str, demande_attribut: dict, service: str, id_demande: str, sujet_ref: str) -> dict:
    """Le guichet NE FAIT PAS confiance au médiateur : il revérifie la signature du registre, avec la clé
    lue dans le volume du registre (monté en lecture seule ; le médiateur ne peut ni la fournir ni la remplacer)."""
    attribut = ATTRIBUTS[demande_attribut["attribut"]]
    registre = ANNUAIRE["registres"][attribut["registre"]]
    cle_publique = (CLES_PUBLIQUES / attribut["registre"] / "cle.pem").read_bytes()
    infos = jwt.decode(jeton, cle_publique, algorithms=["EdDSA"], audience=service, issuer=registre["emetteur"],
                       options={"require": ["iss", "aud", "sub", "demande", "iat", "exp", "jti", "statut"]})
    if infos["demande"] != id_demande or infos["sub"] != sujet_ref:
        raise jwt.InvalidTokenError("réponse émise pour une autre demande ou une autre personne")
    resultat = {"signe": True, "registre": registre["nom"], "cle": empreinte_cle(cle_publique)}
    if infos["statut"] == "refus":
        return resultat | {"refus": str(infos["motif"])}
    if infos["statut"] != "ok":
        raise jwt.InvalidTokenError("statut inattendu")
    return resultat | {"valeur": lire_valeur(infos, attribut, demande_attribut.get("parametres") or {}),
                       "jusqu_a": heure(infos["exp"])}


def lire_valeur(infos: dict, attribut: dict, parametres: dict) -> bool:
    """Réponse signée -> oui/non. Le guichet relit lui-même la réponse, avec les paramètres du catalogue."""
    valeur = infos[attribut["claim"]]
    if attribut["regle"] != "age_entre":
        if type(valeur) is not bool:                # ex. {"nationalite_burkinabe": true}
            raise jwt.InvalidTokenError("valeur inattendue")
        return valeur
    # ex. {"age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31"}
    #     = au moins 18 ans ET pas encore 38 ans (donc 37 ans au plus) à la date de référence
    reference = str(parametres["date_reference"])
    if reference == "aujourd'hui":                  # le jour où le registre a signé
        reference = datetime.fromtimestamp(infos["iat"], timezone.utc).date().isoformat()
    if infos["date_reference"] != reference:
        raise jwt.InvalidTokenError("date de référence différente de celle du catalogue")
    seuils = [str(parametres["min"])] + ([str(parametres["max"] + 1)] if parametres.get("max") is not None else [])
    if set(valeur) != set(seuils) or any(type(v) is not bool for v in valeur.values()):
        raise jwt.InvalidTokenError("seuils d'âge inattendus")
    return valeur[seuils[0]] and not (len(seuils) == 2 and valeur[seuils[1]])


@app.get("/")
async def accueil(request: Request, session: dict = Depends(exiger_agent)):
    return page(request, "accueil.html", demarches=demarches_du_service(session["service"]))


@app.post("/demandes")
async def envoyer(request: Request, csrf: str = Form(...), demarche: str = Form(""), sujet_ref: str = Form(""),
                  session: dict = Depends(exiger_agent)):
    verifier_csrf(request, csrf)
    demarches = demarches_du_service(session["service"])
    if demarche not in demarches or not sujet_ref.strip():
        return page(request, "accueil.html", 400, demarches=demarches, erreur="Choisissez une démarche et "
                    "indiquez l'identifiant de l'usager.")
    id_demande = str(uuid.uuid4())
    # Ni attribut ni question libre : c'est le catalogue qui fixe ce que la démarche peut demander
    corps = {"id_demande": id_demande, "demarche": demarche, "sujet_ref": sujet_ref.strip(),
             "finalite": demarches[demarche]["finalite"]}
    try:
        etat = await mediateur("POST", "/demandes", session, json=corps)
    except httpx.HTTPError:
        return page(request, "erreur.html", 502, message="Médiateur injoignable ou demande invalide : "
                    "rien n'a été transmis, rien n'a été deviné.")
    RESULTATS[id_demande] = {"agent": session["nom"], "sujet_ref": corps["sujet_ref"], "demarche": demarche,
                             "volets": {}}
    # Base légale : les réponses signées arrivent tout de suite, et le médiateur ne les remet qu'une fois
    noter(RESULTATS[id_demande], etat, session, id_demande)
    return RedirectResponse(f"/demandes/{id_demande}", status_code=303)


def noter(suivi: dict, etat: dict, session: dict, id_demande: str):
    """Garde l'état reçu du médiateur. Chaque réponse signée est vérifiée ICI avant tout affichage ;
    un résultat déjà vérifié n'est jamais remplacé."""
    suivi["etat"] = etat
    demandes = {a["attribut"]: a for a in DEMARCHES[suivi["demarche"]]["attributs"]}
    for volet in etat.get("volets", []):
        code = volet["attribut"]
        if code not in demandes or suivi["volets"].get(code, {}).get("signe"):
            continue
        if volet.get("jeton"):
            try:
                suivi["volets"][code] = verifier_volet(volet["jeton"], demandes[code], session["service"],
                                                       id_demande, suivi["sujet_ref"])
            except (jwt.PyJWTError, KeyError, TypeError, AttributeError, FileNotFoundError) as e:
                suivi["volets"][code] = {"echec": f"signature du registre non vérifiée au guichet ({e})"}
        elif volet["statut"] == "en_attente":
            suivi["volets"][code] = {"attente": True}
        elif volet["statut"] == "indisponible":
            suivi["volets"][code] = {"indisponible": volet["motif"]}
        else:       # refusé sans réponse signée, ou non transmis (usager : refus, délai dépassé)
            suivi["volets"][code] = {"echec": volet["motif"] or etat.get("motif") or "non transmis"}


def conclusion(lignes: list[dict]) -> str:
    """Jamais de « oui » global sur un résultat partiel."""
    valeurs = [l["resultat"].get("valeur") for l in lignes]
    if all(v is True for v in valeurs):
        return "oui"
    if any(v is False for v in valeurs):
        return "non"
    return "incomplet"


@app.get("/demandes/{id_demande}")
async def suivre(request: Request, id_demande: uuid.UUID, session: dict = Depends(exiger_agent)):
    id_demande = str(id_demande)
    suivi = RESULTATS.get(id_demande)
    if suivi is None or suivi["agent"] != session["nom"]:
        raise HTTPException(404, "Demande introuvable")
    demarche = DEMARCHES[suivi["demarche"]]
    # On ne réinterroge le médiateur que tant que l'usager n'a pas répondu
    if suivi["etat"]["statut"] in ("en_attente", "confirmee"):
        try:
            noter(suivi, await mediateur("GET", f"/demandes/{id_demande}", session), session, id_demande)
        except httpx.HTTPError:
            return page(request, "erreur.html", 502, message="Médiateur injoignable : rien n'a été deviné. "
                        "Réessayez dans un instant.")
    etat = suivi["etat"]
    lignes = [{"libelle": a["libelle"], "resultat": suivi["volets"].get(a["attribut"], {})}
              for a in demarche["attributs"]]
    return page(request, "demande.html", suivi=suivi, demarche=demarche, etat=etat, lignes=lignes,
                conclusion=conclusion(lignes), expire=heure(etat["expire_le"]) if etat.get("expire_le") else None)

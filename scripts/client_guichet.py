"""Client du guichet pour les scripts et les tests de bout en bout : se connecte comme un vrai agent
(Keycloak : mot de passe + TOTP) et envoie une demande, contre la pile qui tourne.

Comptes de test : agent.banc (Direction des concours) et agent.banc.bourses (Service des bourses).
Leur secret TOTP est créé au premier passage et gardé dans tests/.secrets/ (ignoré par git).
Ne pas utiliser ces comptes en démonstration manuelle.
"""
import base64
import html
import json
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pyotp

RACINE = Path(__file__).resolve().parents[1]
SECRETS = RACINE / "tests/.secrets"
GUICHET = "https://guichet.griot.test"
MOT_DE_PASSE = "Agent-Demo-2026!"
# Compte de test à utiliser pour chaque service
AGENTS = {"direction-concours": "agent.banc", "service-bourses": "agent.banc.bourses"}

# Les noms *.griot.test pointent vers 127.0.0.1, même si le fichier hosts n'est pas encore à jour
_resolution = socket.getaddrinfo
socket.getaddrinfo = lambda hote, *a, **k: _resolution("127.0.0.1" if hote.endswith(".griot.test") else hote, *a, **k)


def autorite_caddy() -> str:
    """Certificat racine de la CA interne de Caddy : le HTTPS est vraiment vérifié."""
    SECRETS.mkdir(parents=True, exist_ok=True)
    chemin = SECRETS / "caddy-racine.crt"
    subprocess.run(["docker", "compose", "cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(chemin)],
                   cwd=RACINE, check=True, capture_output=True)
    return str(chemin)


def formulaire(page: str, identifiant: str) -> tuple[str, dict]:
    """Adresse et champs (y compris cachés) d'un formulaire de la page."""
    bloc = re.search(rf'<form[^>]*id="{identifiant}"[^>]*>(.*?)</form>', page, re.S)
    if not bloc:
        raise AssertionError(f"formulaire {identifiant} absent")
    action = html.unescape(re.search(r'action="([^"]+)"', bloc.group(0)).group(1))
    champs = {n: html.unescape(v) for n, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', bloc[1])}
    return action, champs


def code_neuf(totp: pyotp.TOTP, agent: str) -> str:
    """Keycloak refuse qu'un même code serve deux fois : si le dernier passage l'a déjà utilisé,
    on attend la fenêtre de 30 s suivante."""
    dernier = SECRETS / f"dernier-code-{agent}"
    if dernier.exists() and dernier.read_text() == totp.now():
        time.sleep(30 - time.time() % 30 + 1)
    dernier.write_text(totp.now())
    return totp.now()


def connecter(client: httpx.Client, agent: str = "agent.banc") -> str:
    """Connexion complète (mot de passe + TOTP). Renvoie le jeton anti-CSRF des formulaires du guichet."""
    page = client.get(f"{GUICHET}/connexion").text
    action, _ = formulaire(page, "kc-form-login")
    page = client.post(action, data={"username": agent, "password": MOT_DE_PASSE}).text
    fichier_totp = SECRETS / f"totp-{agent}"
    if 'id="kc-totp-settings-form"' in page:            # premier passage : enrôlement du TOTP
        action, champs = formulaire(page, "kc-totp-settings-form")
        # Le champ caché contient le secret brut ; les applications TOTP utilisent sa forme base32
        secret = base64.b32encode(champs["totpSecret"].encode()).decode()
        fichier_totp.write_text(secret)
        champs.update(totp=code_neuf(pyotp.TOTP(secret), agent), userLabel="banc")
        r = client.post(action, data=champs)
    else:
        action, _ = formulaire(page, "kc-otp-login-form")
        r = client.post(action, data={"otp": code_neuf(pyotp.TOTP(fichier_totp.read_text()), agent)})
    assert str(r.url) == f"{GUICHET}/", f"connexion échouée : {r.url}"
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


def envoyer(client: httpx.Client, csrf: str, sujet: str, demarche: str) -> httpx.Response:
    """Envoie une demande par le formulaire du guichet ; renvoie la page de résultat."""
    return client.post(f"{GUICHET}/demandes", data={"csrf": csrf, "demarche": demarche, "sujet_ref": sujet})


def texte(page: str) -> str:
    """Texte visible d'une page HTML, sur une ligne."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def reponses_signees(page: str) -> dict[str, dict]:
    """Contenu décodé des réponses signées que le guichet a reçues et vérifiées ({attribut: claims})."""
    return {code: json.loads(html.unescape(contenu))
            for code, contenu in re.findall(r'<pre id="jeton-([^"]+)">(.*?)</pre>', page, re.S)}

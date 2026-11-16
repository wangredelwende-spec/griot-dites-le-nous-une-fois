"""Test de bout en bout du jalon 1, contre la pile qui tourne (docker compose up -d --wait).

Joue le parcours d'un vrai agent : connexion Keycloak (mot de passe + TOTP), demande au guichet,
lecture du résultat. Compte utilisé : agent.banc (Direction des concours, base légale).
Son secret TOTP est créé au premier passage et gardé dans tests/.secrets/ (ignoré par git).

Utilisation :  .venv/Scripts/python tests/e2e_jalon1.py
"""
import base64
import html
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pyotp

RACINE = Path(__file__).resolve().parents[1]
SECRETS = RACINE / "tests/.secrets"
AGENT, MOT_DE_PASSE = "agent.banc", "Agent-Demo-2026!"

# Les noms *.griot.test pointent vers 127.0.0.1, même si le fichier hosts n'est pas encore à jour
_resolution = socket.getaddrinfo
socket.getaddrinfo = lambda hote, *a, **k: _resolution("127.0.0.1" if hote.endswith(".griot.test") else hote, *a, **k)


def autorite_caddy() -> str:
    """Certificat racine de la CA interne de Caddy : le test vérifie vraiment le HTTPS."""
    SECRETS.mkdir(exist_ok=True)
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


def code_neuf(totp: pyotp.TOTP, agent: str = AGENT) -> str:
    """Keycloak refuse qu'un même code serve deux fois : si le dernier passage l'a déjà utilisé,
    on attend la fenêtre de 30 s suivante."""
    dernier = SECRETS / f"dernier-code-{agent}"
    if dernier.exists() and dernier.read_text() == totp.now():
        time.sleep(30 - time.time() % 30 + 1)
    dernier.write_text(totp.now())
    return totp.now()


def connecter(client: httpx.Client, agent: str = AGENT) -> str:
    page = client.get("https://guichet.griot.test/connexion").text
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
    assert str(r.url) == "https://guichet.griot.test/", f"connexion échouée : {r.url}"
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


def demander(client: httpx.Client, csrf: str, sujet: str, demarche: str = "verifier-majorite") -> str:
    r = client.post("https://guichet.griot.test/demandes",
                    data={"csrf": csrf, "demarche": demarche, "sujet_ref": sujet})
    texte = html.unescape(re.sub(r"<[^>]+>", " ", r.text))
    return " ".join(texte.split())


REFUS = "refusé par le registre d'état civil : réponse impossible, s'adresser à l'état civil. Réponse signée par le registre, signature vérifiée"
# (démarche, usager, textes attendus) ; démarches du catalogue (catalogue/demarches.yaml)
CAS = [
    ("verifier-majorite", "BF-0001", ["majeur (18 ans accomplis) : oui Signé par le registre d'état civil, signature vérifiée"]),
    ("verifier-majorite", "BF-0003", ["majeur (18 ans accomplis) : non"]),
    ("verifier-majorite", "BF-0004", [REFUS]),      # vers 1990
    ("verifier-majorite", "BF-0007", [REFUS]),      # décédée : le guichet ne l'apprend pas
    ("verifier-majorite", "BF-0019", [REFUS]),      # doublon
    ("verifier-majorite", "BF-0099", [REFUS]),      # introuvable
    # Concours direct : UNE demande, 3 registres
    ("concours-adjoints", "BF-0001", ["âge de 18 à 37 ans au 31/12/2026 : oui", "nationalité burkinabè : oui",
                                      "casier judiciaire vierge : oui", "Conclusion : toutes les conditions sont vérifiées"]),
    ("concours-adjoints", "BF-0008", ["casier judiciaire vierge : non", "au moins une condition n'est pas remplie"]),
    ("concours-adjoints", "BF-0018", ["nationalité burkinabè : non"]),
    ("concours-adjoints", "BF-0003", ["âge de 18 à 37 ans au 31/12/2026 : non",
                                      "réponse impossible, s'adresser au greffe"]),          # absente du casier ≠ vierge
    ("concours-adjoints", "BF-0013", ["réponse impossible, s'adresser au service de la nationalité"]),
]


def main():
    echecs = 0
    with httpx.Client(verify=autorite_caddy(), follow_redirects=True, timeout=20) as client:
        csrf = connecter(client)
        print("OK  connexion de agent.banc (mot de passe + TOTP)")
        for demarche, sujet, attendus in CAS:
            texte = demander(client, csrf, sujet, demarche)
            # Le détail du casier (« vol », « escroquerie ») et les dates ne doivent jamais apparaître au guichet
            ok = all(a in texte for a in attendus) and not any(m in texte for m in ("vol ", "escroquerie", "2001-03-14"))
            echecs += not ok
            print(f"{'OK ' if ok else 'ÉCHEC'} {demarche} {sujet} -> {' | '.join(attendus)}"
                  + ("" if ok else f"\n      page : {texte[-400:]}"))
    verification = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "/journal/verifier.py"],
                                  cwd=RACINE, capture_output=True, text=True)
    print(verification.stdout.strip())
    sys.exit(1 if echecs or verification.returncode else 0)


if __name__ == "__main__":
    main()

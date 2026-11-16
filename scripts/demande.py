"""Une demande en ligne de commande, faite par un VRAI agent, exactement comme au guichet.

    .venv\\Scripts\\python scripts\\demande.py --demarche concours-adjoints --usager BF-0001

Le script demande au clavier l'identifiant de l'agent, son mot de passe (caché) puis son code TOTP.
RIEN n'est enregistré : ni mot de passe, ni code, ni jeton, ni résultat (tout reste en mémoire le temps
de la demande). Il passe par le guichet (https://guichet.griot.test) : mêmes règles, même journal,
mêmes limites que dans le navigateur. Le médiateur n'est pas joignable directement (réseau interne).

Le TOTP doit déjà être enrôlé : se connecter une première fois au guichet avec le navigateur.
"""
import argparse
import getpass
import re
import sys

import httpx

from client_guichet import GUICHET, autorite_caddy, formulaire, texte


def contenu(page: str) -> str:
    """Texte visible de la partie principale de la page (sans l'en-tête)."""
    principal = re.search(r"<main>(.*?)</main>", page, re.S)
    principal = principal.group(1) if principal else page
    # Sans le contenu décodé des réponses signées (visible au guichet, dans « réponse signée reçue »)
    return texte(re.sub(r"<details.*?</details>", " ", principal, flags=re.S))


def connecter(client: httpx.Client) -> str:
    """Connexion Keycloak : identifiant + mot de passe, puis code TOTP. Renvoie le jeton anti-CSRF du guichet."""
    page = client.get(f"{GUICHET}/connexion").text
    action, _ = formulaire(page, "kc-form-login")
    identifiant = input("Identifiant de l'agent : ").strip()
    page = client.post(action, data={"username": identifiant, "password": getpass.getpass("Mot de passe : ")}).text
    if 'id="kc-totp-settings-form"' in page:
        raise SystemExit("Ce compte n'a pas encore de TOTP : connectez-vous d'abord une fois au guichet avec le "
                         "navigateur pour scanner le QR code.")
    if 'id="kc-otp-login-form"' not in page:
        raise SystemExit("Connexion refusée (identifiant ou mot de passe incorrect, ou compte bloqué).")
    action, _ = formulaire(page, "kc-otp-login-form")
    r = client.post(action, data={"otp": input("Code TOTP (6 chiffres) : ").strip()})
    if str(r.url) != f"{GUICHET}/":
        raise SystemExit("Connexion refusée (code TOTP incorrect, ou compte qui n'est pas un agent de guichet).")
    connecte = re.search(r'<span class="connecte">(.*?)</span>', r.text)
    print("Connecté : " + texte(connecte.group(1) if connecte else identifiant))
    return r.text


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Demande au guichet, par un vrai agent (mot de passe + TOTP).")
    parser.add_argument("--demarche", required=True, help="code de la démarche (catalogue/demarches.yaml)")
    parser.add_argument("--usager", required=True, help="identifiant de l'usager, ex. BF-0001")
    args = parser.parse_args()

    with httpx.Client(verify=autorite_caddy(), follow_redirects=True, timeout=30) as client:
        accueil = connecter(client)
        # Le guichet ne propose que les démarches du catalogue ouvertes au service de l'agent
        proposees = re.findall(r'name="demarche" value="([^"]+)"', accueil)
        if args.demarche not in proposees:
            raise SystemExit(f"Démarche « {args.demarche} » non proposée à votre service. "
                             f"Démarches possibles : {', '.join(proposees)}")
        csrf = re.search(r'name="csrf" value="([^"]+)"', accueil).group(1)
        r = client.post(f"{GUICHET}/demandes", data={"csrf": csrf, "demarche": args.demarche,
                                                     "sujet_ref": args.usager})
        print("\n" + contenu(r.text))
        # Démarche avec consentement : on actualise à la demande, comme le bouton du guichet
        while "En attente de l'usager" in r.text:
            if input("\nEntrée pour actualiser, « q » pour quitter : ").strip().lower() == "q":
                break
            r = client.get(str(r.url))
            print("\n" + contenu(r.text))
        client.post(f"{GUICHET}/deconnexion", data={"csrf": csrf})    # ferme aussi la session Keycloak


if __name__ == "__main__":
    main()

r"""Clics de la vidéo de 3 minutes (Playwright + Microsoft Edge installé, fenêtre visible 1920x1080).

Le script NE FILME PAS : un humain filme l'écran et fait la voix off. Entre chaque partie, le script attend la touche
Entrée dans le terminal (le temps de lancer l'enregistrement, de parler, de couper).

    .venv\Scripts\python -m pip install playwright==1.58.0      (une fois ; Edge est déjà installé, rien à télécharger)
    .venv\Scripts\python scripts\remise_a_zero.py               (avant de filmer : historiques vides)
    .venv\Scripts\python scripts\video_demo.py

Préparation (non filmée) : connexion de l'agent du concours au guichet (Keycloak : mot de passe, puis code TOTP).
    LE CODE TOTP N'EST PAS AUTOMATISÉ : c'est l'authentification forte de l'agent. Le script remplit l'identifiant et
    le mot de passe de démonstration, puis attend que l'humain tape le code à 6 chiffres de son application TOTP dans
    la fenêtre (à la toute première connexion : scanner le QR code, puis taper le code).
1) Guichet-agent : concours direct pour la citoyenne BF-0001 (Aminata) -> verdict affiché 8 s.
2) Registre du casier éteint (resilience/panne.py) -> nouvelle demande -> « démarche en attente » affiché 6 s, puis le
   registre est remis en mode normal (toujours, même si le script est interrompu).
3) Portail citoyen : connexion simulée (70000001 / 1234), accueil avec « Bonjour », compteur et liste, détail de la
   consultation du concours, puis le badge « Journal intègre ✓ ».

Les noms *.griot.test sont envoyés vers 127.0.0.1 par Edge lui-même (--host-resolver-rules) : pas besoin de modifier
le fichier hosts. Le certificat HTTPS vient de l'autorité INTERNE de Caddy, inconnue d'Edge : le script l'accepte pour
cette fenêtre seulement (ignore_https_errors). Registres simulés, données fictives.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

RACINE = Path(__file__).resolve().parents[1]
GUICHET = "https://guichet.griot.test"
PORTAIL = "https://usager.griot.test/portail"
MOT_DE_PASSE_DEMO = "Agent-Demo-2026!"          # mot de passe de DÉMONSTRATION (socle/keycloak/realm-griot.json)


def attendre_entree(message: str):
    input(f"\n>>> {message}\n    Entrée pour continuer... ")


def panne(registre: str, mode: str):
    subprocess.run([sys.executable, str(RACINE / "resilience/panne.py"), registre, mode], cwd=RACINE, check=True,
                   capture_output=True)


def montrer(page: Page, selecteur: str, secondes: float):
    """Fait défiler jusqu'à l'élément, puis le laisse à l'écran."""
    element = page.locator(selecteur).first
    element.scroll_into_view_if_needed()
    element.hover()
    time.sleep(secondes)


# --- Préparation : connexion de l'agent (le code TOTP est tapé par l'humain) ---

def connecter_agent(page: Page, agent: str):
    page.goto(f"{GUICHET}/connexion")
    page.fill("#username", agent)
    page.fill("#password", MOT_DE_PASSE_DEMO)
    page.click("#kc-login")
    page.wait_for_load_state()
    if page.url.startswith(GUICHET):
        return
    if page.locator("#kc-totp-settings-form").count():
        print("    Première connexion de ce compte : scannez le QR code avec l'application TOTP, puis tapez le code.")
    print("    Tapez le code TOTP à 6 chiffres dans la fenêtre d'Edge et validez (le script attend, 3 minutes au plus).")
    page.wait_for_url(f"{GUICHET}/", timeout=180_000)


def demande_concours(page: Page, citoyen: str):
    page.goto(f"{GUICHET}/")
    page.check("input[name=demarche][value=concours-direct]")
    page.fill("#sujet_ref", citoyen)
    page.click("form[action='/demandes'] button")
    page.wait_for_url(f"{GUICHET}/demandes/**")


# --- Les 3 parties filmées ---

def partie_1_guichet(page: Page, citoyen: str):
    demande_concours(page, citoyen)
    montrer(page, "text=Conclusion", 8)


def partie_2_registre_eteint(page: Page, citoyen: str):
    panne("casier", "eteint")
    try:
        time.sleep(2)                     # le registre est recréé avec PANNE=eteint
        demande_concours(page, citoyen)
        montrer(page, "text=démarche en attente", 6)
    finally:
        panne("casier", "normal")
        print("    Registre du casier remis en mode normal.")


def partie_3_portail(page: Page, numero: str, pin: str):
    page.goto(PORTAIL)
    page.fill("#numero", numero)
    page.fill("#pin", pin)
    page.click("form[action$='/connexion'] button")
    page.wait_for_selector(".compteur")
    time.sleep(3)                                   # « Bonjour, Aminata » et la légende
    montrer(page, ".compteur", 3)                   # « Vos informations ont été consultées N fois »
    montrer(page, "ul.liste", 4)                    # qui, quoi, quand, pourquoi, statut
    page.locator("ul.liste a", has_text="concours").first.click()      # détail de la consultation du concours
    page.wait_for_selector("dl.carte")
    time.sleep(6)
    page.go_back()
    page.wait_for_selector(".badge")
    page.evaluate("window.scrollTo(0, 0)")
    montrer(page, ".badge", 5)                      # « Journal intègre ✓ — vérifié à HH h MM »


def main():
    parser = argparse.ArgumentParser(description="Clics de la vidéo (Edge visible) ; un humain filme.")
    parser.add_argument("--agent", default="issa.sawadogo", help="agent du concours (groupe Direction des concours)")
    parser.add_argument("--citoyen", default="BF-0001", help="citoyenne de la démarche filmée (Aminata)")
    parser.add_argument("--citoyen-panne", default="BF-0002", help="citoyen de la démarche pendant la panne")
    parser.add_argument("--numero", default="70000001", help="numéro de démonstration du portail (BF-0001)")
    parser.add_argument("--pin", default="1234", help="PIN de démonstration du portail")
    parser.add_argument("--lenteur", type=int, default=400, help="pause entre deux actions, en ms (slow_mo)")
    args = parser.parse_args()

    with sync_playwright() as p:
        navigateur = p.chromium.launch(
            channel="msedge", headless=False, slow_mo=args.lenteur,
            args=["--host-resolver-rules=MAP *.griot.test 127.0.0.1", "--window-position=0,0",
                  "--window-size=1920,1080"])
        contexte = navigateur.new_context(viewport={"width": 1920, "height": 1080}, ignore_https_errors=True,
                                          locale="fr-FR")
        page = contexte.new_page()
        try:
            attendre_entree(f"Préparation (non filmée) : connexion de {args.agent} au guichet")
            connecter_agent(page, args.agent)
            page.goto(f"{GUICHET}/")
            attendre_entree(f"Partie 1 : guichet, concours direct pour {args.citoyen}")
            partie_1_guichet(page, args.citoyen)
            attendre_entree("Partie 2 : registre du casier éteint")
            partie_2_registre_eteint(page, args.citoyen_panne)
            attendre_entree("Partie 3 : portail du citoyen")
            partie_3_portail(page, args.numero, args.pin)
            attendre_entree("Fin : fermer Edge")
        finally:
            navigateur.close()


if __name__ == "__main__":
    main()

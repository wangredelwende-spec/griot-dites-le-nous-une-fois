"""Test de bout en bout du jalon 1, contre la pile qui tourne (docker compose up -d --wait).

Joue le parcours d'un vrai agent : connexion Keycloak (mot de passe + TOTP), demande au guichet,
lecture du résultat. Compte utilisé : agent.banc (Direction des concours, base légale).
Son secret TOTP est créé au premier passage et gardé dans tests/.secrets/ (ignoré par git).

Utilisation :  .venv/Scripts/python tests/e2e_jalon1.py
(connexion : scripts/client_guichet.py)
"""
import subprocess
import sys
from pathlib import Path

import httpx

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "scripts"))
from client_guichet import autorite_caddy, connecter, envoyer, texte  # noqa: E402


def demander(client: httpx.Client, csrf: str, sujet: str, demarche: str = "verifier-majorite") -> str:
    return texte(envoyer(client, csrf, sujet, demarche).text)


REFUS = "refusé par le registre d'état civil : réponse impossible, s'adresser à l'état civil. Réponse signée par le registre, signature vérifiée"
# (démarche, usager, textes attendus) ; démarches du catalogue (consentement-minimisation/catalogue/demarches.yaml)
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

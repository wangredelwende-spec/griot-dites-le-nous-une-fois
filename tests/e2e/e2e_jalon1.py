"""Test de bout en bout du jalon 1, contre la pile qui tourne (docker compose up -d --wait).

Joue le parcours d'un vrai agent : connexion Keycloak (mot de passe + TOTP), demande au guichet,
lecture du résultat. Compte utilisé : agent.banc (Direction des concours, base légale). Registres selon le contrat.
Son secret TOTP est créé au premier passage et gardé dans tests/.secrets/ (ignoré par git).

Utilisation :  .venv/Scripts/python tests/e2e/e2e_jalon1.py
(connexion : scripts/client_guichet.py)
"""
import subprocess
import sys
from pathlib import Path

import httpx

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts"))
from client_guichet import autorite_caddy, connecter, envoyer, texte  # noqa: E402


def demander(client: httpx.Client, csrf: str, sujet: str, demarche: str = "concours-direct") -> str:
    return texte(envoyer(client, csrf, sujet, demarche).text)


# (démarche, usager, textes attendus au guichet) ; citoyens de registres/donnees/citoyens-fictifs.yaml
CAS = [
    # Concours direct : UNE demande, 3 registres, base légale
    ("concours-direct", "BF-0002", ["majeur (18 ans accomplis) : oui", "nationalité burkinabè : oui",
                                    "casier judiciaire vierge : oui", "toutes les conditions sont vérifiées"]),
    ("concours-direct", "BF-0003", ["majeur (18 ans accomplis) : non"]),                     # mineure
    ("concours-direct", "BF-0004", ["casier judiciaire vierge : non", "au moins une condition n'est pas remplie"]),
    ("concours-direct", "BF-0007", ["nationalité burkinabè : non"]),                         # non burkinabè
    ("concours-direct", "BF-0009", ["réponse impossible, s'adresser au registre d'état civil"]),   # décédée : rien de plus
    ("concours-direct", "BF-4242", ["citoyen inconnu"]),
]


def main():
    echecs = 0
    with httpx.Client(verify=autorite_caddy(), follow_redirects=True, timeout=20) as client:
        csrf = connecter(client)
        print("OK  connexion de agent.banc (mot de passe + TOTP)")
        for demarche, sujet, attendus in CAS:
            texte = demander(client, csrf, sujet, demarche)
            # Le détail du casier (« vol », « escroquerie ») et les dates ne doivent jamais apparaître au guichet
            ok = all(a in texte for a in attendus) and not any(m in texte for m in ("1998-07-02", "2012-05-20", "Koudougou", "Hamidou", "décéd"))
            echecs += not ok
            print(f"{'OK ' if ok else 'ÉCHEC'} {demarche} {sujet} -> {' | '.join(attendus)}"
                  + ("" if ok else f"\n      page : {texte[-400:]}"))
    verification = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "/journal/verifier.py"],
                                  cwd=RACINE, capture_output=True, text=True)
    print(verification.stdout.strip())
    sys.exit(1 if echecs or verification.returncode else 0)


if __name__ == "__main__":
    main()

"""Interrupteur de panne d'un registre simulé (banc de pannes, démonstration devant le jury).

La panne est une VARIABLE D'ENVIRONNEMENT du registre (PANNE, lue à chaque appel) :
    python resilience/panne.py etat-civil lent           # répond après 10 s (la passerelle abandonne à 2 s, 1 réessai)
    python resilience/panne.py etat-civil eteint         # répond 503 : registre éteint
    python resilience/panne.py etat-civil non_conforme   # réponse qui ne respecte pas le contrat (rejetée)
    python resilience/panne.py etat-civil coupe          # conteneur arrêté (docker compose stop)
    python resilience/panne.py etat-civil normal         # tout revient à la normale
    python resilience/panne.py                           # état de chaque registre

Registres : etat-civil, nationalite, casier. Changer la variable RECRÉE le conteneur du registre (docker compose up -d
--no-build --no-deps : ni reconstruction d'image, ni suppression de volume). Sans cette commande, un « docker compose
up -d » ultérieur remet le registre en mode normal (la variable n'est pas écrite dans un fichier).
Ancien nom accepté : « corrompu » = non_conforme.
"""
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRES = ("etat-civil", "nationalite", "casier")
MODES = ("normal", "lent", "eteint", "non_conforme", "coupe")


def variable(registre: str) -> str:
    """Nom de la variable lue par docker-compose.yml : PANNE_ETAT_CIVIL, PANNE_NATIONALITE, PANNE_CASIER."""
    return "PANNE_" + registre.upper().replace("-", "_")


def compose(*arguments: str, environnement: dict | None = None, verifier: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *arguments], cwd=RACINE, capture_output=True, text=True,
                          check=verifier, env={**os.environ, **(environnement or {})})


def en_marche(service: str) -> bool:
    return bool(compose("ps", "-q", "--status", "running", service).stdout.strip())


def etat(registre: str) -> str:
    service = f"registre-{registre}"
    if not en_marche(service):
        return "coupe"
    r = compose("exec", "-T", service, "printenv", "PANNE", verifier=False)
    return r.stdout.strip() or "normal"


def changer(registre: str, mode: str):
    service = f"registre-{registre}"
    if mode == "coupe":
        compose("stop", service)
        return
    # Nouveau conteneur avec la nouvelle valeur de PANNE : même image, mêmes volumes ; --wait attend qu'il soit prêt
    compose("up", "-d", "--no-build", "--no-deps", "--wait", service, environnement={variable(registre): mode})


def main():
    if len(sys.argv) == 1:
        for registre in REGISTRES:
            print(f"{registre:12} {etat(registre)}")
        return
    mode = {"corrompu": "non_conforme"}.get(sys.argv[2], sys.argv[2]) if len(sys.argv) == 3 else ""
    if len(sys.argv) != 3 or sys.argv[1] not in REGISTRES or mode not in MODES:
        sys.exit(f"Utilisation : python resilience/panne.py <{'|'.join(REGISTRES)}> <{'|'.join(MODES)}>")
    registre = sys.argv[1]
    changer(registre, mode)
    print(f"Registre {registre} : {etat(registre)}")


if __name__ == "__main__":
    main()

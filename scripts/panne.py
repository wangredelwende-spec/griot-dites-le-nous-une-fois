"""Interrupteur de panne d'un registre simulé (banc de pannes, démonstration devant le jury).

Utilisation :
    python scripts/panne.py etat-civil lent       # répond après 10 s (le médiateur abandonne à 3 s)
    python scripts/panne.py etat-civil corrompu   # réponse modifiée en chemin (signature fausse)
    python scripts/panne.py etat-civil coupe      # conteneur arrêté (docker compose stop)
    python scripts/panne.py etat-civil normal     # tout revient à la normale
    python scripts/panne.py                       # état de chaque registre

Registres : etat-civil, nationalite, casier.
"""
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRES = ("etat-civil", "nationalite", "casier")
MODES = ("normal", "lent", "corrompu", "coupe")


def compose(*arguments: str, verifier: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *arguments], cwd=RACINE, capture_output=True, text=True,
                          check=verifier)


def en_marche(service: str) -> bool:
    return bool(compose("ps", "-q", "--status", "running", service).stdout.strip())


def etat(registre: str) -> str:
    service = f"registre-{registre}"
    if not en_marche(service):
        return "coupe"
    r = compose("exec", "-T", service, "cat", "/tmp/panne", verifier=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "normal"


def changer(registre: str, mode: str):
    service = f"registre-{registre}"
    if mode == "coupe":
        compose("stop", service)
        return
    if not en_marche(service):
        compose("start", service)
        compose("up", "-d", "--wait", service)          # attend que le registre soit prêt
    if mode == "normal":
        compose("exec", "-T", service, "rm", "-f", "/tmp/panne")
    else:
        compose("exec", "-T", service, "sh", "-c", f"echo {mode} > /tmp/panne")


def main():
    if len(sys.argv) == 1:
        for registre in REGISTRES:
            print(f"{registre:12} {etat(registre)}")
        return
    if len(sys.argv) != 3 or sys.argv[1] not in REGISTRES or sys.argv[2] not in MODES:
        sys.exit(f"Utilisation : python scripts/panne.py <{'|'.join(REGISTRES)}> <{'|'.join(MODES)}>")
    registre, mode = sys.argv[1], sys.argv[2]
    changer(registre, mode)
    print(f"Registre {registre} : {etat(registre)}")


if __name__ == "__main__":
    main()

"""Recharge les images sauvegardées par sauvegarder_hors_ligne.py, puis relance tout SANS RÉSEAU.

    python scripts\\charger_hors_ligne.py hors_ligne\\griot-images-<date>.tar
    python scripts\\charger_hors_ligne.py hors_ligne\\griot-images-<date>.tar --sans-demarrer

1. Vérifie l'empreinte SHA-256 du fichier (fichier abîmé ou modifié : on s'arrête).
2. docker load : toutes les images reviennent, avec leurs noms et versions.
3. docker compose up --no-build --pull never : aucune construction, aucun téléchargement.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from sauvegarder_hors_ligne import RACINE, empreinte, executer


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Recharge les images du projet sans réseau.")
    parser.add_argument("fichier", type=Path)
    parser.add_argument("--sans-demarrer", action="store_true", help="charger seulement, sans lancer la pile")
    args = parser.parse_args()
    fichier = args.fichier if args.fichier.is_absolute() else RACINE / args.fichier

    attendu = fichier.with_suffix(".tar.sha256").read_text(encoding="utf-8").split()[0]
    print("Vérification de l'empreinte…", flush=True)
    if empreinte(fichier) != attendu:
        raise SystemExit("ERREUR : empreinte différente : fichier abîmé ou modifié. Rien n'a été chargé.")
    print(f"OK  sha256 {attendu}")

    print("docker load…", flush=True)
    print(executer("docker", "load", "-i", str(fichier)).strip())
    images = fichier.with_suffix(".tar.images").read_text(encoding="utf-8").split()
    presentes = set(executer("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}").split())
    manquantes = [i for i in images if i not in presentes]
    if manquantes:
        raise SystemExit(f"ERREUR : images absentes après chargement : {', '.join(manquantes)}")
    print(f"OK  {len(images)} images présentes")

    if not args.sans_demarrer:
        print("Démarrage sans construction ni téléchargement…", flush=True)
        r = subprocess.run(["docker", "compose", "up", "-d", "--wait", "--no-build", "--pull", "never"], cwd=RACINE)
        if r.returncode:
            raise SystemExit("ERREUR au démarrage (voir ci-dessus).")
        print("OK  pile démarrée hors ligne (docker compose ps)")


if __name__ == "__main__":
    main()

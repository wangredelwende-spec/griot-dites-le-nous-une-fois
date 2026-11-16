"""Sauvegarde HORS LIGNE de toutes les images du projet (y compris l'OCR) dans un seul fichier.

    python scripts\\sauvegarder_hors_ligne.py              # -> hors_ligne\\griot-images-<date>.tar + .sha256

À faire tant qu'on a le réseau (après chaque reconstruction). Si le réseau ou Docker Hub manque le jour J,
ou sur une autre machine : python scripts\\charger_hors_ligne.py hors_ligne\\griot-images-<date>.tar
La liste des images vient de docker-compose.yml (versions épinglées), jamais écrite à la main.
Le dossier hors_ligne\\ est ignoré par git (fichier de plusieurs centaines de Mo).
"""
import hashlib
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def executer(*commande: str) -> str:
    r = subprocess.run(list(commande), cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"Échec de « {' '.join(commande)} » : {r.stderr.strip()[-400:]}")
    return r.stdout


def empreinte(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # Toutes les images, y compris celles des profils (OCR)
    images = sorted(set(executer("docker", "compose", "--profile", "ocr", "config", "--images").split()))
    presentes = set(executer("docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}").split())
    manquantes = [i for i in images if i not in presentes]
    if manquantes:
        raise SystemExit(f"Images absentes (construire ou télécharger d'abord) : {', '.join(manquantes)}\n"
                         "  docker compose build ; docker compose --profile ocr build ocr ; docker compose pull")
    dossier = RACINE / "hors_ligne"
    dossier.mkdir(exist_ok=True)
    sortie = dossier / f"griot-images-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.tar"
    print(f"{len(images)} images :\n  " + "\n  ".join(images) + f"\nÉcriture de {sortie.name}…", flush=True)
    executer("docker", "save", "-o", str(sortie), *images)
    somme = empreinte(sortie)
    (sortie.with_suffix(".tar.sha256")).write_text(f"{somme}  {sortie.name}\n", encoding="utf-8")
    (sortie.with_suffix(".tar.images")).write_text("\n".join(images) + "\n", encoding="utf-8")
    print(f"OK : {sortie.relative_to(RACINE)} ({sortie.stat().st_size / 1e6:.0f} Mo), sha256 {somme}")
    print(f"Recharger sans réseau : python scripts\\charger_hors_ligne.py {sortie.relative_to(RACINE)}")


if __name__ == "__main__":
    main()

"""Vérifie l'intégrité du journal chaîné du médiateur, et éventuellement un reçu.

Utilisation (le journal est dans le volume du médiateur) :
    docker compose exec mediateur python /journal/verifier.py
    docker compose exec mediateur python /journal/verifier.py --recu 3f9a1c0b

Pour chaque ligne, dans l'ordre : recalcule hash = SHA-256(prev_hash + JSON canonique de la ligne
sans « hash ») et vérifie que prev_hash est bien l'empreinte de la ligne précédente.
Un reçu (empreinte remise à l'usager, ou ses 8 premiers caractères) doit se retrouver dans le journal :
si un administrateur avait recalculé toute la chaîne, les reçus déjà remis ne correspondraient plus.
"""
import argparse
import hashlib
import json
import sqlite3
import sys

ZEROS = "0" * 64


def empreinte(ligne: dict) -> str:
    """Même calcul que mediateur/app/journal.py (clés triées, séparateurs compacts, UTF-8)."""
    sans_hash = {k: v for k, v in ligne.items() if k != "hash"}
    canonique = json.dumps(sans_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((ligne["prev_hash"] + canonique).encode("utf-8")).hexdigest()


def verifier(chemin: str) -> tuple[bool, str, list[dict]]:
    base = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)    # lecture seule
    base.row_factory = sqlite3.Row
    lignes = [dict(l) for l in base.execute("SELECT * FROM journal ORDER BY n")]
    precedente = ZEROS
    for attendu, ligne in enumerate(lignes, start=1):
        if ligne["n"] != attendu:
            return False, f"Ligne {attendu} supprimée (on passe directement à la ligne {ligne['n']})", lignes
        if empreinte(ligne) != ligne["hash"]:
            return False, f"Ligne {attendu} modifiée", lignes
        if ligne["prev_hash"] != precedente:
            return False, f"Ligne {attendu - 1} modifiée (son empreinte a été recalculée : chaînage rompu)", lignes
        precedente = ligne["hash"]
    return True, f"Journal intègre : {len(lignes)} lignes", lignes


def main():
    parser = argparse.ArgumentParser(description="Vérifie le journal chaîné du médiateur.")
    parser.add_argument("chemin", nargs="?", default="/donnees/mediateur.sqlite3")
    parser.add_argument("--recu", help="empreinte d'un reçu (au moins 8 caractères)")
    args = parser.parse_args()

    integre, message, lignes = verifier(args.chemin)
    print(("OK  " if integre else "ERREUR  ") + message)
    if args.recu:
        recu = args.recu.strip().lower()
        if len(recu) < 8:
            sys.exit("Un reçu compte au moins 8 caractères.")
        trouvees = [l for l in lignes if l["hash"].startswith(recu)]
        if trouvees:
            l = trouvees[0]
            print(f"OK  Reçu retrouvé : ligne {l['n']}, {l['ts']}, {l['evenement']} ({l['demandeur']})")
        else:
            print("ERREUR  Reçu introuvable : le journal a été réécrit ou le reçu est faux")
            integre = False
    sys.exit(0 if integre else 1)


if __name__ == "__main__":
    main()

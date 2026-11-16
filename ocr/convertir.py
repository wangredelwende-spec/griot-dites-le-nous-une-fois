"""PDF SCANNÉ -> CSV, une seule fois, à l'import des données du jury (conteneur OCR, profil « ocr »).

    docker compose --profile ocr run --rm ocr /donnees/etat_civil_scanne.pdf
    (le dossier donnees_jury/ est monté sur /donnees ; le CSV est écrit à côté du PDF)

1. pdftoppm : chaque page devient une image (300 points par pouce, niveaux de gris).
2. tesseract (langue « fra ») : chaque mot reconnu, avec sa position et sa CONFIANCE (0 à 100).
3. La première ligne du tableau donne les colonnes (mots séparés par un grand espace = colonnes différentes) ;
   chaque mot des lignes suivantes va dans la colonne qui est au-dessus de lui.
4. Règle d'or : une case dont UN mot a une confiance trop basse reste VIDE (donc refus « donnée insuffisante »
   au registre). On ne devine jamais une date ou un identifiant mal lu.
5. Empreintes SHA-256 du PDF d'origine et du CSV produit, écrites dans <fichier>.provenance.json.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def mots_de_la_page(image: Path) -> list[dict]:
    """Mots reconnus par Tesseract (sortie TSV) : texte, position, confiance, numéro de ligne."""
    tsv = subprocess.run(["tesseract", str(image), "stdout", "-l", "fra", "--psm", "6", "tsv"],
                         capture_output=True, text=True, check=True).stdout
    lignes = list(csv.DictReader(tsv.splitlines(), delimiter="\t", quoting=csv.QUOTE_NONE))
    return [{"texte": l["text"].strip(), "gauche": int(l["left"]), "largeur": int(l["width"]),
             "confiance": float(l["conf"]), "ligne": (l["block_num"], l["par_num"], l["line_num"]),
             "haut": int(l["top"])}
            for l in lignes if l["level"] == "5" and l["text"].strip()]


def par_ligne(mots: list[dict]) -> list[list[dict]]:
    lignes = {}
    for m in mots:
        lignes.setdefault(m["ligne"], []).append(m)
    return [sorted(l, key=lambda m: m["gauche"]) for l in sorted(lignes.values(), key=lambda l: l[0]["haut"])]


def colonnes_de_l_entete(entete: list[dict], ecart: int) -> list[tuple[str, int]]:
    """Mots de l'en-tête séparés de plus de « ecart » pixels = colonnes différentes. Renvoie (nom, x de début)."""
    colonnes = []
    for m in entete:
        if colonnes and m["gauche"] - colonnes[-1][2] < ecart:
            nom, debut, _fin = colonnes[-1]
            colonnes[-1] = (f"{nom} {m['texte']}", debut, m["gauche"] + m["largeur"])
        else:
            colonnes.append((m["texte"], m["gauche"], m["gauche"] + m["largeur"]))
    return [(nom, debut) for nom, debut, _ in colonnes]


def convertir(pdf: Path, seuil: float, ecart: int) -> tuple[Path, dict]:
    with tempfile.TemporaryDirectory() as dossier:
        subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(pdf), f"{dossier}/page"], check=True)
        pages = sorted(Path(dossier).glob("page*.png"))
        colonnes, resultat, vides = None, [], 0
        for image in pages:
            for ligne in par_ligne(mots_de_la_page(image)):
                if colonnes is None:
                    colonnes = colonnes_de_l_entete(ligne, ecart)
                    noms = [n for n, _ in colonnes]
                    continue
                cases = {n: [] for n in noms}
                for m in ligne:
                    # la colonne la plus à droite qui commence avant ce mot (petite tolérance)
                    nom = next((n for n, x in reversed(colonnes) if m["gauche"] >= x - ecart // 2), noms[0])
                    cases[nom].append(m)
                valeurs = []
                for n in noms:
                    if any(m["confiance"] < seuil for m in cases[n]):
                        valeurs.append("")          # douteux : VIDE, jamais deviné
                        vides += 1
                    else:
                        valeurs.append(" ".join(m["texte"] for m in cases[n]))
                if valeurs != noms and any(valeurs):    # en-tête répété sur une autre page : ignoré
                    resultat.append(valeurs)
    if colonnes is None:
        raise SystemExit("Aucun texte reconnu dans ce PDF.")
    sortie = pdf.with_suffix(".csv")
    with open(sortie, "w", encoding="utf-8", newline="") as f:
        ecrivain = csv.writer(f, delimiter=";")
        ecrivain.writerow(noms)
        ecrivain.writerows(resultat)
    provenance = {
        "origine": pdf.name, "sha256_origine": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "produit": sortie.name, "sha256_produit": hashlib.sha256(sortie.read_bytes()).hexdigest(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pages": len(pages),
        "lignes": len(resultat), "colonnes": noms, "seuil_confiance": seuil, "cases_laissees_vides": vides,
        "outil": "tesseract (fra, psm 6) + pdftoppm 300 dpi",
    }
    pdf.with_suffix(".provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    return sortie, provenance


def main():
    parser = argparse.ArgumentParser(description="PDF scanné -> CSV (une seule fois, à l'import).")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--seuil", type=float, default=80, help="confiance minimale d'un mot (0-100)")
    parser.add_argument("--ecart", type=int, default=60, help="espace (pixels à 300 dpi) qui sépare deux colonnes")
    args = parser.parse_args()
    sortie, p = convertir(args.pdf, args.seuil, args.ecart)
    print(f"{p['lignes']} lignes, colonnes {p['colonnes']}, {p['cases_laissees_vides']} cases douteuses laissées VIDES")
    print(f"origine  {p['origine']} sha256 {p['sha256_origine']}")
    print(f"produit  {p['produit']} sha256 {p['sha256_produit']}")
    print("À RELIRE avant usage (inspecter_donnees.py), puis décrire le CSV dans l'adaptateur (type: csv).")


if __name__ == "__main__":
    sys.exit(main())

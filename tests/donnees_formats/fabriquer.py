"""Fabrique les petits jeux FICTIFS aux formats que le jury pourrait fournir (preuve : aucun changement de code,
seulement les fichiers YAML de tests/adaptateurs_formats/).

    .venv\\Scripts\\python tests\\donnees_formats\\fabriquer.py

Mêmes personnes que registres_sim/donnees_fictives, écrites autrement :
- etat_civil.xlsx      : Excel, en-têtes en français, dates jj/mm/aaaa (texte) et une vraie date Excel ;
- nationalite.json     : JSON imbriqué (registre.personnes[].identite.nip…), valeurs écrites de plusieurs façons ;
- casier.csv           : CSV Windows-1252, séparateur « ; », accents ;
- etat_civil.db / etat_civil.sql : SQLite et dump SQL ;
- etat_civil.pdf       : PDF TEXTE (tableau) ; etat_civil_scanne.pdf : PDF SCANNÉ (image seule, pour l'OCR).
"""
import sqlite3
from datetime import datetime
from pathlib import Path

ICI = Path(__file__).resolve().parent

# nip, nom, prénoms, date de naissance (jj/mm/aaaa ou partielle), date de décès
ETAT_CIVIL = [
    ("BF-0001", "KABORÉ", "Aminata", "14/03/2001", ""),
    ("BF-0003", "SAWADOGO", "Fatimata", "21/05/2010", ""),
    ("BF-0004", "ZONGO", "Issouf", "vers 1990", ""),
    ("BF-0007", "TRAORÉ", "Mariam", "10/01/1950", "01/06/2024"),
    ("BF-0011", "KONATÉ", "Awa", "2004", ""),
    ("BF-0019", "SANOU", "Jean", "05/05/1991", ""),
    ("BF-0019", "SANOU", "Jean", "15/05/1991", ""),
]


def excel():
    import openpyxl
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "Etat civil"
    feuille.append(["N° d'identification", "Nom", "Prénom(s)", "Date de naissance", "Date de décès"])
    for ligne in ETAT_CIVIL:
        feuille.append(list(ligne))
    feuille.append(["BF-0002", "OUÉDRAOGO", "Moussa", datetime(1998, 7, 2), None])   # vraie date Excel
    classeur.save(ICI / "etat_civil.xlsx")


def json_imbrique():
    import json
    personnes = [
        {"identite": {"nip": "BF-0001", "nom": "KABORÉ"}, "nationalite": {"libelle": "Burkinabè"}},
        {"identite": {"nip": "BF-0002", "nom": "OUÉDRAOGO"}, "nationalite": {"libelle": "BF"}},
        {"identite": {"nip": "BF-0006", "nom": "COMPAORÉ"}, "nationalite": {"libelle": "burkinabe"}},
        {"identite": {"nip": "BF-0018", "nom": "OUATTARA"}, "nationalite": {"libelle": "Ivoirienne"}},
        {"identite": {"nip": "BF-0020", "nom": "ZOUNGRANA"}, "nationalite": {"libelle": ["Ivoirienne", "Burkinabè"]}},
        {"identite": {"nip": "BF-0013", "nom": "SOMÉ"}, "nationalite": {"libelle": ""}},
        {"identite": {"nip": "BF-0014", "nom": "BAMOGO"}, "nationalite": {"libelle": "XX"}},
    ]
    (ICI / "nationalite.json").write_text(json.dumps({"registre": {"version": 1, "personnes": personnes}},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")


def csv_windows():
    lignes = ["NIP;Nom;Prénoms;Nb condamnations;Peines complémentaires",
              "BF-0001;KABORÉ;Aminata;0;Aucune",
              "BF-0005;COMPAORÉ;Salif;1;Aucune",
              "BF-0008;ILBOUDO;Adama;2;Interdiction de sortie du territoire (5 ans)",
              "BF-0015;TIENDRÉBÉOGO;Karim;;"]
    (ICI / "casier.csv").write_bytes(("\r\n".join(lignes) + "\r\n").encode("cp1252"))


def sqlite_et_dump():
    chemin = ICI / "etat_civil.db"
    chemin.unlink(missing_ok=True)
    base = sqlite3.connect(chemin)
    base.execute("CREATE TABLE personnes (nip TEXT, nom TEXT, date_naissance TEXT, date_deces TEXT)")
    base.executemany("INSERT INTO personnes VALUES (?, ?, ?, ?)",
                     [(n, nom, d, dc) for n, nom, _p, d, dc in ETAT_CIVIL])
    base.commit()
    (ICI / "etat_civil.sql").write_text("\n".join(base.iterdump()) + "\n", encoding="utf-8")
    base.close()


def pdf_texte():
    """PDF TEXTE minimal écrit à la main (un tableau quadrillé) : pdfplumber doit y retrouver les colonnes."""
    colonnes = [60, 150, 260, 360, 470]
    entete = ("nip", "nom", "prenoms", "date_naissance", "date_deces")
    lignes = [entete] + ETAT_CIVIL
    haut, pas = 760, 22
    flux = ["0.5 w"]
    for i in range(len(lignes) + 1):                         # lignes horizontales
        y = haut - i * pas
        flux.append(f"{colonnes[0] - 5} {y} m 560 {y} l S")
    for x in colonnes + [565]:                               # lignes verticales
        flux.append(f"{x - 5} {haut} m {x - 5} {haut - len(lignes) * pas} l S")
    for i, ligne in enumerate(lignes):
        y = haut - i * pas - 15
        for x, valeur in zip(colonnes, ligne):
            texte = valeur.encode("cp1252").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            flux.append(f"BT /F1 9 Tf {x} {y} Td ({texte}) Tj ET")
    contenu = "\n".join(flux).encode("latin-1")
    objets = [b"<< /Type /Catalog /Pages 2 0 R >>",
              b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> "
              b"/Contents 5 0 R >>",
              b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
              b"<< /Length " + str(len(contenu)).encode() + b" >>\nstream\n" + contenu + b"\nendstream"]
    sortie = bytearray(b"%PDF-1.4\n")
    positions = []
    for numero, objet in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += f"{numero} 0 obj\n".encode() + objet + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += f"xref\n0 {len(objets) + 1}\n0000000000 65535 f \n".encode()
    sortie += b"".join(f"{p:010d} 00000 n \n".encode() for p in positions)
    sortie += f"trailer\n<< /Size {len(objets) + 1} /Root 1 0 R >>\nstartxref\n{debut_xref}\n%%EOF\n".encode()
    (ICI / "etat_civil.pdf").write_bytes(bytes(sortie))


def pdf_scanne():
    """PDF SCANNÉ : une IMAGE du tableau, sans aucun texte (il faut l'OCR). Police Arial de Windows."""
    from PIL import Image, ImageDraw, ImageFont
    police = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    colonnes = [80, 380, 700, 1010, 1380]
    lignes = [("nip", "nom", "prenoms", "date_naissance", "date_deces")] + ETAT_CIVIL[:5]
    image = Image.new("L", (1700, 200 + 70 * len(lignes)), 255)
    dessin = ImageDraw.Draw(image)
    for i, ligne in enumerate(lignes):
        for x, valeur in zip(colonnes, ligne):
            dessin.text((x, 100 + i * 70), valeur, fill=0, font=police)
    image.save(ICI / "etat_civil_scanne.pdf", resolution=200)


if __name__ == "__main__":
    excel(); json_imbrique(); csv_windows(); sqlite_et_dump(); pdf_texte(); pdf_scanne()
    print("Fichiers fabriqués dans", ICI)

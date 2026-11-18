"""Lecture de la SOURCE d'un registre, décrite dans registres/adaptateurs/<registre>.yaml (« source: »).

Formats : csv, xlsx, json, sqlite, sql (dump), pdf (PDF TEXTE : tableaux lus avec pdfplumber),
api (API HTTP du jury, interrogée à chaque demande). Un PDF SCANNÉ (images) est refusé ici : il est converti
UNE fois en CSV à l'import par le conteneur OCR (profil docker « ocr », voir docs/JOUR_J_DONNEES_JURY.md, retiré le 18/11 : voir l'historique git).

Toutes les valeurs deviennent du texte nettoyé (espaces retirés, vide si absent) : le reste du code ne voit
que des lignes {colonne: texte}. Une cellule vide reste VIDE : on ne devine jamais une valeur.
"""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path


class SourceIndisponible(Exception):
    """La source (API du jury) ne répond pas ou répond mal : le registre se déclare indisponible (non signé)."""


def texte(valeur) -> str:
    """Valeur d'une cellule -> texte. Date Excel -> 2001-03-14 ; nombre entier 3.0 -> « 3 » ; absent -> « »."""
    if valeur is None:
        return ""
    if isinstance(valeur, datetime):
        return valeur.date().isoformat()
    if isinstance(valeur, date):
        return valeur.isoformat()
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur).strip()


def aplatir(objet: dict, prefixe: str = "") -> dict:
    """JSON imbriqué -> une seule ligne : {"naissance": {"date": "…"}} devient {"naissance.date": "…"}.
    Une liste de valeurs simples devient un texte « a ; b » (ex. deux nationalités)."""
    plat = {}
    for cle, valeur in objet.items():
        nom = f"{prefixe}{str(cle).strip()}"
        if isinstance(valeur, dict):
            plat |= aplatir(valeur, nom + ".")
        elif isinstance(valeur, list) and all(not isinstance(v, (dict, list)) for v in valeur):
            plat[nom] = " ; ".join(texte(v) for v in valeur if texte(v))
        else:
            plat[nom] = valeur
    return plat


def nettoyer(lignes) -> list[dict]:
    return [{k: texte(v) for k, v in aplatir({k: v for k, v in ligne.items() if k is not None}).items()}
            for ligne in lignes]


# --- CSV : séparateur et encodage détectés si « auto » ---

def decoder(brut: bytes, encodage: str) -> str:
    """« auto » : UTF-8 (avec ou sans BOM d'Excel), sinon Windows-1252 (CSV enregistré par Excel en français)."""
    if encodage != "auto":
        return brut.decode(encodage)
    try:
        return brut.decode("utf-8-sig")
    except UnicodeDecodeError:
        return brut.decode("cp1252")


def lire_csv(source: dict) -> list[dict]:
    contenu = decoder(Path(source["chemin"]).read_bytes(), source.get("encodage", "auto"))
    separateur = source.get("separateur", "auto")
    if separateur == "auto":
        entete = contenu.splitlines()[0] if contenu else ""
        separateur = ";" if entete.count(";") >= entete.count(",") else ","
    return nettoyer(csv.DictReader(io.StringIO(contenu, newline=""), delimiter=separateur))


# --- Excel .xlsx (openpyxl, licence MIT) : première ligne = noms des colonnes ---

def lire_xlsx(source: dict) -> list[dict]:
    import openpyxl     # importé ici : inutile pour les autres formats
    classeur = openpyxl.load_workbook(source["chemin"], read_only=True, data_only=True)
    feuille = classeur[source["feuille"]] if source.get("feuille") else classeur.worksheets[0]
    lignes = feuille.iter_rows(values_only=True)
    entete = [texte(c) for c in next(lignes, [])]
    resultat = [dict(zip(entete, l)) for l in lignes if any(c not in (None, "") for c in l)]
    classeur.close()
    return nettoyer(resultat)


# --- JSON : une liste d'objets, éventuellement sous une clé (« liste: personnes ») ---

def extraire_liste(donnees, cle: str | None) -> list:
    if cle:
        for morceau in cle.split("."):
            donnees = donnees[morceau]
    if isinstance(donnees, dict):           # un seul objet = une seule fiche
        donnees = [donnees]
    if not isinstance(donnees, list) or not all(isinstance(d, dict) for d in donnees):
        raise ValueError("JSON : une liste d'objets est attendue (régler « liste: » dans l'adaptateur)")
    return donnees


def lire_json(source: dict) -> list[dict]:
    donnees = json.loads(decoder(Path(source["chemin"]).read_bytes(), source.get("encodage", "auto")))
    return nettoyer(extraire_liste(donnees, source.get("liste")))


# --- SQLite (fichier .db) ou dump SQL (rechargé en mémoire) : une table ou une requête SELECT ---

def lire_table(base: sqlite3.Connection, source: dict) -> list[dict]:
    if source.get("requete"):
        requete = source["requete"]
        if not requete.lstrip().lower().startswith("select"):
            raise ValueError("SQL : seule une requête SELECT est acceptée")
    else:
        requete = f'SELECT * FROM "{source["table"]}"'
    base.row_factory = sqlite3.Row
    return nettoyer(dict(l) for l in base.execute(requete))


def lire_sqlite(source: dict) -> list[dict]:
    base = sqlite3.connect(f"file:{Path(source['chemin']).as_posix()}?mode=ro", uri=True)    # lecture seule
    try:
        return lire_table(base, source)
    finally:
        base.close()


def lire_dump_sql(source: dict) -> list[dict]:
    """Dump SQL (CREATE TABLE + INSERT) rejoué dans une base SQLite EN MÉMOIRE. Un dump propre à MySQL ou
    PostgreSQL peut contenir des instructions que SQLite refuse : le registre refuse alors de démarrer."""
    base = sqlite3.connect(":memory:")
    try:
        base.executescript(decoder(Path(source["chemin"]).read_bytes(), source.get("encodage", "auto")))
        return lire_table(base, source)
    finally:
        base.close()


# --- PDF TEXTE (pdfplumber, licence MIT) : tableaux de toutes les pages, première ligne = noms des colonnes ---

def lire_pdf(source: dict) -> list[dict]:
    import pdfplumber   # importé ici : inutile pour les autres formats
    entete, resultat = None, []
    with pdfplumber.open(source["chemin"]) as pdf:
        if not any((page.extract_text() or "").strip() for page in pdf.pages):
            raise ValueError("PDF sans texte (PDF scanné) : le convertir d'abord avec le conteneur OCR "
                             "(docs/JOUR_J_DONNEES_JURY.md, retiré le 18/11 : voir l'historique git)")
        for page in pdf.pages:
            for tableau in page.extract_tables():
                for ligne in tableau:
                    cellules = [" ".join(texte(c).split()) for c in ligne]     # retours à la ligne dans une case
                    if entete is None:
                        entete = cellules
                    elif cellules != entete and any(cellules):     # en-tête répété sur chaque page : ignoré
                        resultat.append(dict(zip(entete, cellules)))
    if entete is None:
        raise ValueError("PDF : aucun tableau trouvé")
    return nettoyer(resultat)


LECTEURS = {"csv": lire_csv, "xlsx": lire_xlsx, "json": lire_json, "sqlite": lire_sqlite, "sql": lire_dump_sql,
            "pdf": lire_pdf}


def empreinte_fichier(chemin: str) -> str:
    """SHA-256 du fichier source, écrit dans les logs au démarrage : on sait quelle version a été lue."""
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


def lire_source(source: dict) -> list[dict]:
    """Fichier lu une fois au démarrage du registre."""
    if source["type"] not in LECTEURS:
        raise ValueError(f"type de source inconnu : {source['type']} (attendus : {', '.join(LECTEURS)}, api)")
    return LECTEURS[source["type"]](source)


def avec_secrets(valeur: str) -> str:
    """« Bearer {secret:api_jury} » -> le contenu de /run/secrets/api_jury (valeur rangée dans .env, transmise
    par docker compose comme secret). Le secret n'est jamais écrit dans le YAML ni dans les logs."""
    dossier = Path(os.environ.get("GRIOT_SECRETS", "/run/secrets"))
    return re.sub(r"\{secret:([\w-]+)\}", lambda m: (dossier / m[1]).read_text().strip(), valeur)


# --- API HTTP du jury : interrogée à CHAQUE demande, avec un délai maximal ---

def interroger_api(source: dict, sujet_ref: str) -> list[dict]:
    """GET <url> où « {sujet_ref} » est remplacé par l'identifiant. Renvoie les fiches trouvées.
    404 = personne introuvable (liste vide). Délai dépassé, autre erreur, réponse illisible : SourceIndisponible
    (le registre ne devine rien et ne signe rien). Le délai reste sous celui du médiateur (3 s)."""
    url = source["url"].replace("{sujet_ref}", urllib.parse.quote(sujet_ref, safe=""))
    entetes = {nom: avec_secrets(str(v)) for nom, v in (source.get("entetes") or {}).items()}
    requete = urllib.request.Request(avec_secrets(url), headers={"Accept": "application/json", **entetes})
    try:
        with urllib.request.urlopen(requete, timeout=float(source.get("delai", 2))) as r:
            donnees = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise SourceIndisponible(f"API du registre en erreur (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SourceIndisponible("API du registre injoignable ou trop lente")
    except ValueError:
        raise SourceIndisponible("API du registre : réponse illisible")
    try:
        return nettoyer(extraire_liste(donnees, source.get("liste")))
    except (ValueError, KeyError, TypeError):
        raise SourceIndisponible("API du registre : réponse de forme inattendue")

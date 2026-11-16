"""Inspecte des données du jury (format inconnu) et propose un brouillon d'adaptateur YAML.

    .venv\\Scripts\\python scripts\\inspecter_donnees.py donnees_jury\\etat_civil.xlsx
    .venv\\Scripts\\python scripts\\inspecter_donnees.py donnees_jury\\*.csv --proposer-yaml
    .venv\\Scripts\\python scripts\\inspecter_donnees.py "http://api-jury/personnes" --entete "Authorization: Bearer …"

Pour chaque fichier : format, colonnes, nombre de lignes, 3 exemples, cases vides, formats de date, valeurs
distinctes (quand il y en a peu), identifiant probable, doublons, homonymes, CLÉ D'IDENTITÉ proposée (colonne
commune, sinon clé composée nom + prénoms + date de naissance [+ lieu], avec le nombre d'homonymes exacts qui
seraient refusés). Avec plusieurs fichiers : colonnes qui partagent les mêmes valeurs (identifiant commun).
Avec --proposer-yaml, dans donnees_jury/brouillons/ (À RELIRE : « À VÉRIFIER » = suppositions) : un brouillon
d'adaptateur par fichier, le format d'identifiant à mettre dans catalogue/annuaire.yaml, et un brouillon
d'annuaire USSD (numéros et PIN FICTIFS liés à quelques identifiants).
Lit les fichiers avec le MÊME code que les registres (registres_sim/app/sources.py). Ne modifie rien.
"""
import argparse
import importlib.util
import json
import re
from datetime import datetime
import sqlite3
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sources", RACINE / "registres_sim/app/sources.py")
sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sources)

TYPES = {".csv": "csv", ".txt": "csv", ".xlsx": "xlsx", ".json": "json", ".db": "sqlite", ".sqlite": "sqlite",
         ".sqlite3": "sqlite", ".sql": "sql", ".pdf": "pdf"}
# Formes de date reconnues : (expression, nom affiché, format strptime proposé)
DATES = [(r"\d{2}/\d{2}/\d{4}", "jj/mm/aaaa", "%d/%m/%Y"), (r"\d{2}-\d{2}-\d{4}", "jj-mm-aaaa", "%d-%m-%Y"),
         (r"\d{2}\.\d{2}\.\d{4}", "jj.mm.aaaa", "%d.%m.%Y"), (r"\d{4}-\d{2}-\d{2}", "aaaa-mm-jj (ISO)", None),
         (r"\d{4}-\d{2}", "aaaa-mm (jour manquant)", None), (r"\d{2}/\d{4}", "mm/aaaa (jour manquant)", None),
         (r"\d{4}", "aaaa (année seule)", None), (r"(?i)(vers|env\.?|environ|~)\s*\d{4}", "« vers aaaa » (refus)", None),
         (r"0{1,2}/0{1,2}/\d{4}", "00/00/aaaa (jour et mois inconnus)", None)]
# Colonnes devinées par leur nom (sans accents, minuscules) -> nom utilisé par le code
DEVINETTES = [("naiss", "date_naissance"), ("deces", "date_deces"), ("dece", "date_deces"), ("mort", "date_deces"),
              ("nationalit", "nationalite"), ("condamn", "nombre_condamnations"), ("peine", "peines_complementaires")]
REGISTRES = [("etat", "etat-civil"), ("naiss", "etat-civil"), ("civil", "etat-civil"), ("nation", "nationalite"),
             ("casier", "casier"), ("judic", "casier")]


def simple(texte: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().casefold()


def trouver_liste(donnees, chemin="") -> str | None:
    """Chemin de la première liste d'objets dans un JSON (« registre.personnes »), « » si c'est la racine."""
    if isinstance(donnees, list) and donnees and all(isinstance(d, dict) for d in donnees):
        return chemin
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            trouve = trouver_liste(valeur, f"{chemin}.{cle}" if chemin else str(cle))
            if trouve is not None:
                return trouve
    return None


def lire(adresse: str, entetes: dict, table: str | None) -> tuple[dict, list[dict]]:
    """Renvoie (bloc « source » proposé pour le YAML, lignes lues)."""
    if adresse.startswith(("http://", "https://")):
        requete = urllib.request.Request(adresse, headers={"Accept": "application/json", **entetes})
        with urllib.request.urlopen(requete, timeout=10) as r:
            donnees = json.loads(r.read().decode("utf-8"))
        liste = trouver_liste(donnees)
        source = {"type": "api", "url": adresse + "  # À VÉRIFIER : mettre {sujet_ref} à la place de l'identifiant",
                  "delai": 2}
        if liste:
            source["liste"] = liste
        return source, sources.nettoyer(sources.extraire_liste(donnees, liste or None))
    chemin = Path(adresse)
    type_ = TYPES.get(chemin.suffix.lower())
    if type_ is None:
        raise SystemExit(f"{chemin.name} : extension inconnue ({', '.join(TYPES)})")
    source = {"type": type_, "chemin": f"/donnees/{chemin.name}"}
    lecture = {"type": type_, "chemin": str(chemin)}
    if type_ == "csv":
        brut = chemin.read_bytes()
        try:
            brut.decode("utf-8")
            encodage = "UTF-8"
        except UnicodeDecodeError:
            encodage = "Windows-1252"
        entete = sources.decoder(brut, "auto").splitlines()[0]
        print(f"  encodage : {encodage} ; séparateur : « {';' if entete.count(';') >= entete.count(',') else ','} »")
        source |= {"separateur": "auto", "encodage": "auto"}
    if type_ == "json":
        liste = trouver_liste(json.loads(sources.decoder(chemin.read_bytes(), "auto")))
        if liste:
            source["liste"] = lecture["liste"] = liste
    if type_ in ("sqlite", "sql"):
        if type_ == "sqlite":
            base = sqlite3.connect(f"file:{chemin.as_posix()}?mode=ro", uri=True)
        else:
            base = sqlite3.connect(":memory:")
            base.executescript(sources.decoder(chemin.read_bytes(), "auto"))
        tables = [t[0] for t in base.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        base.close()
        print(f"  tables : {', '.join(tables)}")
        source["table"] = lecture["table"] = table or tables[0]
    if type_ == "xlsx":
        import openpyxl
        feuilles = openpyxl.load_workbook(chemin, read_only=True).sheetnames
        print(f"  feuilles : {', '.join(feuilles)} (lue : {feuilles[0]})")
        source["feuille"] = feuilles[0]
    if type_ == "pdf":
        try:
            return source, sources.lire_source(lecture)
        except ValueError as e:
            raise SystemExit(f"  {e}")
    return source, sources.lire_source(lecture)


def date_iso(valeur: str) -> str:
    """« 14/03/2001 » -> « 2001-03-14 » (même normalisation que le registre) ; sinon texte simplifié."""
    for _motif, _nom, fmt in DATES:
        if fmt:
            try:
                return datetime.strptime(valeur.strip(), fmt).date().isoformat()
            except ValueError:
                pass
    return valeur.strip() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur.strip()) else " ".join(simple(valeur).split())


def forme_identifiant(valeurs: list[str]) -> str:
    """Format commun à toutes les valeurs (« BF-0001 » -> ^[A-Z]{2}-\d{4}$), sinon un format large."""
    def forme(v):
        morceaux = re.findall(r"\d+|[A-Z]+|[a-z]+|.", v)
        return "".join(r"\d{%d}" % len(m) if m.isdigit() else "[A-Z]{%d}" % len(m) if m.isupper()
                       else "[a-z]{%d}" % len(m) if m.islower() else re.escape(m) for m in morceaux)
    formes = {forme(v) for v in valeurs if v}
    return f"^{formes.pop()}$" if len(formes) == 1 else r"^[A-Za-z0-9-]{1,64}$"


def cle_composee_possible(colonnes: list[str], lignes: list[dict]) -> tuple[list[str], int] | None:
    """Nom + prénoms + date de naissance (+ lieu s'il réduit les homonymes). Renvoie (colonnes, nombre de groupes
    d'homonymes EXACTS, qui seraient refusés) ou None si ces colonnes manquent."""
    nom = next((c for c in colonnes if simple(c).split(".")[-1] in ("nom", "nom de famille", "noms")), None)
    prenoms = next((c for c in colonnes if simple(c).split(".")[-1].startswith("prenom")), None)
    naissance = next((c for c in colonnes if "naiss" in simple(c) and "lieu" not in simple(c)), None)
    lieu = next((c for c in colonnes if "lieu" in simple(c)), None)
    if not (nom and prenoms and naissance):
        return None

    def homonymes(cols):
        cles = Counter(tuple(date_iso(l.get(c, "")) for c in cols) for l in lignes if all(l.get(c) for c in cols))
        return sum(1 for n in cles.values() if n > 1)
    cols = [nom, prenoms, naissance]
    if lieu and homonymes(cols + [lieu]) < homonymes(cols):
        cols.append(lieu)
    return cols, homonymes(cols)


def formats_de_date(valeurs: list[str]) -> Counter:
    formes = Counter()
    for v in valeurs:
        forme = next((nom for motif, nom, _ in DATES if re.fullmatch(motif, v.strip())), None)
        if forme:
            formes[forme] += 1
    return formes


def identifiant_probable(colonnes: list[str], lignes: list[dict]) -> str | None:
    """Colonne aux valeurs presque toutes distinctes, de préférence nommée nip / id / identifiant / cnib…"""
    meilleures = []
    for c in colonnes:
        valeurs = [l[c] for l in lignes if l.get(c)]
        if not valeurs:
            continue
        unicite = len(set(valeurs)) / len(lignes)
        nom = simple(c).split(".")[-1]          # « identite.nip » : on regarde « nip »
        # Un nom, un prénom, un lieu ou une date n'est JAMAIS un identifiant, même si toutes les valeurs diffèrent
        if nom.startswith(("nom", "prenom", "lieu", "date", "sexe")) or "naiss" in nom:
            continue
        if not re.search(r"nip|ident|^id\b|cnib|numero|matricule|^nin$|uid|^n d", nom) and \
                not all(re.search(r"\d", v) for v in valeurs):
            continue                            # ni nom d'identifiant, ni valeurs avec des chiffres
        bonus = 1 if (re.search(r"nip|ident|^id\b|cnib|numero|matricule|^nin$|uid|^n d", nom)
                      and not nom.startswith(("nom", "prenom"))) else 0
        meilleures.append((bonus, unicite, c))
    meilleures.sort(reverse=True)
    return meilleures[0][2] if meilleures and meilleures[0][1] > 0.8 else None


def inspecter(adresse: str, entetes: dict, table: str | None) -> dict:
    print(f"\n=== {adresse}")
    source, lignes = lire(adresse, entetes, table)
    colonnes = list(dict.fromkeys(c for l in lignes for c in l))
    print(f"  format : {source['type']} ; {len(lignes)} lignes ; {len(colonnes)} colonnes")
    print("  exemples :")
    for l in lignes[:3]:
        print("    " + json.dumps(l, ensure_ascii=False))
    print("  colonnes :")
    formats_trouves = Counter()
    for c in colonnes:
        valeurs = [l.get(c, "") for l in lignes]
        remplies = [v for v in valeurs if v]
        details = [f"{len(valeurs) - len(remplies)} vides"]
        dates = formats_de_date(remplies)
        if dates and sum(dates.values()) >= 0.5 * len(remplies):
            formats_trouves += dates
            details.append("dates : " + ", ".join(f"{n} × {f}" for f, n in dates.most_common()))
            autres = len(remplies) - sum(dates.values())
            if autres:
                details.append(f"{autres} valeurs NON reconnues comme dates (refus)")
        distinctes = Counter(remplies)
        if 1 < len(distinctes) <= 12 and not dates:
            details.append("valeurs : " + ", ".join(f"« {v} » × {n}" for v, n in distinctes.most_common()))
        print(f"    - {c} : " + " ; ".join(details))
    identite = identifiant_probable(colonnes, lignes)
    if identite:
        doublons = [v for v, n in Counter(l.get(identite) for l in lignes if l.get(identite)).items() if n > 1]
        print(f"  identifiant probable : « {identite} » ; identifiants en double : "
              f"{len(doublons)} {doublons[:5] if doublons else ''} (→ refus « identité ambiguë »)")
    else:
        print("  identifiant probable : AUCUN (pas de colonne aux valeurs distinctes) : rapprochement à décider")
    lignes_identiques = sum(n - 1 for n in Counter(json.dumps(l, sort_keys=True) for l in lignes).values() if n > 1)
    print(f"  lignes entièrement identiques : {lignes_identiques}")
    nom = next((c for c in colonnes if simple(c) in ("nom", "nom de famille", "noms")), None)
    prenoms = next((c for c in colonnes if simple(c).startswith("prenom")), None)
    if nom and prenoms:
        par_personne = {}
        for l in lignes:
            par_personne.setdefault((simple(l.get(nom, "")), simple(l.get(prenoms, ""))), set()).add(
                l.get(identite) if identite else id(l))
        homonymes = [f"{n.upper()} {p.title()}" for (n, p), ids in par_personne.items() if len(ids) > 1 and n]
        print(f"  homonymes (même nom et prénoms, identifiants différents) : {len(homonymes)} {homonymes[:5]}")
    composee = cle_composee_possible(colonnes, lignes)
    if composee:
        print(f"  clé composée possible : {' + '.join(composee[0])} ; homonymes EXACTS (même clé, refusés) : "
              f"{composee[1]}")
    return {"adresse": adresse, "source": source, "colonnes": colonnes, "lignes": lignes, "identite": identite,
            "formats": formats_trouves, "composee": composee[0] if composee else None}


def identifiants_communs(fichiers: list[dict]) -> bool:
    """Affiche les colonnes communes ; renvoie True si CHAQUE paire de fichiers partage un identifiant."""
    print("\n=== Identifiant commun possible entre les fichiers")
    tous = True
    for i, a in enumerate(fichiers):
        for b in fichiers[i + 1:]:
            meilleur = None
            for ca in a["colonnes"]:
                va = {l.get(ca) for l in a["lignes"] if l.get(ca)}
                for cb in b["colonnes"]:
                    vb = {l.get(cb) for l in b["lignes"] if l.get(cb)}
                    if va and vb:
                        commun = len(va & vb) / min(len(va), len(vb))
                        if commun >= 0.25 and (meilleur is None or commun > meilleur[0]):
                            meilleur = (commun, ca, cb)
            nom_a, nom_b = Path(a["adresse"]).name, Path(b["adresse"]).name
            if meilleur:
                print(f"  {nom_a}.« {meilleur[1]} » = {nom_b}.« {meilleur[2]} » ({meilleur[0]:.0%} des valeurs en commun)")
            else:
                tous = False
                print(f"  {nom_a} / {nom_b} : AUCUNE colonne commune : rapprochement à proposer AVANT d'implémenter")
    return tous


def cle_retenue(f: dict, commun: bool):
    """Identifiant commun s'il existe ; sinon la clé composée (jamais de rapprochement approximatif)."""
    if f["identite"] and commun:
        return f["identite"]
    if f["composee"]:
        return {"colonnes": f["composee"], "separateur": "|"}
    return f["identite"] or "À VÉRIFIER : ni identifiant commun, ni nom + prénoms + date de naissance"


def identifiant_usager(f: dict, cle) -> tuple[dict, list[str]]:
    """Format d'identifiant pour catalogue/annuaire.yaml, et quelques identifiants d'exemple."""
    if isinstance(cle, dict):
        exemples = ["|".join(date_iso(l[c]) if "naiss" in simple(c) else l[c] for c in cle["colonnes"])
                    for l in f["lignes"] if all(l.get(c) for c in cle["colonnes"])][:5]
        morceaux = [r"\d{4}-\d{2}-\d{2}" if "naiss" in simple(c) else r"[^|/]{1,80}" for c in cle["colonnes"]]
        return {"format": "^" + r"\|".join(morceaux) + "$", "exemple": exemples[0] if exemples else ""}, exemples
    valeurs = [l[cle] for l in f["lignes"] if l.get(cle)] if cle in f["colonnes"] else []
    return {"format": forme_identifiant(valeurs), "exemple": valeurs[0] if valeurs else ""}, valeurs[:5]


def proposer_yaml(f: dict, commun: bool = True) -> Path:
    """Brouillon : on part de l'adaptateur actuel du registre (groupes, attributs, double clé) et on remplace
    seulement la description des données (source, identité, colonnes, format des dates)."""
    nom = simple(Path(f["adresse"]).stem)
    registre = next((r for mot, r in REGISTRES if mot in nom), "etat-civil")
    conf = yaml.safe_load((RACINE / f"adaptateurs/{registre}.yaml").read_text(encoding="utf-8"))
    conf["source"] = f["source"]
    conf["identite"] = cle_retenue(f, commun)
    champs = {}
    for c in f["colonnes"]:
        devine = next((code for mot, code in DEVINETTES if mot in simple(c)), None)
        if devine and devine not in champs:
            champs[devine] = c
    for code in conf.get("champs", {}):
        champs.setdefault(code, "À VÉRIFIER : colonne non trouvée")
    conf["champs"] = champs
    formats = [fmt for motif, forme, fmt in DATES if fmt and f["formats"].get(forme)]
    if formats:
        conf["format_date"] = formats[0] if len(formats) == 1 else formats
    if "nationalite" in champs and champs["nationalite"] in f["colonnes"]:
        valeurs = sorted({m.strip() for l in f["lignes"] for m in l.get(champs["nationalite"], "").split(";")
                          if m.strip()})       # « Ivoirienne ; Burkinabè » (double nationalité) : deux valeurs
        if len(valeurs) <= 30:
            for a in conf["attributs"].values():
                if a.get("regle") == "egal":
                    a["correspondances"] = {"oui": [v for v in valeurs if "burk" in simple(v) or simple(v) in ("bf", "bfa")],
                                            "non": [v for v in valeurs if not ("burk" in simple(v) or simple(v) in ("bf", "bfa"))]}
    dossier = RACINE / "donnees_jury/brouillons"
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"{registre}-{Path(f['adresse']).name.replace('.', '-')}.yaml"     # un brouillon par fichier
    entete = (f"# BROUILLON proposé par scripts/inspecter_donnees.py pour {Path(f['adresse']).name} : À RELIRE.\n"
              f"# Chercher « À VÉRIFIER ». Les « correspondances » (oui / non) sont devinées : les relire une par une.\n"
              f"# Puis copier dans adaptateurs/{registre}.yaml et tester :\n"
              f"#   .venv\\Scripts\\python scripts\\tester_adaptateur.py {registre} <identifiant> --yaml {chemin.relative_to(RACINE)}\n")
    chemin.write_text(entete + yaml.safe_dump(conf, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return chemin


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspecte des données du jury (aucune modification).")
    parser.add_argument("adresses", nargs="+", help="fichiers (csv, xlsx, json, db, sql, pdf) ou URL d'API")
    parser.add_argument("--proposer-yaml", action="store_true", help="brouillon d'adaptateur dans donnees_jury/brouillons/")
    parser.add_argument("--entete", action="append", default=[], help="en-tête HTTP pour une API (« Nom: valeur »)")
    parser.add_argument("--table", help="table à lire (SQLite, dump SQL) ; par défaut la première")
    args = parser.parse_args()
    entetes = dict(e.split(":", 1) for e in args.entete)
    fichiers = [inspecter(a, {k.strip(): v.strip() for k, v in entetes.items()}, args.table) for a in args.adresses]
    commun = identifiants_communs(fichiers) if len(fichiers) > 1 else True
    cle = cle_retenue(fichiers[0], commun)
    format_id, exemples = identifiant_usager(fichiers[0], cle)
    print("\n=== Clé d'identité proposée")
    print("  " + ("identifiant commun : " + cle if isinstance(cle, str) else "clé composée : " + " + ".join(cle["colonnes"])))
    print(f"  format pour catalogue/annuaire.yaml : {format_id}")
    if args.proposer_yaml:
        print("\n=== Brouillons (À RELIRE)")
        for f in fichiers:
            print(f"  {proposer_yaml(f, commun).relative_to(RACINE)}")
        dossier = RACINE / "donnees_jury/brouillons"
        (dossier / "identifiant_usager.yaml").write_text(
            "# À copier dans catalogue/annuaire.yaml (remplace le bloc identifiant_usager) : À RELIRE\n"
            + yaml.safe_dump({"identifiant_usager": format_id}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        abonnes = {f"700001{i:02d}": {"sujet_ref": e, "pin": "1234"} for i, e in enumerate(exemples, start=1)}
        (dossier / "abonnes.yaml").write_text(
            "# Annuaire USSD FICTIF pour la démo avec les données du jury (numéros et PIN inventés).\n"
            "# Copier dans donnees_jury/abonnes.yaml, puis ABONNES_USSD=./donnees_jury/abonnes.yaml dans .env.\n"
            + yaml.safe_dump(abonnes, allow_unicode=True, sort_keys=False), encoding="utf-8")
        for nom in ("identifiant_usager.yaml", "abonnes.yaml"):
            print(f"  {(dossier / nom).relative_to(RACINE)}")


if __name__ == "__main__":
    main()

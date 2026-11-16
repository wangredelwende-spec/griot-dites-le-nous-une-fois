"""Annuaire USSD du jour J : un numéro de téléphone FICTIF et un PIN de démo pour CHAQUE citoyen importé.

    .venv\\Scripts\\python scripts\\annuaire_ussd.py                 # écrit donnees_jury\\abonnes.yaml + imprime le tableau
    .venv\\Scripts\\python scripts\\annuaire_ussd.py --pin 4321      # autre PIN de démo (le même pour tous)
    .venv\\Scripts\\python scripts\\annuaire_ussd.py --essai         # imprime seulement, n'écrit rien

Le jury peut désigner n'importe quel citoyen : il doit pouvoir « prendre son téléphone » (*226#).
Les citoyens sont lus dans le registre d'ÉTAT CIVIL, avec le MÊME code et le MÊME adaptateur que le registre
(adaptateurs/etat-civil.yaml, données de DONNEES_REGISTRES dans .env). L'identifiant imprimé est EXACTEMENT celui à
taper au guichet : le médiateur retrouve les demandes de l'usager par cet identifiant (pseudonymisé), une autre
écriture (accents, date en jj/mm/aaaa) ne retrouverait pas ses demandes sur le téléphone.

Sorties (dans donnees_jury/, ignoré par git) :
- abonnes.yaml       : numéro -> {sujet_ref, pin}, lu par le simulateur USSD (ABONNES_USSD dans .env) ;
- annuaire_ussd.csv  : le tableau (identifiant ; nom ; numéro ; PIN ; remarque), à imprimer pour le jury.
Numéros : 71 000 001, 71 000 002… dans l'ordre du fichier (fictifs ; en production le numéro vient de l'opérateur).
PIN : le même PIN de DÉMO pour tous, en clair dans abonnes.yaml (comme ussd_sim/abonnes.yaml) : voir LIMITES.md.
"""
import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tester_adaptateur import RACINE, charger_paquet_registre, lire_env  # noqa: E402

PREMIER_NUMERO = 71000001


def colonnes_du_nom(lignes: list[dict], normaliser) -> list[str]:
    """Colonnes « nom » et « prénom(s) » du fichier, quelle que soit leur écriture (Nom, NOM, Prénoms…)."""
    entetes = list(lignes[0]) if lignes else []
    trouvees = []
    for cherche in ("nom", "prenom"):
        for e in entetes:
            n = normaliser(e).replace("_", " ")
            if (n == "nom" or n.startswith("nom ")) if cherche == "nom" else n.startswith("prenom"):
                trouvees.append(e)
                break
    return trouvees


def identifiant_de(registre, ligne: dict) -> str | None:
    """Identifiant à taper au guichet pour cette fiche (None : clé incomplète, la personne est introuvable)."""
    if not registre.cle_composee:
        return (ligne.get(registre.identite) or "").strip() or None
    if registre.cle_de_la_fiche(ligne) is None:
        return None
    morceaux = []
    for colonne in registre.identite:
        brut = (ligne.get(colonne) or "").strip()
        forme = registre.morceau_de_cle(brut)
        # Les dates sont écrites 2001-03-14 (forme comparée par le registre) ; le texte est gardé tel quel
        morceaux.append(forme if forme[:4].isdigit() and forme.count("-") == 2 else brut)
    identifiant = registre.separateur_cle.join(morceaux)
    # Contre-épreuve : le registre doit retrouver CETTE fiche avec cet identifiant (sinon : pas de numéro).
    # « ZONGO|Issouf|vers 1990 » est retrouvé, puis refusé par le registre (donnée insuffisante) : bon cas de démo.
    cle = [registre.morceau_de_cle(m) for m in identifiant.split(registre.separateur_cle)]
    return identifiant if cle == registre.cle_de_la_fiche(ligne) else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Numéro fictif + PIN de démo pour chaque citoyen importé.")
    parser.add_argument("--pin", default="1234", help="PIN de démo, le même pour tous (4 chiffres)")
    parser.add_argument("--donnees", help="dossier des données (par défaut DONNEES_REGISTRES du .env)")
    parser.add_argument("--yaml", help="adaptateur d'état civil (par défaut adaptateurs/etat-civil.yaml)")
    parser.add_argument("--sortie", default=str(RACINE / "donnees_jury"), help="dossier de sortie")
    parser.add_argument("--essai", action="store_true", help="imprimer seulement, sans rien écrire")
    args = parser.parse_args()
    if not (args.pin.isdigit() and len(args.pin) == 4):
        raise SystemExit("Le PIN de démo doit faire 4 chiffres.")

    env = lire_env()
    donnees = Path(args.donnees or env.get("DONNEES_REGISTRES", "").strip() or "registres_sim/donnees_fictives")
    donnees = donnees if donnees.is_absolute() else RACINE / donnees
    source = Path(args.yaml) if args.yaml else RACINE / "adaptateurs/etat-civil.yaml"
    temporaire = Path(tempfile.mkdtemp(prefix="annuaire-ussd-"))
    (temporaire / "api_jury").write_text("")
    os.environ["GRIOT_SECRETS"] = str(temporaire)
    chemin = temporaire / "etat-civil.yaml"
    chemin.write_text(source.read_text(encoding="utf-8").replace("/donnees/", donnees.as_posix() + "/"),
                      encoding="utf-8")
    module = charger_paquet_registre()
    registre = module.Adaptateur(chemin)
    if registre.lignes is None:
        raise SystemExit("Registre branché sur une API : exporter d'abord ses données "
                         "(scripts/exporter_api_jury.py), puis relancer sur le fichier exporté.")

    colonnes_nom = colonnes_du_nom(registre.lignes, module.normaliser_texte)
    # Combien de fiches par identifiant : plusieurs = homonymes ou doublon (le registre refusera)
    identifiants = [identifiant_de(registre, l) for l in registre.lignes]
    nombre = {i: identifiants.count(i) for i in identifiants if i}

    abonnes, tableau, vus, numero = {}, [], set(), PREMIER_NUMERO
    for ligne, ident in zip(registre.lignes, identifiants):
        nom = " ".join((ligne.get(c) or "").strip() for c in colonnes_nom).strip() or "?"
        if ident is None:
            tableau.append(["", nom, "", "", "pas d'identifiant (clé incomplète) : introuvable"])
            continue
        if ident in vus:
            continue                                    # même identifiant : un seul numéro
        vus.add(ident)
        remarque = f"{nombre[ident]} fiches : le registre refusera (identité ambiguë)" if nombre[ident] > 1 else ""
        abonnes[str(numero)] = {"sujet_ref": ident, "pin": args.pin}
        tableau.append([ident, nom, str(numero), args.pin, remarque])
        numero += 1

    largeur = max([len("Identifiant")] + [len(t[0]) for t in tableau])
    print(f"Registre d'état civil : {len(registre.lignes)} fiches, {len(abonnes)} numéros attribués "
          f"(sha256 des données {registre.empreinte_source[:16]}…)\n")
    print(f"{'Identifiant':<{largeur}}  {'Numéro':<8}  PIN   Nom")
    for ident, nom, num, pin, remarque in tableau:
        print(f"{ident:<{largeur}}  {num:<8}  {pin:<4}  {nom}" + (f"   [{remarque}]" if remarque else ""))
    if args.essai:
        return

    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "abonnes.yaml").write_text(
        "# Annuaire USSD de DÉMO (scripts/annuaire_ussd.py) : numéros FICTIFS et PIN de démo, en clair.\n"
        "# Lu par le simulateur USSD si ABONNES_USSD=./donnees_jury/abonnes.yaml dans .env.\n"
        + yaml.safe_dump(abonnes, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with open(sortie / "annuaire_ussd.csv", "w", encoding="utf-8-sig", newline="") as f:
        ecrivain = csv.writer(f, delimiter=";")
        ecrivain.writerow(["identifiant (à taper au guichet)", "nom", "numéro USSD", "PIN", "remarque"])
        ecrivain.writerows(tableau)
    print(f"\nÉcrit : {sortie / 'abonnes.yaml'} et {sortie / 'annuaire_ussd.csv'}")


if __name__ == "__main__":
    main()

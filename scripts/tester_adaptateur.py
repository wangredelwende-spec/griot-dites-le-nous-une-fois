"""Ce que le registre RÉPONDRAIT pour une personne, sans rien signer ni journaliser (outil local).

    .venv\\Scripts\\python scripts\\tester_adaptateur.py etat-civil BF-0001
    .venv\\Scripts\\python scripts\\tester_adaptateur.py etat-civil BF-0001 --yaml donnees_jury\\brouillons\\etat-civil-etat_civil-xlsx.yaml

Charge l'adaptateur avec le MÊME code que le registre (registres_sim/app/adaptateur.py). Les chemins
« /donnees/… » du YAML sont lus dans le dossier des données : DONNEES_REGISTRES du .env (par défaut
registres_sim/donnees_fictives), ou --donnees. Pour chaque attribut (et chaque jeu de paramètres déclaré) :
la réponse minimale, ou le motif PRÉCIS du refus (qui, lui, ne sort jamais du registre en vrai).
Aucune clé, aucun jeton, aucun journal : rien n'est écrit.
"""
import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def charger_paquet_registre():
    """registres_sim/app chargé sous le nom « registre_app » (comme dans les tests)."""
    spec = importlib.util.spec_from_file_location("registre_app", RACINE / "registres_sim/app/__init__.py",
                                                  submodule_search_locations=[str(RACINE / "registres_sim/app")])
    sys.modules["registre_app"] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sys.modules["registre_app"])
    return importlib.import_module("registre_app.adaptateur")


def lire_env() -> dict:
    chemin = RACINE / ".env"
    if not chemin.exists():
        return {}
    return dict(l.split("=", 1) for l in chemin.read_text(encoding="utf-8").splitlines()
                if "=" in l and not l.lstrip().startswith("#"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Réponse qu'un registre donnerait, sans signer ni journaliser.")
    parser.add_argument("registre", help="etat-civil, nationalite, casier…")
    parser.add_argument("identifiant", help="identifiant de la personne (sujet_ref)")
    parser.add_argument("--yaml", help="adaptateur à essayer (par défaut adaptateurs/<registre>.yaml)")
    parser.add_argument("--donnees", help="dossier des fichiers (par défaut DONNEES_REGISTRES du .env)")
    args = parser.parse_args()

    env = lire_env()
    donnees = Path(args.donnees or env.get("DONNEES_REGISTRES", "").strip() or "registres_sim/donnees_fictives")
    donnees = donnees if donnees.is_absolute() else RACINE / donnees
    yaml_source = Path(args.yaml) if args.yaml else RACINE / f"adaptateurs/{args.registre}.yaml"
    temporaire = Path(tempfile.mkdtemp(prefix="tester-adaptateur-"))
    # Secret de l'API du jury (.env -> fichier temporaire, comme /run/secrets dans le conteneur), effacé à la fin
    (temporaire / "api_jury").write_text(env.get("API_JURY_SECRET", "").strip())
    os.environ["GRIOT_SECRETS"] = str(temporaire)
    chemin = temporaire / "adaptateur.yaml"
    chemin.write_text(yaml_source.read_text(encoding="utf-8").replace("/donnees/", donnees.as_posix() + "/"),
                      encoding="utf-8")
    try:
        adaptateur = charger_paquet_registre()
        registre = adaptateur.Adaptateur(chemin)
        print(f"Adaptateur : {yaml_source} ; source {registre.source['type']}"
              + (f", {len(registre.lignes)} lignes, sha256 {registre.empreinte_source[:16]}…" if registre.lignes else ""))
        try:
            print(f"Fiches trouvées pour {args.identifiant} : {len(registre.fiches(args.identifiant))}")
        except adaptateur.SourceIndisponible as e:
            print(f"Source indisponible : {e} (le registre répondrait « indisponible », sans rien signer)")
            return
        aujourdhui = datetime.now(timezone.utc).date().isoformat()
        for code, regle in registre.attributs.items():
            services = regle.get("services", [])
            jeux = ([dict(p) for params in services.values() for p in params or []] if isinstance(services, dict)
                    else [{}])
            vus = []
            for parametres in jeux:
                if parametres in vus:
                    continue
                vus.append(parametres)
                if parametres.get("date_reference") == "aujourd'hui":
                    parametres = parametres | {"date_reference": aujourdhui}
                titre = code + (f" {json.dumps(parametres, ensure_ascii=False)}" if parametres else "")
                try:
                    print(f"  {titre} -> {json.dumps(registre.calculer(code, args.identifiant, parametres), ensure_ascii=False)}")
                except adaptateur.Refus as motif:
                    print(f"  {titre} -> REFUS : {motif}   (motif public envoyé : « {registre.motif_refus_public} »)")
    finally:
        for f in temporaire.iterdir():
            f.unlink()
        temporaire.rmdir()


if __name__ == "__main__":
    main()

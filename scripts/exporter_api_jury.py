"""Export UNIQUE de l'API du jury vers un fichier JSON (option par défaut : on importe un fichier).

    .venv\\Scripts\\python scripts\\exporter_api_jury.py "http://api-jury/etat-civil/personnes" etat_civil
    .venv\\Scripts\\python scripts\\exporter_api_jury.py "<url>" nationalite --entete "X-Api-Key: …"

Lance UNE requête GET (depuis le poste, pas depuis un conteneur), puis écrit dans donnees_jury\\ :
- <nom>.json            : la réponse telle quelle (aucune transformation) ;
- <nom>.provenance.json : adresse (sans le jeton), date, nombre de fiches, empreinte SHA-256 du fichier.
Le jeton de l'API est pris dans .env (API_JURY_SECRET) ou passé par --entete ; il n'est écrit nulle part.
Ensuite : inspecter_donnees.py donnees_jury\\<nom>.json --proposer-yaml (source « type: json »), comme pour un
fichier remis par le jury. Les registres restent sans aucun accès réseau.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Export unique de l'API du jury vers donnees_jury\\<nom>.json")
    parser.add_argument("url")
    parser.add_argument("nom", help="nom du fichier produit, sans extension (ex. etat_civil)")
    parser.add_argument("--entete", action="append", default=[], help="en-tête HTTP « Nom: valeur »")
    parser.add_argument("--delai", type=float, default=30, help="secondes (export unique : peut être long)")
    args = parser.parse_args()

    entetes = {"Accept": "application/json"}
    entetes |= {k.strip(): v.strip() for k, v in (e.split(":", 1) for e in args.entete)}
    env = RACINE / ".env"
    secret = next((l.split("=", 1)[1].strip() for l in env.read_text(encoding="utf-8").splitlines()
                   if l.startswith("API_JURY_SECRET=")), "") if env.exists() else ""
    if secret and "Authorization" not in entetes:
        entetes["Authorization"] = f"Bearer {secret}"

    with urllib.request.urlopen(urllib.request.Request(args.url, headers=entetes), timeout=args.delai) as r:
        brut = r.read()
    donnees = json.loads(brut.decode("utf-8"))           # refuse ce qui n'est pas du JSON
    dossier = RACINE / "donnees_jury"
    dossier.mkdir(exist_ok=True)
    sortie = dossier / f"{args.nom}.json"
    sortie.write_bytes(brut)
    nombre = len(donnees) if isinstance(donnees, list) else None
    provenance = {"source": args.url.split("?")[0], "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "fichier": sortie.name, "octets": len(brut), "fiches_a_la_racine": nombre,
                  "sha256": hashlib.sha256(brut).hexdigest()}
    (dossier / f"{args.nom}.provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
    print(f"OK : {sortie.relative_to(RACINE)} ({len(brut)} octets), sha256 {provenance['sha256']}")
    print(f"Ensuite : .venv\\Scripts\\python scripts\\inspecter_donnees.py {sortie.relative_to(RACINE)} --proposer-yaml")


if __name__ == "__main__":
    main()

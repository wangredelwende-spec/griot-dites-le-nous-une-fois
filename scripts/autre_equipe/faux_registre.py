r"""FAUX registre d'état civil d'une AUTRE équipe, pour l'essai à blanc (docs/brancher-un-registre.md).

    .venv\Scripts\python scripts\autre_equipe\faux_registre.py [port]      (7000 par défaut)

Il sert NOS citoyens fictifs (registres/donnees/citoyens-fictifs.yaml) sous une autre forme, celle de
contrat-autre-equipe.yaml : autre adresse, autre route (GET /api/v2/personnes/{numero}), autres noms de champs.
404 si la personne est inconnue. Bibliothèque standard + PyYAML seulement.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import yaml

RACINE = Path(__file__).resolve().parents[2]
PREFIXE = "/api/v2/personnes/"
# Nos noms de champs -> les siens (c'est ce que correspondance.yaml devra défaire)
SES_NOMS = {"id": "numero", "nom": "nom_famille", "prenoms": "prenom", "date_naissance": "ne_le",
            "lieu_naissance": "ne_a", "pere": "pere_nom", "mere": "mere_nom", "date_deces": "decede_le"}


def personnes() -> dict:
    citoyens = yaml.safe_load((RACINE / "registres/donnees/citoyens-fictifs.yaml").read_text(encoding="utf-8"))["citoyens"]
    return {str(c["id"]): {sien: (None if c.get(notre) is None and sien == "decede_le" else str(c.get(notre)))
                           for notre, sien in SES_NOMS.items()} for c in citoyens}


class FauxRegistre(BaseHTTPRequestHandler):
    fiches = personnes()
    appels = 0                    # compté par l'essai à blanc : prouve que la passerelle l'a bien appelé
    non_conforme = False          # l'essai à blanc le met à True : réponse qui ne respecte pas SON contrat

    def do_GET(self):
        if not self.path.startswith(PREFIXE):
            return self.repondre(404, {"erreur": "route inconnue"})
        FauxRegistre.appels += 1
        fiche = self.fiches.get(unquote(self.path[len(PREFIXE):]))
        if fiche is None:
            return self.repondre(404, {"erreur": "personne inconnue"})
        if FauxRegistre.non_conforme:
            fiche = {"numero": fiche["numero"], "date_de_naissance": fiche["ne_le"]}      # champ hors contrat
        self.repondre(200, fiche)

    def repondre(self, code: int, corps: dict):
        donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(donnees)))
        self.end_headers()
        self.wfile.write(donnees)

    def log_message(self, *args):
        pass                      # rien dans la console : l'adresse contient l'identifiant du citoyen


def demarrer(port: int = 7000, hote: str = "127.0.0.1") -> ThreadingHTTPServer:
    """hote="0.0.0.0" : joignable depuis Docker (host.docker.internal), comme une autre machine du réseau."""
    return ThreadingHTTPServer((hote, port), FauxRegistre)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7000
    print(f"Faux registre « autre équipe » : http://127.0.0.1:{port}{PREFIXE}<numero>  (Ctrl+C pour arrêter)", flush=True)
    try:
        demarrer(port).serve_forever()
    except KeyboardInterrupt:
        pass

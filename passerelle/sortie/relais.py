"""Relais vers l'API du jury (profil docker « api-jury ») : le SEUL conteneur qui touche le réseau extérieur.

Les registres restent sur des réseaux sans sortie. Quand le jury impose son API en direct, un registre l'interroge
à travers ce relais (réseau interne « relais-jury ») :

    registre  --GET http://relais-api-jury:8080/personnes?nip=…-->  relais  --GET <API_JURY_URL>/personnes?nip=…-->  API

Règles, toutes simples :
- une seule destination : l'adresse API_JURY_URL écrite dans .env (le chemin demandé lui est ajouté ; impossible
  de viser un autre serveur) ;
- GET seulement (lecture) ; tout le reste est refusé (405) ;
- délai maximal (DELAI_API_JURY, 2 s par défaut, sous les 3 s du médiateur) ; API coupée ou trop lente : 504,
  et le registre répond « indisponible », sans rien deviner ni signer ;
- le jeton de l'API (secret « api_jury », valeur dans .env) est ajouté ici : le registre ne le connaît pas ;
- les journaux ne contiennent ni l'adresse demandée (elle contient l'identifiant du citoyen), ni la réponse.
Bibliothèque standard seulement.
"""
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TAILLE_MAX = 5_000_000          # octets : une réponse plus grosse est refusée


def configuration() -> dict:
    secret = Path(os.environ.get("GRIOT_SECRETS", "/run/secrets")) / "api_jury"
    return {"base": os.environ["API_JURY_URL"].rstrip("/"),
            "delai": float(os.environ.get("DELAI_API_JURY", "2")),
            "jeton": secret.read_text().strip() if secret.exists() else "",
            "schema": os.environ.get("API_JURY_SCHEMA", "Bearer")}


class Relais(BaseHTTPRequestHandler):
    conf: dict = {}

    def repondre(self, code: int, corps: bytes, type_: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def refuser(self, code: int, motif: str):
        self.repondre(code, json.dumps({"detail": motif}, ensure_ascii=False).encode())

    def do_GET(self):
        debut = time.monotonic()
        if self.path == "/__sante":                       # santé du relais lui-même (sans appeler l'API)
            return self.repondre(200, b"ok", "text/plain")
        # Le chemin demandé est AJOUTÉ à l'adresse fixe : « //autre-serveur » ou « http:… » sont refusés
        if not self.path.startswith("/") or self.path.startswith("//") or "://" in self.path.split("?")[0]:
            return self.refuser(400, "chemin refusé")
        entetes = {"Accept": "application/json"}
        if self.conf["jeton"]:
            entetes["Authorization"] = f"{self.conf['schema']} {self.conf['jeton']}"
        requete = urllib.request.Request(self.conf["base"] + self.path, headers=entetes)
        try:
            with urllib.request.urlopen(requete, timeout=self.conf["delai"]) as r:
                corps = r.read(TAILLE_MAX + 1)
                code = r.status
        except urllib.error.HTTPError as e:
            corps, code = e.read(TAILLE_MAX + 1), e.code       # 404 = personne introuvable : transmis tel quel
        except (urllib.error.URLError, TimeoutError, OSError):
            corps, code = json.dumps({"detail": "API du jury injoignable ou trop lente"}).encode(), 504
        if len(corps) > TAILLE_MAX:
            corps, code = json.dumps({"detail": "réponse trop grosse"}).encode(), 502
        self.repondre(code, corps)
        # Journal : code et durée seulement (jamais l'adresse, qui contient l'identifiant du citoyen)
        print(f"relais : {code} en {time.monotonic() - debut:.2f} s", flush=True)

    def do_POST(self):
        self.refuser(405, "lecture seule : GET uniquement")

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, *_):
        pass                                              # pas de journal par défaut (il contiendrait l'adresse)


def serveur(port: int = 8080) -> ThreadingHTTPServer:
    Relais.conf = configuration()
    return ThreadingHTTPServer(("0.0.0.0", port), Relais)


if __name__ == "__main__":
    s = serveur(int(os.environ.get("PORT", "8080")))
    print(f"Relais vers l'API du jury prêt (destination fixée par API_JURY_URL, délai {Relais.conf['delai']} s)",
          flush=True)
    s.serve_forever()

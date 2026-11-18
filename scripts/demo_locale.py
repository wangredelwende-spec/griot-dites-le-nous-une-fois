"""Démonstration LOCALE, sans Docker : passerelle + portail web usager + simulateur USSD dans UN seul processus.

    .venv\Scripts\python scripts\demo_locale.py

Puis ouvrir dans le navigateur :
    http://127.0.0.1:8081/portail      portail web (numéro 70000001, PIN 1234)
    http://127.0.0.1:8082/             simulateur du téléphone *226# (même numéro, même PIN)
    http://127.0.0.1:8000/journal/verification   le badge « journal intègre » en JSON

Pour voir quelque chose, le script prépare 3 consultations fictives de « Aminata Kaboré » (BF-0001) avec des
registres simulés RÉELS, branchés en mémoire selon notre contrat des registres (données fictives) : un concours (base légale), une carte nationale
d'identité à l'ONI (base légale, réponse immédiate) et une demande de certificat de nationalité EN ATTENTE, à confirmer ou
refuser vous-même. Tout est jeté à l'arrêt (Ctrl+C). Ce n'est PAS la pile Docker : les données ne sont pas conservées.
"""
import os
import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
os.environ.update(COOKIE_SECURE="0", MEDIATEUR="http://127.0.0.1:8000",
                  ABONNES=str(RACINE / "espace-usager/ussd/abonnes.yaml"))

import respx  # noqa: E402
import uvicorn  # noqa: E402

# conftest.py prépare tout comme pour les tests : dossier temporaire, secrets de démonstration, clés des faux registres,
# passerelle en mémoire. On le réutilise tel quel pour ne pas écrire deux fois la même préparation.
import conftest  # noqa: E402
from conftest import CANAL, brancher_les_registres_reels, demande, mediateur  # noqa: E402

SUJET = "BF-0001"


def preparer_les_consultations():
    """Trois demandes passées par la VRAIE passerelle (règles, catalogue, journal chaîné), avec des registres simulés."""
    from fastapi.testclient import TestClient
    agent = {"nom": "issa.sawadogo"}
    mediateur.app.dependency_overrides[conftest.agent_connecte] = lambda: {
        "nom": agent["nom"], "jeton": conftest.JETON_AGENT, "groupes": conftest.AGENTS[agent["nom"]]}

    with respx.mock, TestClient(mediateur.app) as client:
        brancher_les_registres_reels()          # le vrai code des registres simulés, sans réseau
        # 1. Concours direct : base légale, réponse immédiate, l'usager le voit dans son historique
        client.post("/demandes", json=demande("concours-direct", sujet=SUJET))
        # 2. Carte nationale d'identité (ONI) : base légale, réponse immédiate, visible dans l'historique
        agent["nom"] = "aicha.ilboudo"
        client.post("/demandes", json=demande("carte-identite-oni", sujet=SUJET))
        # 3. Certificat de nationalité : laissé EN ATTENTE, à vous de confirmer ou refuser
        agent["nom"] = "moussa.kone"
        client.post("/demandes", json=demande("certificat-nationalite", sujet=SUJET))
    mediateur.app.dependency_overrides.clear()


def servir(app, port):
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=serveur.run, daemon=True).start()


def main():
    preparer_les_consultations()
    servir(mediateur.app, 8000)
    # Le portail et l'USSD lisent leur configuration à l'import : après la préparation des variables d'environnement
    import importlib.util

    def charger(nom, fichier, textes):
        os.environ["TEXTES"] = str(RACINE / textes)
        spec = importlib.util.spec_from_file_location(nom, RACINE / fichier)
        module = importlib.util.module_from_spec(spec)
        sys.modules[nom] = module
        spec.loader.exec_module(module)
        return module
    portail = charger("portail_demo", "espace-usager/portail/app/main.py", "traduction-moore/phrases-portail.csv")
    ussd = charger("ussd_demo", "espace-usager/ussd/app/main.py", "traduction-moore/phrases-ussd.csv")
    servir(portail.app, 8081)
    servir(ussd.app, 8082)
    time.sleep(1)
    print("Démonstration locale prête (Ctrl+C pour arrêter) :\n"
          "  portail web : http://127.0.0.1:8081/portail   (numéro 70000001, PIN 1234)\n"
          "  téléphone   : http://127.0.0.1:8082/          (même numéro, même PIN)\n"
          "  journal     : http://127.0.0.1:8000/journal/verification\n"
          "Registres simulés, données fictives.", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

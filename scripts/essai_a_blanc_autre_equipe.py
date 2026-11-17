r"""ESSAI À BLANC CHRONOMÉTRÉ : brancher le registre d'état civil d'une AUTRE équipe (docs/brancher-un-registre.md).

    .venv\Scripts\python scripts\essai_a_blanc_autre_equipe.py            vous modifiez les fichiers, chrono en marche
    .venv\Scripts\python scripts\essai_a_blanc_autre_equipe.py --auto     le script fait les modifications (test)

Sans Docker, sans toucher au dépôt :
1. un FAUX registre « autre équipe » démarre (scripts/autre_equipe/faux_registre.py : autre adresse, autre route,
   autres noms de champs, son propre contrat) ;
2. le catalogue est COPIÉ dans un dossier temporaire ; la VRAIE passerelle démarre en mémoire sur cette copie ;
3. le chrono part : vous modifiez annuaire.yaml et correspondance.yaml de la copie (et vous y copiez le contrat de
   l'autre équipe), puis Entrée. Aucun redémarrage : la passerelle relit ces fichiers à chaud ;
4. le script joue le concours direct et affiche ✅ / ❌ ligne par ligne, puis le temps total.
Les registres de la nationalité et du casier restent les nôtres (simulés en mémoire).
"""
import argparse
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "scripts/autre_equipe"))

# Les modifications attendues (les mêmes que dans docs/brancher-un-registre.md)
ANNUAIRE_AVANT = """  etat-civil:
    url: http://registre-etat-civil:8000
    chemin: /etat-civil/{id}
    nom: registre d'état civil
"""
ANNUAIRE_APRES = """  etat-civil:
    url: http://127.0.0.1:{port}
    chemin: /api/v2/personnes/{{numero}}
    nom: registre d'état civil
    contrat: contrats/autre-equipe.yaml
"""
CORRESPONDANCE_AVANT = """  etat-civil:
    nom: nom
    prenoms: prenoms
    date_naissance: date_naissance
    lieu_naissance: lieu_naissance
    pere: pere
    mere: mere
    date_deces: date_deces
"""
CORRESPONDANCE_APRES = """  etat-civil:
    nom: nom_famille
    prenoms: prenom
    date_naissance: ne_le
    lieu_naissance: ne_a
    pere: pere_nom
    mere: mere_nom
    date_deces: decede_le
"""


def remplacer(fichier: Path, avant: str, apres: str):
    texte = fichier.read_text(encoding="utf-8").replace("\r\n", "\n")
    if avant not in texte:
        sys.exit(f"--auto : bloc introuvable dans {fichier.name} (le fichier du dépôt a changé)")
    fichier.write_text(texte.replace(avant, apres), encoding="utf-8")


def faire_les_modifications(catalogue: Path, port: int):
    """Ce que fait un humain en mode normal : 1 fichier copié, 2 blocs remplacés."""
    (catalogue / "contrats").mkdir(exist_ok=True)
    shutil.copy(RACINE / "scripts/autre_equipe/contrat-autre-equipe.yaml", catalogue / "contrats/autre-equipe.yaml")
    remplacer(catalogue / "annuaire.yaml", ANNUAIRE_AVANT, ANNUAIRE_APRES.format(port=port))
    remplacer(catalogue / "correspondance.yaml", CORRESPONDANCE_AVANT, CORRESPONDANCE_APRES)


def main():
    parser = argparse.ArgumentParser(description="Essai à blanc : brancher le registre d'une autre équipe")
    parser.add_argument("--auto", action="store_true", help="faire les modifications automatiquement (test)")
    parser.add_argument("--port", type=int, default=7000, help="port du faux registre (0 = au hasard, avec --auto)")
    args = parser.parse_args()

    # 1. Faux registre de l'autre équipe
    import faux_registre
    try:
        serveur = faux_registre.demarrer(args.port)
    except OSError:
        sys.exit(f"Port {args.port} occupé : relancer avec --port <autre port>")
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()

    # 2. Copie du catalogue + vraie passerelle en mémoire sur cette copie (préparation de conftest.py, comme
    #    demo_locale.py). Le dépôt n'est jamais modifié.
    dossier = Path(tempfile.mkdtemp(prefix="griot-essai-"))
    catalogue = dossier / "catalogue"
    shutil.copytree(RACINE / "consentement-minimisation/catalogue", catalogue)
    os.environ["GRIOT_CATALOGUE"] = str(catalogue)
    import respx
    from fastapi.testclient import TestClient
    import conftest
    from conftest import brancher_les_registres_reels, demande, mediateur

    mediateur.app.dependency_overrides[conftest.agent_connecte] = lambda: {
        "nom": "issa.sawadogo", "jeton": conftest.JETON_AGENT, "groupes": conftest.AGENTS["issa.sawadogo"]}

    # 3. Chrono
    print(f"Faux registre de l'autre équipe : http://127.0.0.1:{port}/api/v2/personnes/<numero>")
    print(f"   son contrat : {RACINE / 'scripts/autre_equipe/contrat-autre-equipe.yaml'}")
    print(f"Catalogue à modifier (COPIE, le dépôt n'est pas touché) : {catalogue}")
    debut = time.monotonic()
    if args.auto:
        faire_les_modifications(catalogue, port)
    else:
        print("\nCHRONO EN MARCHE. Suivez docs/brancher-un-registre.md sur ce dossier :\n"
              f"  1. copier le contrat de l'autre équipe dans {catalogue / 'contrats' / 'autre-equipe.yaml'}\n"
              f"  2. annuaire.yaml       : bloc etat-civil (url http://127.0.0.1:{port}, chemin, contrat)\n"
              "  3. correspondance.yaml : bloc etat-civil (noms des champs de l'autre équipe)")
        input("Puis Entrée pour vérifier... ")
    time.sleep(1.1)                 # la passerelle regarde ses fichiers au plus une fois par seconde

    # 4. Vérifications avec la VRAIE passerelle
    resultats = []

    def verifier(texte, ok, detail=""):
        resultats.append(ok)
        print(f"{'✅' if ok else '❌'} {texte}" + (f"  ({detail})" if detail and not ok else ""), flush=True)

    def majeur(reponse):
        return next((v for v in reponse.get("volets", []) if v["attribut"] == "majeur"), {})

    print()
    with respx.mock(assert_all_called=False) as routeur, TestClient(mediateur.app) as client:
        routeur.route(host="127.0.0.1", port=port).pass_through()     # le faux registre : un vrai appel réseau local
        brancher_les_registres_reels()                                 # nationalité et casier : les nôtres
        client.get("/catalogue")                                       # la passerelle relit annuaire.yaml
        registre = mediateur.CAT["registres"]["etat-civil"]
        verifier("catalogue accepté, état civil = registre de l'autre équipe",
                 not mediateur.REFUS_CATALOGUE and registre["url"] == f"http://127.0.0.1:{port}",
                 mediateur.REFUS_CATALOGUE.get("raison", "").strip() or registre["url"])

        appels = faux_registre.FauxRegistre.appels
        r = client.post("/demandes", json=demande("concours-direct", sujet="BF-0001")).json()
        verifier("BF-0001 : concours, majeur = oui, lu chez l'autre équipe",
                 majeur(r).get("statut") == "ok" and majeur(r).get("valeur") == 1
                 and faux_registre.FauxRegistre.appels > appels, majeur(r).get("motif") or r.get("motif", ""))
        verifier("BF-0001 : nationalité et casier toujours lus chez nous",
                 r.get("statut") == "remise", r.get("motif", ""))
        r = client.post("/demandes", json=demande("concours-direct", sujet="BF-0003")).json()
        verifier("BF-0003 (mineure) : majeur = non", majeur(r).get("statut") == "ok" and majeur(r).get("valeur") == 0,
                 majeur(r).get("motif", ""))
        r = client.post("/demandes", json=demande("concours-direct", sujet="BF-0009")).json()
        verifier("BF-0009 (décédée, champ « decede_le ») : refus, rien n'est deviné",
                 majeur(r).get("statut") == "refuse", majeur(r).get("motif", ""))
        r = client.post("/demandes", json=demande("concours-direct", sujet="BF-9999")).json()
        verifier("BF-9999 : inconnu de l'autre équipe (404) : refus", r.get("statut") == "refuse", r.get("motif", ""))
        faux_registre.FauxRegistre.non_conforme = True
        r = client.post("/demandes", json=demande("concours-direct", sujet="BF-0001")).json()
        faux_registre.FauxRegistre.non_conforme = False
        verifier("réponse hors de SON contrat : rejetée (réponse corrompue)",
                 "non conforme au contrat" in (majeur(r).get("motif", "") + r.get("motif", "")), majeur(r).get("motif", ""))
        verifier("journal intègre", client.get("/journal/verification").json().get("integre") is True)

    duree = time.monotonic() - debut
    serveur.shutdown()
    shutil.rmtree(dossier, ignore_errors=True)
    print(f"\n{sum(resultats)}/{len(resultats)} vérifications ; registre de l'autre équipe branché en "
          f"{int(duree // 60)} min {int(duree % 60)} s (modifications comprises).")
    sys.exit(0 if all(resultats) else 1)


if __name__ == "__main__":
    main()

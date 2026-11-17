"""Remise à zéro des DONNÉES DE DÉMONSTRATION (avant une répétition ou la démo devant le jury).

    python scripts/remise_a_zero.py --oui

Si consentement-minimisation/catalogue/demarches.yaml diffère de la version committée (démarche ajoutée pendant une répétition), le script
le montre et propose de le restaurer (git checkout du fichier, copie de la version modifiée gardée en .bak).
    --restaurer-catalogue   restaurer sans poser la question
    --garder-catalogue      garder le catalogue modifié sans poser la question

N'EFFACE RIEN : le journal et la double trace sont ARCHIVÉS (renommés avec la date), puis le médiateur et les
registres repartent sur un journal neuf et des traces vides. L'historique d'Aïssata ne montre donc plus les
lignes des tests automatiques, et les limites de débit repartent de zéro.

Ce qui est archivé (date = heure UTC de la remise à zéro, ex. 20261116T170000Z) :
- volume du médiateur : mediateur.sqlite3 → mediateur-archive-<date>.sqlite3 (journal chaîné + demandes) ;
- volume de chaque registre : trace.sqlite3 → trace-archive-<date>.sqlite3 ;
- export SIGNÉ de chaque trace, pris juste avant l'arrêt, rangé à côté de l'archive du journal :
  trace-<registre>-archive-<date>.jwt (signé par le registre : le médiateur ne peut pas le modifier).

Vérifier une archive plus tard (chaîne + double trace) :
    docker compose exec mediateur python /journal/verifier.py /donnees/mediateur-archive-<date>.sqlite3 --registres

Garde : les clés des registres (mêmes empreintes), Keycloak (comptes, TOTP déjà enrôlés), le catalogue,
les adaptateurs. Sans « --oui », le script ne fait rien.
"""
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REGISTRES = ["etat-civil", "nationalite", "casier"]
ECRANS = ["guichet", "ussd_sim"]          # gardent des demandes en mémoire : redémarrés à la fin


def executer(*commande: str, entree: str | None = None) -> str:
    r = subprocess.run(list(commande), cwd=RACINE, capture_output=True, text=True, encoding="utf-8", input=entree)
    if r.returncode:
        raise SystemExit(f"Échec de « {' '.join(commande)} » : {r.stderr.strip()[-300:]}")
    return r.stdout


def dans_le_volume(service: str, script: str, entree: str | None = None) -> str:
    """Commande shell dans un conteneur TEMPORAIRE du service (même image, mêmes volumes, service arrêté).
    Aucune image à télécharger : fonctionne sans réseau."""
    return executer("docker", "compose", "run", "--rm", "--no-deps", "-T", "--entrypoint", "sh", service,
                    "-c", script, entree=entree)


def verifier_catalogue(date: str):
    """Une démarche ajoutée pendant une répétition (scène 4) ne doit pas rester pour la démo : si
    consentement-minimisation/catalogue/demarches.yaml diffère de la version committée, on le montre et on propose de le restaurer
    (git checkout). Une copie de la version modifiée est gardée (rien n'est perdu)."""
    fichier = "consentement-minimisation/catalogue/demarches.yaml"
    r = subprocess.run(["git", "diff", "HEAD", "--", fichier], cwd=RACINE, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode or not r.stdout.strip():
        return                                       # identique à la version committée (ou git absent)
    print(f"ATTENTION : {fichier} diffère de la version committée (démarche ajoutée pendant une répétition ?) :")
    for ligne in r.stdout.splitlines():
        if ligne.startswith(("+", "-")) and not ligne.startswith(("+++", "---")):
            print("    " + ligne)
    if "--restaurer-catalogue" in sys.argv:
        restaurer = True
    elif "--garder-catalogue" in sys.argv or not sys.stdin.isatty():
        restaurer = False
    else:
        try:
            restaurer = input("Restaurer la version committée (git checkout du fichier) ? [o/N] ").strip().lower() == "o"
        except EOFError:                             # terminal sans saisie possible : on ne touche à rien
            restaurer = False
            print()
    if not restaurer:
        print(f"Catalogue gardé tel quel. Pour le restaurer : git checkout HEAD -- {fichier}  "
              "(ou relancer avec --restaurer-catalogue)\n", flush=True)
        return
    copie = RACINE / f"consentement-minimisation/catalogue/demarches-avant-remise-{date}.yaml.bak"
    copie.write_bytes((RACINE / fichier).read_bytes())
    executer("git", "checkout", "HEAD", "--", fichier)
    print(f"Catalogue restauré (version committée). Copie de la version modifiée : {copie.relative_to(RACINE)}\n",
          flush=True)


def main():
    if "--oui" not in sys.argv:
        print(__doc__)
        raise SystemExit("Rien n'a été fait. Ajoutez --oui pour confirmer.")
    date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    # 0. Catalogue modifié pendant une répétition ? (avant le redémarrage : le journal neuf citera le bon catalogue)
    verifier_catalogue(date)

    # 1. Plus aucune demande ne doit arriver : on arrête d'abord les écrans, puis le médiateur
    print("Arrêt des écrans et du médiateur…", flush=True)
    executer("docker", "compose", "stop", *ECRANS, "mediateur")

    # 2. Export signé de chaque trace, pendant que les registres tournent encore (plus rien ne peut s'y ajouter)
    exports = {}
    for registre in REGISTRES:
        exports[registre] = executer(
            "docker", "compose", "exec", "-T", f"registre-{registre}", "python", "-c",
            "import json, urllib.request; "
            "print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/trace', timeout=5))['jeton'])").strip()
        print(f"  trace signée exportée : {registre}", flush=True)

    # 3. Arrêt des registres, puis renommage des fichiers dans leurs volumes (rien n'est supprimé)
    executer("docker", "compose", "stop", *[f"registre-{r}" for r in REGISTRES])
    for registre in REGISTRES:
        dans_le_volume(f"registre-{registre}", f"mv /trace/trace.sqlite3 /trace/trace-archive-{date}.sqlite3")
        print(f"  archivé : volume du registre {registre} → trace-archive-{date}.sqlite3", flush=True)
    dans_le_volume("mediateur", f"mv /donnees/mediateur.sqlite3 /donnees/mediateur-archive-{date}.sqlite3")
    print(f"  archivé : volume du médiateur → mediateur-archive-{date}.sqlite3", flush=True)
    for registre, jeton in exports.items():
        dans_le_volume("mediateur", f"cat > /donnees/trace-{registre}-archive-{date}.jwt", entree=jeton + "\n")
    print(f"  archivés : trace-<registre>-archive-{date}.jwt (exports signés, à côté du journal)", flush=True)

    # 4. Redémarrage : journal neuf (sa 1re ligne = chargement du catalogue), traces vides
    print("Redémarrage…", flush=True)
    executer("docker", "compose", "up", "-d", "--wait", "--no-deps", "mediateur", *[f"registre-{r}" for r in REGISTRES], *ECRANS)

    # 5. Contrôle : l'archive reste vérifiable (chaîne + double trace), le nouveau journal est intègre
    print("\nVérification de l'archive (chaîne + double trace) :", flush=True)
    archive = executer_verifier(f"/donnees/mediateur-archive-{date}.sqlite3", "--registres")
    print("Vérification du nouveau journal :", flush=True)
    neuf = executer_verifier()
    if not archive.startswith("OK  Journal intègre") or not neuf.startswith("OK  Journal intègre"):
        raise SystemExit("ATTENTION : chaîne rompue (voir ci-dessus).")
    if "ABSENTE du journal" in archive:
        # Le banc de pannes (scénario A) appelle exprès les registres SANS passer par le médiateur, comme le ferait
        # un médiateur compromis : la double trace doit les voir. Ce sont des faits, on les garde dans l'archive.
        print("NOTE : les écarts « ABSENTE du journal » ci-dessus sont les appels directs du banc de pannes "
              "(scénario A, médiateur compromis) : la double trace les a bien détectés.")
    print(f"\nDonnées de démonstration remises à zéro. Archive {date} conservée et vérifiable.")
    env = [l.strip() for l in (RACINE / ".env").read_text(encoding="utf-8").splitlines()]
    if "OUTILS_TEST=1" in env:
        print("ATTENTION : OUTILS_TEST=1 (comptes de test actifs). Avant la démonstration : OUTILS_TEST=0 dans .env, "
              "puis python scripts/outils_test.py")


def executer_verifier(*arguments: str) -> str:
    """verifier.py dans le conteneur du médiateur ; affiche et renvoie sa sortie."""
    r = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "/journal/verifier.py", *arguments],
                       cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    print(r.stdout + r.stderr, end="", flush=True)
    return r.stdout


if __name__ == "__main__":
    main()

"""Preuve de minimisation : les données d'un citoyen ne sortent JAMAIS du registre.

1. Lit, DANS chaque registre, les données témoins du citoyen (date et lieu de naissance, parents, détail
   du casier…) : ce qu'un registre bavard aurait pu laisser fuir.
2. Fait une vraie demande de bout en bout (agent.banc, connexion mot de passe + TOTP, guichet, médiateur, registres).
3. Cherche chaque témoin PARTOUT hors des registres : base SQLite du médiateur (journal, demandes en attente),
   logs du médiateur, du guichet, de l'USSD et de Caddy, page du guichet, réponses signées reçues par le guichet,
   historique de l'usager.
4. Affiche « introuvable ✅ » ou « TROUVÉ ❌ » pour chaque endroit, puis les réponses signées décodées.

Utilisation :
    python scripts/preuve_minimisation.py BF-0001
    python scripts/preuve_minimisation.py BF-0008 --demarche concours-direct
Code de sortie : 0 si aucun témoin n'est trouvé, 1 sinon.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client_guichet import AGENTS, RACINE, autorite_caddy, connecter, envoyer, reponses_signees, texte  # noqa: E402

REGISTRES = ("etat-civil", "nationalite", "casier")
LONGUEUR_MINIMALE = 4       # « F », « 0 », « M » : trop courts pour être des témoins (ils apparaissent partout)

# Lu DANS le conteneur du registre, avec son propre adaptateur : fiches du citoyen + vocabulaire des réponses
LECTURE_REGISTRE = """
import json, os, sys
from pathlib import Path
from app.adaptateur import Adaptateur
a = Adaptateur(Path(os.environ["ADAPTATEUR"]))
vocabulaire = [m for code, r in a.attributs.items() for m in (code, r["claim"])]
print(json.dumps({"identite": a.identite, "fiches": a.fiches(sys.argv[1]), "vocabulaire": vocabulaire}))
"""


def compose(*arguments: str, entree: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *arguments], cwd=RACINE, input=entree, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def variantes(valeur: str) -> list[str]:
    """Une date peut fuir sous une autre forme : 2001-03-14, 14/03/2001, 14-03-2001, 20010314."""
    formes = [valeur]
    morceaux = valeur.split("-")
    if len(morceaux) == 3 and all(m.isdigit() for m in morceaux):
        a, m, j = morceaux
        formes += [f"{j}/{m}/{a}", f"{j}-{m}-{a}", f"{a}{m}{j}"]
    return formes


def temoins_du_registre(lecture: dict) -> dict[str, list[str]]:
    """{nom du champ: formes à chercher}. On ne garde ni l'identifiant (il circule, c'est la question posée),
    ni les valeurs trop courtes, ni celles qui font partie du vocabulaire des réponses (« burkinabe »)."""
    temoins = {}
    for fiche in lecture["fiches"]:
        for champ, valeur in fiche.items():
            if isinstance(valeur, list):       # « ; » dans une valeur CSV : le reste de la ligne arrive en liste
                champ, valeur = "suite de la ligne" if champ in (None, "null") else champ, " ; ".join(valeur)
            valeur = (valeur or "").strip()
            if (champ == lecture["identite"] or len(valeur) < LONGUEUR_MINIMALE
                    or any(valeur.lower() in mot.lower() for mot in lecture["vocabulaire"])):
                continue
            temoins.setdefault(champ, [])
            temoins[champ] += [v for v in variantes(valeur) if v not in temoins[champ]]
    return temoins


def chercher(temoins: dict[str, list[str]], contenu: bytes) -> list[str]:
    """Témoins présents dans un contenu brut (octets UTF-8 : base SQLite, logs, page…)."""
    return [f"{champ} « {forme} »" for champ, formes in temoins.items() for forme in formes
            if forme.encode("utf-8") in contenu]


def base_du_mediateur() -> bytes:
    """Le FICHIER SQLite entier (journal, demandes, volets, y compris l'espace libéré), octet par octet."""
    with tempfile.TemporaryDirectory() as dossier:
        copie = Path(dossier) / "mediateur.sqlite3"
        resultat = compose("cp", "mediateur:/donnees/mediateur.sqlite3", str(copie))
        if resultat.returncode:
            raise SystemExit(f"Base du médiateur illisible : {resultat.stderr.strip()}")
        return copie.read_bytes()


def historique_usager(sujet: str) -> bytes:
    """Ce que voit l'usager (« Qui a consulté mes données »), par l'API usager du médiateur."""
    script = ("import httpx, pathlib, sys; c = pathlib.Path('/run/secrets/canal_usager').read_text().strip(); "
              "print(httpx.get(f'http://127.0.0.1:8000/usagers/{sys.argv[1]}/historique', "
              "headers={'X-Cle-Canal': c}).text)")
    return compose("exec", "-T", "mediateur", "python", "-c", script, sujet).stdout.encode("utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")       # ✅ et ❌ dans la console Windows
    parametres = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parametres.add_argument("usager", help="identifiant du citoyen, ex. BF-0001")
    parametres.add_argument("--demarche", default="concours-direct", help="démarche du catalogue")
    args = parametres.parse_args()

    # 1. Données témoins, lues dans chaque registre
    print(f"1. Données témoins de {args.usager}, lues DANS les registres :")
    temoins = {}
    for registre in REGISTRES:
        lecture = compose("exec", "-T", f"registre-{registre}", "python", "-", args.usager, entree=LECTURE_REGISTRE)
        if lecture.returncode:
            raise SystemExit(f"Registre {registre} illisible : {lecture.stderr.strip()[-300:]}")
        trouves = temoins_du_registre(json.loads(lecture.stdout))
        for champ, formes in trouves.items():
            print(f"   {registre:12} {champ:22} {formes[0]}")
            temoins[f"{registre}.{champ}"] = formes
    if not temoins:
        raise SystemExit("Aucune donnée témoin : citoyen absent des registres ? Choisissez-en un autre.")

    # 2. Une vraie demande, de bout en bout
    print(f"\n2. Demande « {args.demarche} » pour {args.usager} au guichet (agent.banc, mot de passe + TOTP)…")
    with httpx.Client(verify=autorite_caddy(), follow_redirects=True, timeout=30) as client:
        csrf = connecter(client, AGENTS["direction-concours"])
        page = envoyer(client, csrf, args.usager, args.demarche).text
    signees = reponses_signees(page)
    resultat = texte(page)
    debut = resultat.find("Usager :")
    print(f"   Résultat : {resultat[debut:debut + 400]}…")

    # 3. Recherche des témoins partout hors des registres
    print("\n3. Recherche des données témoins hors des registres :")
    endroits = {
        "base SQLite du médiateur (journal + demandes)": base_du_mediateur(),
        "historique de l'usager (API usager)": historique_usager(args.usager),
        "page du guichet (ce que voit l'agent)": texte(page).encode("utf-8"),
        "réponses signées reçues par le guichet": json.dumps(signees, ensure_ascii=False).encode("utf-8"),
    }
    for service in ("mediateur", "guichet", "ussd_sim", "portail", "caddy"):
        endroits[f"logs du conteneur {service}"] = compose("logs", "--no-color", service).stdout.encode("utf-8")
    fuites = 0
    for endroit, contenu in endroits.items():
        trouves = chercher(temoins, contenu)
        fuites += bool(trouves)
        print(f"   {endroit:48} " + (f"TROUVÉ ❌ {', '.join(trouves)}" if trouves else "introuvable ✅"))

    # 4. Ce que le guichet a réellement reçu
    print("\n4. Réponses signées reçues par le guichet (contenu complet, décodé) :")
    for attribut, claims in signees.items():
        print(f"   {attribut} : {json.dumps(claims, ensure_ascii=False)}")
    if not signees:
        print("   (aucune : registre indisponible ou demande refusée avant les registres)")
    print("\n" + ("Aucune donnée témoin hors des registres ✅" if not fuites else f"{fuites} endroit(s) avec une fuite ❌"))
    sys.exit(1 if fuites else 0)


if __name__ == "__main__":
    main()

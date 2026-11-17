"""Démonstration : un administrateur falsifie le journal directement dans le fichier SQLite.

Le script travaille sur une COPIE du journal (dans le conteneur du médiateur), pour que la démonstration
puisse être rejouée sans abîmer le vrai journal.

Utilisation :
    python resilience/falsifier_journal.py            # modifie la ligne 5 de la copie
    python resilience/falsifier_journal.py 12         # modifie la ligne 12
    python resilience/falsifier_journal.py --cacher   # CACHE la dernière consultation et recalcule toute la chaîne

1. Modifier une ligne : il supprime le déclencheur qui interdit les modifications, puis change une valeur.
   verifier.py indique la ligne exacte.
2. --cacher : l'administrateur habile supprime toutes les lignes de la dernière consultation puis RECALCULE la
   chaîne entière. La chaîne seule paraît intègre ! Mais la double trace (verifier.py --registres) le voit :
   les registres ont gardé, chez eux, la trace des réponses signées qu'ils ont envoyées.
"""
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

MODIFIER = """
import shutil, sqlite3, sys
n = int(sys.argv[1])
shutil.copy("/donnees/mediateur.sqlite3", "/tmp/journal-falsifie.sqlite3")
base = sqlite3.connect("/tmp/journal-falsifie.sqlite3", isolation_level=None)
avant = base.execute("SELECT demandeur, finalite FROM journal WHERE n = ?", (n,)).fetchone()
if avant is None:
    sys.exit(f"Pas de ligne {n} dans le journal.")
base.execute("DROP TRIGGER journal_sans_modification")
base.execute("UPDATE journal SET demandeur = 'mairie', finalite = 'autre chose' WHERE n = ?", (n,))
print(f"Ligne {n} modifiée dans la copie : demandeur {avant[0]!r} -> 'mairie', finalité {avant[1]!r} -> 'autre chose'")
"""

CACHER = """
import shutil, sqlite3, sys
sys.path.insert(0, "/app")
from tracabilite.journal import ZEROS, empreinte
shutil.copy("/donnees/mediateur.sqlite3", "/tmp/journal-falsifie.sqlite3")
base = sqlite3.connect("/tmp/journal-falsifie.sqlite3", isolation_level=None)
base.row_factory = sqlite3.Row
cible = base.execute("SELECT id_demande, demandeur, demarche FROM journal WHERE evenement = 'reponse-registre' "
                     "ORDER BY n DESC LIMIT 1").fetchone()
if cible is None:
    sys.exit("Aucune consultation dans le journal : faites d'abord une demande au guichet.")
base.execute("DROP TRIGGER journal_sans_modification")
base.execute("DROP TRIGGER journal_sans_suppression")
supprimees = base.execute("DELETE FROM journal WHERE id_demande = ?", (cible["id_demande"],)).rowcount
# Recalcul COMPLET de la chaîne : numéros, prev_hash et hash, comme le ferait un administrateur habile
lignes = [dict(l) for l in base.execute("SELECT * FROM journal ORDER BY n")]
base.execute("DELETE FROM journal")
precedente = ZEROS
for numero, ligne in enumerate(lignes, start=1):
    ligne.update(n=numero, prev_hash=precedente)
    ligne["hash"] = empreinte(ligne)
    precedente = ligne["hash"]
    base.execute(f"INSERT INTO journal ({', '.join(ligne)}) VALUES ({', '.join('?' * len(ligne))})", list(ligne.values()))
print(f"Consultation cachée dans la copie : {supprimees} lignes de la demande {cible['id_demande']} "
      f"({cible['demandeur']}, {cible['demarche']}) supprimées, puis chaîne entièrement recalculée")
"""


def main():
    cacher = "--cacher" in sys.argv
    ligne = next((a for a in sys.argv[1:] if a.isdigit()), "5")
    executer = ["docker", "compose", "exec", "-T", "mediateur", "python"]
    r = subprocess.run(executer + ["-", ligne], input=CACHER if cacher else MODIFIER, cwd=RACINE, text=True,
                       capture_output=True, encoding="utf-8")
    print((r.stdout + r.stderr).strip(), flush=True)
    if r.returncode:
        sys.exit(r.returncode)
    print("\nVérification du vrai journal :", flush=True)
    subprocess.run(executer + ["/journal/verifier.py"], cwd=RACINE)
    print("\nVérification de la copie falsifiée (chaîne seule) :", flush=True)
    subprocess.run(executer + ["/journal/verifier.py", "/tmp/journal-falsifie.sqlite3"], cwd=RACINE)
    if cacher:
        print("\nVérification de la copie falsifiée AVEC la double trace des registres :", flush=True)
        subprocess.run(executer + ["/journal/verifier.py", "/tmp/journal-falsifie.sqlite3", "--registres"], cwd=RACINE)


if __name__ == "__main__":
    main()

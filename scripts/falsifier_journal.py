"""Démonstration : un administrateur modifie une ligne du journal directement dans le fichier SQLite.

Le script travaille sur une COPIE du journal (dans le conteneur du médiateur), pour que la démonstration
puisse être rejouée sans abîmer le vrai journal. La manipulation est exactement celle d'un administrateur :
supprimer le déclencheur qui interdit les modifications, puis changer une valeur.

Utilisation :
    python scripts/falsifier_journal.py            # modifie la ligne 5 de la copie
    python scripts/falsifier_journal.py 12         # modifie la ligne 12
"""
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

FALSIFICATION = """
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


def main():
    ligne = sys.argv[1] if len(sys.argv) > 1 else "5"
    executer = ["docker", "compose", "exec", "-T", "mediateur", "python"]
    r = subprocess.run(executer + ["-", ligne], input=FALSIFICATION, cwd=RACINE, text=True, capture_output=True)
    print((r.stdout + r.stderr).strip(), flush=True)
    if r.returncode:
        sys.exit(r.returncode)
    print("Vérification du vrai journal :", flush=True)
    subprocess.run(executer + ["/journal/verifier.py"], cwd=RACINE)
    print("Vérification de la copie falsifiée :", flush=True)
    subprocess.run(executer + ["/journal/verifier.py", "/tmp/journal-falsifie.sqlite3"], cwd=RACINE)


if __name__ == "__main__":
    main()

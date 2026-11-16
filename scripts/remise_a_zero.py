"""Remise à zéro des DONNÉES DE DÉMONSTRATION (avant une répétition ou la démo devant le jury).

    python scripts/remise_a_zero.py --oui

Efface : le journal et les demandes du médiateur (volume mediateur_donnees) et la double trace des registres
(volumes trace_*). Ainsi l'historique d'Aïssata ne montre plus les lignes des tests automatiques, et les limites
de débit repartent de zéro.
Garde : les clés des registres (mêmes empreintes), Keycloak (comptes, TOTP déjà enrôlés), le catalogue, les adaptateurs.
Irréversible : le journal effacé ne peut pas être retrouvé. Sans « --oui », le script n'efface rien.
"""
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SERVICES = ["mediateur", "registre-etat-civil", "registre-nationalite", "registre-casier"]
VOLUMES = ["griot_mediateur_donnees", "griot_trace_etat_civil", "griot_trace_nationalite", "griot_trace_casier"]


def executer(*commande: str):
    r = subprocess.run(list(commande), cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise SystemExit(f"Échec de « {' '.join(commande)} » : {r.stderr.strip()[-300:]}")


def main():
    if "--oui" not in sys.argv:
        print(__doc__)
        raise SystemExit("Rien n'a été effacé. Ajoutez --oui pour confirmer.")
    print("Arrêt du médiateur et des registres…", flush=True)
    executer("docker", "compose", "stop", *SERVICES)
    executer("docker", "compose", "rm", "-f", *SERVICES)        # libère les volumes (les conteneurs sont recréés)
    for volume in VOLUMES:
        executer("docker", "volume", "rm", volume)
        print(f"  volume effacé : {volume}", flush=True)
    print("Redémarrage…", flush=True)
    executer("docker", "compose", "up", "-d", "--wait", *SERVICES)
    executer("docker", "compose", "restart", "guichet", "ussd_sim")    # oublie les demandes gardées en mémoire
    print("Données de démonstration remises à zéro : journal neuf, traces des registres vides, limites remises à zéro.")


if __name__ == "__main__":
    main()

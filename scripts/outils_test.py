"""Comptes de TEST (banc de pannes, scripts/demande.py) : ils n'existent que si OUTILS_TEST=1 dans .env.

    python scripts/outils_test.py          # applique .env : crée (OUTILS_TEST=1) ou supprime (sinon) les comptes
    python scripts/outils_test.py etat     # affiche seulement l'état

Trois comptes de service Keycloak (secret client, pas d'humain, pas de TOTP), chacun membre d'un service :
    outil-test-concours  -> Direction des concours – ministère des Serviteurs du peuple
    outil-test-bourses   -> Service des bourses
    outil-test-curieux   -> Service des bourses (sert à déclencher la limite « agent curieux »)
Ils suivent EXACTEMENT les mêmes règles que les agents (catalogue, double clé, limites de débit : aucune exemption).
Dans le journal, leurs actions apparaissent sous le nom « service-account-outil-test-… ».
Ceinture et bretelles : si OUTILS_TEST n'est pas 1, le médiateur ET les registres refusent leurs jetons.
DÉSACTIVER AVANT LA DÉMONSTRATION DEVANT LE JURY : OUTILS_TEST=0 dans .env, puis relancer ce script.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
COMPTES = {
    "outil-test-concours": "Direction des concours – ministère des Serviteurs du peuple",
    "outil-test-bourses": "Service des bourses",
    "outil-test-curieux": "Service des bourses",
}


def lire_env() -> dict:
    lignes = (RACINE / ".env").read_text(encoding="utf-8").splitlines()
    return dict(l.split("=", 1) for l in lignes if "=" in l and not l.lstrip().startswith("#"))


def kcadm(*arguments: str, entree: str | None = None) -> str:
    r = subprocess.run(["docker", "compose", "exec", "-T", "keycloak", "/opt/keycloak/bin/kcadm.sh", *arguments],
                       cwd=RACINE, input=entree, capture_output=True, text=True, encoding="utf-8",
                       env=os.environ | {"MSYS_NO_PATHCONV": "1"})
    if r.returncode:
        raise SystemExit(f"kcadm {arguments[0]} : {r.stderr.strip()[-300:]}")
    return r.stdout


def client_guichet() -> dict:
    """Les mêmes « mappers » que le guichet : rôles, groupes (= service) et audience « mediateur »."""
    realm = json.loads((RACINE / "keycloak/realm-griot.json").read_text(encoding="utf-8"))
    return next(c for c in realm["clients"] if c["clientId"] == "guichet")


def existants() -> dict[str, str]:
    clients = json.loads(kcadm("get", "clients", "-r", "griot", "--fields", "id,clientId"))
    return {c["clientId"]: c["id"] for c in clients if c["clientId"] in COMPTES}


def main():
    env = lire_env()
    actif = env.get("OUTILS_TEST", "0").strip() == "1"
    kcadm("config", "credentials", "--server", "http://localhost:8080", "--realm", "master", "--user", "admin",
          "--password", env["KEYCLOAK_ADMIN_PASSWORD"])
    presents = existants()
    if sys.argv[1:] != ["etat"]:
        if actif:
            groupes = {g["name"]: g["id"] for g in json.loads(kcadm("get", "groups", "-r", "griot"))}
            mappers = client_guichet()["protocolMappers"]
            for nom, groupe in COMPTES.items():
                if nom not in presents:
                    kcadm("create", "clients", "-r", "griot", "-f", "-", entree=json.dumps({
                        "clientId": nom, "name": nom, "description": "Compte de TEST (OUTILS_TEST=1)",
                        "enabled": True, "protocol": "openid-connect", "publicClient": False,
                        "clientAuthenticatorType": "client-secret", "secret": env["OUTILS_TEST_SECRET"],
                        "standardFlowEnabled": False, "directAccessGrantsEnabled": False,
                        "serviceAccountsEnabled": True, "attributes": {"access.token.lifespan": "300"},
                        "protocolMappers": mappers}))
                utilisateur = json.loads(kcadm("get", "users", "-r", "griot", "-q",
                                               f"username=service-account-{nom}"))[0]
                kcadm("add-roles", "-r", "griot", "--uusername", f"service-account-{nom}", "--rolename", "agent-guichet")
                kcadm("update", f"users/{utilisateur['id']}/groups/{groupes[groupe]}", "-r", "griot",
                      "-s", "realm=griot", "-s", f"userId={utilisateur['id']}", "-s", f"groupId={groupes[groupe]}", "-n")
        else:
            for nom, identifiant in presents.items():
                kcadm("delete", f"clients/{identifiant}", "-r", "griot")
        # Le médiateur et les registres lisent OUTILS_TEST au démarrage : compose les recrée si la valeur a changé
        subprocess.run(["docker", "compose", "up", "-d", "--wait", "mediateur", "registre-etat-civil",
                        "registre-nationalite", "registre-casier"], cwd=RACINE, capture_output=True)
        presents = existants()
    print(f"OUTILS_TEST={'1' if actif else '0'} dans .env ; comptes de test dans Keycloak : "
          f"{', '.join(sorted(presents)) if presents else 'aucun'}")
    if actif:
        print("ATTENTION : comptes de test ACTIFS. Avant la démonstration : OUTILS_TEST=0 puis relancer ce script.")


if __name__ == "__main__":
    main()

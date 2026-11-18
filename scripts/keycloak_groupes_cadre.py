"""Ajoute à un Keycloak DÉJÀ installé les groupes et agents de démonstration du cadre, SANS réimporter le realm
(les TOTP déjà enrôlés sont conservés). Idempotent : ce qui existe est laissé tel quel.

    .venv\\Scripts\\python scripts\\keycloak_groupes_cadre.py

Groupes = annuaire.yaml (« groupe » de chaque service) ; agents = ceux du realm du dépôt qui sont dans ces groupes
(socle/keycloak/realm-griot.json). Un agent créé ici doit enrôler son TOTP à sa première connexion.
"""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outils_test import RACINE, kcadm, lire_env  # noqa: E402


def main():
    env = lire_env()
    kcadm("config", "credentials", "--server", "http://localhost:8080", "--realm", "master", "--user", "admin",
          "--password", env.get("KEYCLOAK_ADMIN_PASSWORD", "demo-admin-keycloak-a-changer"))   # défaut de docker-compose.yml (sans .env)
    annuaire = yaml.safe_load((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_text(encoding="utf-8"))
    realm = json.loads((RACINE / "socle/keycloak/realm-griot.json").read_text(encoding="utf-8"))
    groupes = {g["name"]: g["id"] for g in json.loads(kcadm("get", "groups", "-r", "griot"))}
    for code, service in annuaire["services"].items():
        if service["groupe"] not in groupes:
            kcadm("create", "groups", "-r", "griot", "-f", "-",
                  entree=json.dumps({"name": service["groupe"], "attributes": {"code": [code]}}))
            print(f"groupe créé : {service['groupe']}")
    groupes = {g["name"]: g["id"] for g in json.loads(kcadm("get", "groups", "-r", "griot"))}
    utiles = {s["groupe"] for s in annuaire["services"].values()}
    for u in realm["users"]:
        groupe = (u.get("groups") or [""])[0].lstrip("/")
        if groupe not in utiles:
            continue
        trouves = json.loads(kcadm("get", "users", "-r", "griot", "-q", f"username={u['username']}", "-q", "exact=true"))
        if trouves:
            identifiant = trouves[0]["id"]
        else:
            fiche = {k: u[k] for k in ("username", "enabled", "firstName", "lastName", "attributes", "credentials",
                                       "requiredActions") if k in u}
            kcadm("create", "users", "-r", "griot", "-f", "-", entree=json.dumps(fiche))
            identifiant = json.loads(kcadm("get", "users", "-r", "griot", "-q", f"username={u['username']}",
                                           "-q", "exact=true"))[0]["id"]
            for role in u.get("realmRoles", []):
                kcadm("add-roles", "-r", "griot", "--uid", identifiant, "--rolename", role)
            print(f"agent créé : {u['username']}")
        # Groupe du service (ajout idempotent ; les anciens groupes de l'agent sont retirés)
        actuels = {g["name"]: g["id"] for g in json.loads(kcadm("get", f"users/{identifiant}/groups", "-r", "griot"))}
        for nom, gid in actuels.items():
            if nom != groupe:
                kcadm("delete", f"users/{identifiant}/groups/{gid}", "-r", "griot")
        if groupe not in actuels:
            kcadm("update", f"users/{identifiant}/groups/{groupes[groupe]}", "-r", "griot", "-s", "realm=griot",
                  "-s", f"userId={identifiant}", "-s", f"groupId={groupes[groupe]}", "-n")
            print(f"{u['username']} -> {groupe}")


if __name__ == "__main__":
    main()

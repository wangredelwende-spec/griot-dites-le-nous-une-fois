"""Le realm du dépôt (socle/keycloak/realm-griot.json) suffit à reconstruire la pile à partir de zéro.

Keycloak l'importe au premier démarrage (--import-realm) : groupes, comptes, rôles et flux TOTP doivent donc y être,
et correspondre aux services de l'annuaire et des registres. Seuls les TOTP sont à réenrôler (QR code).
"""
import json

import yaml
from conftest import RACINE

REALM = json.loads((RACINE / "socle/keycloak/realm-griot.json").read_text(encoding="utf-8"))
GROUPES = {g["name"] for g in REALM["groups"]}
COMPTES = {u["username"]: u for u in REALM["users"]}
TRIBUNAL = "Tribunal – certificats de nationalité"
CEFORE = "CEFORE – guichet des entreprises"
CONCOURS = "Direction des concours – ministère des Serviteurs du peuple"


def test_groupes_renommes_presents_partout():
    assert {TRIBUNAL, CONCOURS, CEFORE} == GROUPES
    annuaire = yaml.safe_load((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_text(encoding="utf-8"))
    assert {s["groupe"] for s in annuaire["services"].values()} <= GROUPES
    for registre in ("etat-civil", "nationalite", "casier"):
        adaptateur = yaml.safe_load((RACINE / f"registres/adaptateurs/{registre}.yaml").read_text(encoding="utf-8"))
        assert set(adaptateur["groupes"]) <= GROUPES, registre


def test_comptes_de_demo():
    attendus = {"moussa.kone": TRIBUNAL, "issa.sawadogo": CONCOURS, "awa.ouedraogo": CEFORE,
                "agent.curieux": CEFORE, "agent.banc": CONCOURS, "agent.banc.cefore": CEFORE}
    for nom, groupe in attendus.items():
        u = COMPTES[nom]
        assert u["enabled"] and u["groups"] == [f"/{groupe}"] and u["realmRoles"] == ["agent-guichet"], nom
        assert u["requiredActions"] == ["CONFIGURE_TOTP"], nom          # TOTP réenrôlé à la 1re connexion
    assert COMPTES["controle.cil"]["realmRoles"] == ["controleur"] and not COMPTES["controle.cil"].get("groups")


def test_mot_de_passe_puis_totp_obligatoire():
    flux = {f["alias"]: f for f in REALM["authenticationFlows"]}
    etapes = [(e.get("authenticator"), e["requirement"])
              for e in flux["mot-de-passe-puis-otp"]["authenticationExecutions"]]
    assert REALM["browserFlow"] == "navigateur-otp-obligatoire"
    assert etapes == [("auth-username-password-form", "REQUIRED"), ("auth-otp-form", "REQUIRED")]
    assert REALM["bruteForceProtected"] and REALM["loginTheme"] == "griot"

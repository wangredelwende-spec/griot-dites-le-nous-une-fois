"""Banc de pannes : joue les scénarios du jury contre la pile qui tourne et affiche ✅ / ❌ ligne par ligne.

Prérequis : `docker compose up -d --wait`, puis comptes de test activés :
    OUTILS_TEST=1 dans .env, puis   python scripts/outils_test.py
Utilisation :
    python scripts/banc_de_pannes.py
À la fin, remettre OUTILS_TEST=0 (puis python scripts/outils_test.py) avant la démonstration devant le jury.

Les appels « outil » passent par les comptes de test outil-test-* (jeton Keycloak, mêmes règles que les agents,
aucune exemption) ; ils sont exécutés DANS le conteneur du médiateur (réseau interne). Chaque scénario utilise
d'autres citoyens pour ne pas déclencher les limites de débit, sauf le scénario « agent curieux ».
Code de sortie : 0 si tout est ✅.
"""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client_guichet import RACINE, autorite_caddy, connecter, envoyer, texte  # noqa: E402

FINALITES = {code: d["finalite"] for code, d in
             yaml.safe_load((RACINE / "catalogue/demarches.yaml").read_text(encoding="utf-8"))["demarches"].items()}

# Fonctions disponibles dans le conteneur du médiateur pour chaque scénario
PRELUDE = r'''
import json, os, sqlite3, time, uuid
import httpx, jwt

def jeton(client):
    """Jeton Keycloak d'un compte de test (identifiants du client, réseau interne)."""
    r = httpx.post("http://keycloak:8080/realms/griot/protocol/openid-connect/token", timeout=10,
                   data={"grant_type": "client_credentials", "client_id": client,
                         "client_secret": os.environ["OUTILS_TEST_SECRET"]})
    r.raise_for_status()
    return r.json()["access_token"]

def demander(client, demarche, sujet, finalite, **plus):
    corps = {"id_demande": str(uuid.uuid4()), "demarche": demarche, "sujet_ref": sujet, "finalite": finalite} | plus
    return corps, envoyer(client, corps)

def envoyer(client, corps):
    entetes = {"Authorization": "Bearer " + jeton(client)}
    debut = time.monotonic()
    r = httpx.post("http://127.0.0.1:8000/demandes", json=corps, headers=entetes, timeout=20)
    return {"code": r.status_code, "corps": r.json(), "duree": round(time.monotonic() - debut, 2)}

def suivre(client, id_demande):
    r = httpx.get(f"http://127.0.0.1:8000/demandes/{id_demande}", headers={"Authorization": "Bearer " + jeton(client)})
    return r.json()

CANAL = open("/run/secrets/canal_usager").read().strip()

def usager(methode, chemin, corps=None):
    r = httpx.request(methode, "http://127.0.0.1:8000" + chemin, json=corps, headers={"X-Cle-Canal": CANAL}, timeout=10)
    return r.json()

def journal(id_demande):
    base = sqlite3.connect("file:/donnees/mediateur.sqlite3?mode=ro", uri=True)
    base.row_factory = sqlite3.Row
    return [dict(l) for l in base.execute("SELECT agent, evenement, resultat, registre, attribut, motif FROM journal "
                                          "WHERE id_demande = ? ORDER BY n", (id_demande,))]

def registre_direct(registre, corps, entetes):
    """Appel DIRECT d'un registre (comme le ferait un médiateur compromis) ; réponse signée décodée."""
    r = httpx.post(f"http://registre-{registre}:8000/attributs", json=corps, headers=entetes, timeout=10)
    cle = open(f"/publiques/{registre}/cle.pem", "rb").read()
    return jwt.decode(r.json()["jeton"], cle, algorithms=["EdDSA"], audience=corps["destinataire"])

resultat = {}
'''

# Citoyens de la DÉMO devant le jury : le banc ne les utilise JAMAIS (sinon il consommerait leur limite de 5 demandes
# par 24 h et remplirait leur historique). Vérifié par tests/test_banc.py. Ordre fixe : banc -> remise à zéro -> démo.
CITOYENS_DE_LA_DEMO = {"BF-0012", "BF-0005", "BF-0015", "BF-0001"}
# BF-0021 : citoyen fictif RÉSERVÉ au banc (adulte ordinaire, burkinabè, casier vierge), jamais montré en démo.

RESULTATS: list[bool] = []
APPELS_DIRECTS: set[str] = set()     # demandes envoyées directement aux registres (scénario A), sans le médiateur
PREFIXE_DIRECT = "appel-direct-banc-"    # repère ces appels d'un passage du banc à l'autre (traces en ajout seul)


def lire_env() -> dict:
    lignes = (RACINE / ".env").read_text(encoding="utf-8").splitlines()
    return dict(l.split("=", 1) for l in lignes if "=" in l and not l.lstrip().startswith("#"))


ENV = lire_env()


def dans_le_mediateur(code: str) -> dict:
    """Exécute PRELUDE + code dans le conteneur du médiateur ; le code remplit « resultat »."""
    r = subprocess.run(["docker", "compose", "exec", "-T", "-e", f"OUTILS_TEST_SECRET={ENV.get('OUTILS_TEST_SECRET', '')}",
                        "mediateur", "python", "-"], cwd=RACINE, capture_output=True, text=True, encoding="utf-8",
                       input=PRELUDE + code + "\nprint(json.dumps(resultat, ensure_ascii=False))\n")
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def panne(registre: str, mode: str):
    subprocess.run([sys.executable, str(RACINE / "scripts/panne.py"), registre, mode], cwd=RACINE,
                   capture_output=True, check=True)


def noter(titre: str, ok: bool, preuve: str, detail: str = ""):
    RESULTATS.append(ok)
    print(f"{'✅' if ok else '❌'} {titre} : {preuve}" + ("" if ok else f"\n      détail : {detail[:500]}"), flush=True)
    if not ok and "bloqu" in detail:
        print("      (limite de débit atteinte par des passages précédents : remettre les données de démo à zéro, "
              "ou attendre)", flush=True)


def volet(reponse: dict, attribut: str) -> dict:
    return next((v for v in reponse.get("volets", []) if v["attribut"] == attribut), {})


def concours(sujet: str, finalite: str = FINALITES["concours-adjoints"], **plus) -> str:
    """Code d'une demande « Concours direct » par outil-test-concours."""
    return (f"d, r = demander('outil-test-concours', 'concours-adjoints', {sujet!r}, {finalite!r}, **{plus!r})\n"
            "resultat.update(r=r, journal=journal(d['id_demande']), id=d['id_demande'])\n")


# --------------------------------------------------------------------------------------------- scénarios

def registre_coupe():
    panne("etat-civil", "coupe")
    try:
        x = dans_le_mediateur(concours("BF-0002"))
        age, autres = volet(x["r"]["corps"], "age_entre"), [volet(x["r"]["corps"], a) for a in
                                                             ("nationalite_burkinabe", "casier_judiciaire_vierge")]
        ligne = any(l["resultat"] == "indisponible" and l["registre"] == "etat-civil" for l in x["journal"])
        noter("1. Registre coupé (API)", age.get("statut") == "indisponible" and "rien n'a été deviné" in age.get("motif", "")
              and all(v.get("jeton") for v in autres) and ligne,
              f"« {age.get('motif')} », les 2 autres registres répondent, ligne « indisponible » au journal", json.dumps(x))
        # Le guichet (agent.banc) : un message clair, pas d'écran blanc
        with httpx.Client(verify=autorite_caddy(), follow_redirects=True, timeout=30) as client:
            page = envoyer(client, connecter(client, "agent.banc"), "BF-0002", "concours-adjoints")
        lisible = texte(page.text)
        noter("1. Registre coupé (guichet)", page.status_code == 200 and "rien n'a été deviné" in lisible
              and "résultat incomplet" in lisible, "page lisible : « … indisponible … rien n'a été deviné », "
              "« résultat incomplet, aucune conclusion »", lisible[-400:])
    finally:
        panne("etat-civil", "normal")


def registre_lent():
    panne("etat-civil", "lent")
    try:
        x = dans_le_mediateur(concours("BF-0010"))      # jamais un citoyen de la démo (CITOYENS_DE_LA_DEMO)
        age, duree = volet(x["r"]["corps"], "age_entre"), x["r"]["duree"]
        noter("2. Registre lent", age.get("statut") == "indisponible" and "délai dépassé" in age.get("motif", "")
              and 2.5 <= duree <= 6, f"refus après {duree} s : « {age.get('motif')} »", json.dumps(x))
    finally:
        panne("etat-civil", "normal")


def reponse_corrompue():
    panne("etat-civil", "corrompu")
    try:
        x = dans_le_mediateur(concours("BF-0006"))
        age = volet(x["r"]["corps"], "age_entre")
        alerte = any(l["evenement"] == "alerte" and l["registre"] == "etat-civil" for l in x["journal"])
        noter("3. Réponse corrompue", "signature invalide" in age.get("motif", "") and not age.get("jeton") and alerte,
              f"« {age.get('motif')} » + ligne d'alerte au journal", json.dumps(x))
    finally:
        panne("etat-civil", "normal")


def demande_rejouee():
    x = dans_le_mediateur(f"""
d, premiere = demander('outil-test-concours', 'concours-adjoints', 'BF-0011', {FINALITES['concours-adjoints']!r})
seconde = envoyer('outil-test-concours', d)
resultat.update(premiere=premiere["corps"], seconde=seconde["corps"], journal=journal(d['id_demande']))
""")
    appels = sum(l["evenement"] == "reponse-registre" for l in x["journal"])
    p, s = x["premiere"], x["seconde"]
    noter("4. Demande rejouée", p.get("statut") == s.get("statut") == "remise" and appels == 3
          and all(v.get("jeton") for v in p["volets"]) and not any(v.get("jeton") for v in s.get("volets", [])),
          f"même statut « {s.get('statut')} », registres appelés une seule fois ({appels} réponses), "
          "réponses signées remises une seule fois", json.dumps(x))


def mauvaise_finalite():
    x = dans_le_mediateur(concours("BF-0021", finalite="curiosité"))
    r = x["r"]["corps"]
    appels = sum(l["evenement"] == "reponse-registre" for l in x["journal"])
    noter("5. Mauvaise finalité", r.get("statut") == "refuse" and r.get("motif") == "finalité non autorisée" and appels == 0,
          "« finalité non autorisée », aucun registre appelé", json.dumps(x))
    x = dans_le_mediateur(concours("BF-0021", attributs=["age_entre", "nationalite_burkinabe",
                                                         "casier_judiciaire_vierge", "personne_connue"]))
    r = x["r"]["corps"]
    noter("5 bis. Attribut demandé en plus", r.get("statut") == "refuse" and "attributs non autorisés" in r.get("motif", ""),
          f"« {r.get('motif')} »", json.dumps(x))


def renforcements_registre():
    """A. médiateur compromis : le registre vérifie lui-même l'agent ; B. seuils non déclarés refusés."""
    ids = [PREFIXE_DIRECT + str(uuid.uuid4()) for _ in range(3)]
    APPELS_DIRECTS.update(ids)
    x = dans_le_mediateur(f"ids = {ids!r}\n" + """
corps = {"id_demande": ids[0], "attribut": "casier_judiciaire_vierge", "sujet_ref": "BF-0008",
         "destinataire": "direction-concours"}
resultat["sans_jeton"] = registre_direct("casier", corps, {})
corps = {"id_demande": ids[1], "attribut": "age_entre", "sujet_ref": "BF-0021",
         "destinataire": "direction-concours", "parametres": {"min": 25, "date_reference": time.strftime("%Y-%m-%d")}}
resultat["seuil"] = registre_direct("etat-civil", corps, {"Authorization": "Bearer " + jeton("outil-test-concours")})
corps = {"id_demande": ids[2], "attribut": "casier_judiciaire_vierge", "sujet_ref": "BF-0008",
         "destinataire": "direction-concours"}
resultat["usurpation"] = registre_direct("casier", corps, {"Authorization": "Bearer " + jeton("outil-test-bourses")})
""")
    noter("A. Appel direct au registre sans jeton d'agent", x["sans_jeton"]["statut"] == "refus",
          f"refus signé par le registre : « {x['sans_jeton'].get('motif')} »", json.dumps(x))
    noter("A bis. Service usurpé (jeton des bourses, se dit « concours »)", x["usurpation"]["statut"] == "refus",
          f"« {x['usurpation'].get('motif')} »", json.dumps(x))
    noter("B. Seuil d'âge non déclaré (25 ans)", x["seuil"].get("motif") == "paramètres non autorisés par le registre pour ce service",
          f"« {x['seuil'].get('motif')} » : impossible de reconstituer une date de naissance", json.dumps(x))


def agent_curieux():
    x = dans_le_mediateur(f"""
statuts = []
for i in range(1, 7):
    d, r = demander('outil-test-curieux', 'verifier-majorite', f'BANC-CUR-{{i}}', {FINALITES['verifier-majorite']!r})
    statuts.append(r["corps"].get("statut"))
resultat.update(statuts=statuts, motif=r["corps"].get("motif"),
                historique=[l for l in usager("GET", "/usagers/BANC-CUR-1/historique") if l["evenement"] == "alerte"][:1])
""")
    alerte = x["historique"] and "bloqué" in x["historique"][0]["motif"]
    noter("6. Agent qui consulte trop de citoyens", x["statuts"][-1] == "bloquee" and bool(alerte),
          f"6e citoyen : « {x['motif']} » ; ALERTE dans l'historique des citoyens consultés", json.dumps(x))


def passeport_casier_en_panne():
    """Passeport (consentement, nationalité + casier, pas d'âge) pendant que le CASIER est coupé, lent puis
    corrompu : l'usager ne voit que ce qui est arrivé (signé), le guichet reçoit la réponse signée de la
    nationalité et un volet en échec, jamais tout."""
    F = FINALITES["passeport-ordinaire"]
    for mode, sujet, attendu in (("coupe", "BF-0021", "injoignable"), ("lent", "BF-0002", "délai dépassé"),
                                 ("corrompu", "BF-0006", "réponse corrompue")):
        panne("casier", mode)
        try:
            x = dans_le_mediateur(f"""
d, r = demander('outil-test-passeport', 'passeport-ordinaire', {sujet!r}, {F!r})
attente = usager("GET", "/usagers/{sujet}/en-attente")
usager("POST", f"/demandes/{{d['id_demande']}}/confirmer", {{"sujet_ref": {sujet!r}}})
resultat.update(r=r, attente=attente, remise=suivre('outil-test-passeport', d['id_demande']))
""")
        finally:
            panne("casier", "normal")
        avant, remise = x["r"]["corps"], x["remise"]
        casier = volet(remise, "interdiction_sortie_territoire")
        signes = [volet(remise, "nationalite_burkinabe").get("jeton")]
        apercu = x["attente"][0]["apercu"] if x["attente"] else ""
        ok = (avant["statut"] == "en_attente" and "interdiction" not in apercu and "Rien d'autre" in apercu
              and "majeur" not in apercu and not volet(remise, "age_entre")
              and remise.get("statut") == "remise" and all(signes) and not casier.get("jeton")
              and casier.get("statut") in ("indisponible", "refuse") and attendu in casier.get("motif", ""))
        noter(f"10. Passeport, casier {mode}", ok,
              f"aperçu sans le casier ni l'âge, nationalité signée remise, casier « {casier.get('motif')} » : "
              "résultat partiel, jamais de « oui » global", json.dumps(x, ensure_ascii=False))


def consentement():
    x = dans_le_mediateur(f"""
F = {FINALITES['bourse-nationale']!r}
d, r = demander('outil-test-bourses', 'bourse-nationale', 'BF-0014', F)
usager("POST", f"/demandes/{{d['id_demande']}}/refuser", {{"sujet_ref": "BF-0014"}})
resultat["refus"] = [r["corps"]["statut"], suivre('outil-test-bourses', d['id_demande'])]
d, r = demander('outil-test-bourses', 'bourse-nationale', 'BF-0016', F)
usager("POST", f"/demandes/{{d['id_demande']}}/confirmer", {{"sujet_ref": "BF-0016"}})
usager("POST", f"/demandes/{{d['id_demande']}}/retirer", {{"sujet_ref": "BF-0016"}})
resultat["retrait"] = [r["corps"]["statut"], suivre('outil-test-bourses', d['id_demande'])]
d, r = demander('outil-test-bourses', 'bourse-nationale', 'BF-0020', F)
# On « avance l'horloge » de cette seule demande (table de travail, pas le journal) au lieu d'attendre 10 minutes
base = sqlite3.connect("/donnees/mediateur.sqlite3", isolation_level=None)
base.execute("UPDATE demandes SET expire_le = 0 WHERE id_demande = ?", (d['id_demande'],))
base.close()
resultat["expiration"] = [r["corps"]["statut"], suivre('outil-test-bourses', d['id_demande'])]
""")
    for cas, attendu in (("refus", "refuse"), ("retrait", "retiree"), ("expiration", "expiree")):
        avant, apres = x[cas]
        rien = not any(v.get("jeton") for v in apres.get("volets", []))
        noter(f"7. Consentement {cas}", avant == "en_attente" and apres.get("statut") == attendu and rien,
              f"« {apres.get('motif')} », rien n'est remis au guichet", json.dumps(x[cas]))


def portail_web():
    """Portail web : une confirmation faite avec le secret du canal web est écrite « canal = web » et visible dans
    l'historique servi à l'USSD (même journal). Puis le portail arrêté seul : message clair, l'USSD continue."""
    x = dans_le_mediateur(f"""
F = {FINALITES['bourse-nationale']!r}
WEB = open("/run/secrets/canal_web").read().strip()
d, r = demander('outil-test-bourses', 'bourse-nationale', 'BF-0017', F)
c = httpx.post(f"http://127.0.0.1:8000/demandes/{{d['id_demande']}}/confirmer", json={{"sujet_ref": "BF-0017"}},
               headers={{"X-Cle-Canal": WEB}}, timeout=10).json()
base = sqlite3.connect("file:/donnees/mediateur.sqlite3?mode=ro", uri=True)
resultat["canal"] = (base.execute("SELECT canal FROM journal WHERE hash = ?", (c.get("empreinte", ""),)).fetchone() or [""])[0]
resultat["vu_par_ussd"] = [l["canal"] for l in usager("GET", "/usagers/BF-0017/historique")
                           if l["empreinte"] == c.get("empreinte")]
resultat["remise"] = suivre('outil-test-bourses', d['id_demande']).get("statut")
""")
    noter("11. Portail web : confirmation", x["canal"] == "web" and x["vu_par_ussd"] == ["web"] and x["remise"] == "remise",
          "écrite au journal avec canal = web, visible dans l'historique USSD, remise au guichet", json.dumps(x))
    with httpx.Client(verify=autorite_caddy(), timeout=10) as client:
        subprocess.run(["docker", "compose", "stop", "portail"], cwd=RACINE, capture_output=True, check=True)
        try:
            arrete = client.get("https://usager.griot.test/portail")
            ussd = client.get("https://usager.griot.test/")
        finally:
            subprocess.run(["docker", "compose", "up", "-d", "--wait", "--no-deps", "portail"], cwd=RACINE,
                           capture_output=True, check=True)
        relance = client.get("https://usager.griot.test/portail")
    noter("11 bis. Portail web arrêté seul", arrete.status_code == 503 and "Portail web arrêté" in arrete.text
          and ussd.status_code == 200 and relance.status_code == 200,
          "« Portail web arrêté. Rien n'a été transmis » ; le *226# répond toujours ; relancé d'une commande",
          f"{arrete.status_code} {arrete.text[:80]} | USSD {ussd.status_code} | relance {relance.status_code}")


def journal_modifie():
    sortie = subprocess.run([sys.executable, str(RACINE / "scripts/falsifier_journal.py"), "5"], cwd=RACINE,
                            capture_output=True, text=True, encoding="utf-8").stdout
    noter("8. Ligne du journal modifiée", "OK  Journal intègre" in sortie and "ERREUR  Ligne 5 modifiée" in sortie,
          "vrai journal intègre ; copie falsifiée : « Ligne 5 modifiée »", sortie)
    sortie = subprocess.run([sys.executable, str(RACINE / "scripts/falsifier_journal.py"), "--cacher"], cwd=RACINE,
                            capture_output=True, text=True, encoding="utf-8").stdout
    noter("8 bis. Consultation cachée + chaîne recalculée", "ABSENTE du journal du médiateur" in sortie,
          "la chaîne seule ne voit rien, la double trace des registres le détecte", sortie)


def reseau_coupe():
    reseaux = {nom: subprocess.run(["docker", "network", "inspect", "-f", "{{.Internal}}", f"griot_{nom}"],
                                   capture_output=True, text=True).stdout.strip()
               for nom in ("interne", "registres", "cles-agents")}
    sortie = []
    for service in ("mediateur", "registre-casier"):
        r = subprocess.run(["docker", "compose", "exec", "-T", service, "python", "-c",
                            "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)"],
                           cwd=RACINE, capture_output=True, text=True)
        sortie.append(r.returncode != 0)
    noter("9. Réseau / wifi coupé", all(v == "true" for v in reseaux.values()) and all(sortie),
          "réseaux Docker internes, aucun conteneur ne peut joindre Internet : tout fonctionne en local "
          "(couper le wifi en vrai pendant la démo)", json.dumps(reseaux))


def double_trace():
    """Les appels DIRECTS du scénario A (comme un médiateur compromis) ont été tracés par les registres mais
    pas par le médiateur : la double trace doit les signaler, eux et RIEN d'autre."""
    r = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "/journal/verifier.py", "--registres"],
                       cwd=RACINE, capture_output=True, text=True, encoding="utf-8")
    ecarts = [l for l in r.stdout.splitlines() if l.startswith("ERREUR")]
    signales = {i for i in APPELS_DIRECTS if any(i in l for l in ecarts)}
    autres = [l for l in ecarts if PREFIXE_DIRECT not in l]
    noter("Fin. Journal intègre + double trace", r.stdout.startswith("OK  Journal intègre") and not autres
          and signales == APPELS_DIRECTS,
          f"{r.stdout.splitlines()[0][4:]} ; les {len(APPELS_DIRECTS)} appels directs du scénario A sont signalés "
          "« ABSENTS du journal du médiateur », et rien d'autre", "\n".join(autres) or r.stdout + r.stderr)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if ENV.get("OUTILS_TEST") != "1":
        raise SystemExit("Comptes de test désactivés : mettez OUTILS_TEST=1 dans .env, lancez "
                         "« python scripts/outils_test.py », puis relancez le banc.")
    debut = time.monotonic()
    print("Banc de pannes Griot : scénarios du jury contre la pile qui tourne\n", flush=True)
    for scenario in (registre_coupe, registre_lent, reponse_corrompue, passeport_casier_en_panne,
                     demande_rejouee, mauvaise_finalite,
                     renforcements_registre, agent_curieux, consentement, portail_web, journal_modifie, reseau_coupe, double_trace):
        try:
            scenario()
        except Exception as e:      # un scénario qui plante est un échec, pas un arrêt du banc
            noter(scenario.__name__, False, "erreur pendant le scénario", repr(e))
    print(f"\n{sum(RESULTATS)}/{len(RESULTATS)} vérifications réussies en {time.monotonic() - debut:.0f} s", flush=True)
    print(subprocess.run([sys.executable, str(RACINE / "scripts/panne.py")], capture_output=True, text=True).stdout)
    print("Ensuite, dans cet ordre : OUTILS_TEST=0 + outils_test.py, puis remise_a_zero.py --oui, puis la démo.\n"
          "Jamais de banc après la dernière remise à zéro (il consommerait les limites et remplirait les historiques).")
    sys.exit(0 if all(RESULTATS) else 1)


if __name__ == "__main__":
    main()

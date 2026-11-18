"""Banc de pannes : les situations de l'épreuve du jury, jouées contre la PILE QUI TOURNE (docker compose), une ligne
✅ / ❌ par situation. Les administrations passent par leur CLÉ API (pas de Keycloak, pas de TOTP) ; l'usager par l'API
usager de la passerelle (secret du canal, comme l'USSD).

    .venv\\Scripts\\python resilience\\banc_de_pannes.py

Les pannes sont posées par resilience/panne.py (variable PANNE d'un registre, ou conteneur arrêté) puis TOUJOURS
retirées. Le banc n'utilise jamais la citoyenne de la démonstration (Aminata Kaboré) ; il remplit l'historique des autres :
lancer scripts/remise_a_zero.py après, avant une démonstration.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parents[1]
CATALOGUE = RACINE / "consentement-minimisation/catalogue"
FINALITES = {code: d["finalite"] for code, d in
             yaml.safe_load((CATALOGUE / "demarches.yaml").read_text(encoding="utf-8"))["demarches"].items()}
CLES = {"concours-direct": "cle-demo-concours", "carte-identite-oni": "cle-demo-oni",
        "certificat-nationalite": "cle-demo-tribunal"}       # clés de DÉMONSTRATION (annuaire.yaml)
RESULTATS: list[bool] = []

# Code exécuté DANS le conteneur de la passerelle (réseau interne : elle n'est pas publiée)
PRELUDE = r'''
import json, sqlite3, time, uuid
import httpx
P = "http://127.0.0.1:8000"
CANAL = {"X-Cle-Canal": open("/run/secrets/canal_usager").read().strip()}

def demander(demarche, sujet, finalite, cle, **plus):
    corps = {"id_demande": str(uuid.uuid4()), "demarche": demarche, "sujet_ref": sujet, "finalite": finalite} | plus
    debut = time.monotonic()
    r = httpx.post(P + "/demandes", json=corps, headers={"X-Cle-Api": cle}, timeout=30)
    return corps["id_demande"], {"code": r.status_code, "corps": r.json(), "duree": round(time.monotonic() - debut, 2)}

def suivre(id_demande, cle):
    return httpx.get(f"{P}/demandes/{id_demande}", headers={"X-Cle-Api": cle}).json()

def confirmer(id_demande, sujet):
    return httpx.post(f"{P}/demandes/{id_demande}/confirmer", json={"sujet_ref": sujet}, headers=CANAL).json()

def journal(id_demande):
    base = sqlite3.connect("file:/donnees/mediateur.sqlite3?mode=ro", uri=True)
    base.row_factory = sqlite3.Row
    return [dict(l) for l in base.execute("SELECT * FROM journal WHERE id_demande = ? ORDER BY n", (id_demande,))]

def sans_accord(sujet):
    """Retire les accords encore valables (laissés par un passage précédent du banc) : la démarche redemande l'accord."""
    for a in httpx.get(f"{P}/usagers/{sujet}/accords", headers=CANAL).json():
        httpx.post(f"{P}/demandes/{a['id_demande']}/retirer", json={"sujet_ref": sujet}, headers=CANAL)

def historique(sujet):
    return httpx.get(f"{P}/usagers/{sujet}/historique", headers=CANAL).json()

resultat = {}
'''


def dans_la_passerelle(code: str) -> dict:
    r = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "-"], cwd=RACINE, capture_output=True,
                       text=True, encoding="utf-8", input=PRELUDE + code + "\nprint(json.dumps(resultat, ensure_ascii=False))\n")
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[-500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def demande(demarche: str, sujet: str, **plus) -> str:
    """Ligne de code (dans la passerelle) qui envoie une demande et range la réponse dans « r »."""
    return f"d, r = demander({demarche!r}, {sujet!r}, {FINALITES[demarche]!r}, {CLES[demarche]!r}, **{plus!r})\n"


def panne(registre: str, mode: str):
    subprocess.run([sys.executable, str(RACINE / "resilience/panne.py"), registre, mode], cwd=RACINE,
                   capture_output=True, check=True)


def noter(titre: str, ok: bool, preuve: str, detail: str = ""):
    RESULTATS.append(ok)
    print(f"{'✅' if ok else '❌'} {titre}\n      {preuve}" + ("" if ok else f"\n      détail : {detail[:600]}"), flush=True)


def volets(reponse: dict) -> dict:
    return {v["attribut"]: v for v in reponse["corps"].get("volets", [])}


# --- Les 3 démarches de bout en bout ---

def concours_majeur_sans_la_date():
    x = dans_la_passerelle(demande("concours-direct", "BF-0002") + """
resultat.update(r=r, journal=[l["evenement"] for l in journal(d)], historique=[l["evenement"] for l in historique("BF-0002")][:3])
""")
    v = volets(x["r"])
    ok = (x["r"]["code"] == 200 and {a: v[a].get("valeur") for a in v} == {"majeur": True, "nationalite_bf": True,
          "casier_vierge": True} and "1998" not in json.dumps(x["r"]) and "remise" in x["journal"]
          and "remise" in x["historique"])
    noter("1. Concours direct : « majeur : oui » sans la date, visible au journal ET dans l'espace usager", ok,
          f"volets {[(a, v[a].get('valeur')) for a in v]} ; journal {x['journal']} ; historique usager {x['historique']}",
          json.dumps(x, ensure_ascii=False))


def carte_identite_oni():
    x = dans_la_passerelle(demande("carte-identite-oni", "BF-0002") + """
resultat.update(r=r, journal=[l["evenement"] for l in journal(d)])
""")
    v = {w["attribut"]: w.get("valeur") for w in volets(x["r"]).values()}
    ok = (x["r"]["code"] == 200 and x["r"]["corps"]["statut"] == "remise" and v["nationalite_bf"] is True
          and v["identite"] == {"nom": "OUEDRAOGO", "prenoms": "Moussa"}
          and v["naissance_filiation"] == {"date_naissance": "1998-07-02", "lieu_naissance": "Koudougou",
                                           "pere": "Hamidou OUEDRAOGO", "mere": "Bintou OUEDRAOGO"}
          and "casier" not in json.dumps(x["r"]) and "remise" in x["journal"])
    noter("2. Carte nationale d'identité (ONI, base légale) : identité, naissance et filiation, nationalité ; pas de casier", ok,
          f"{x['r']['corps']['statut']} {sorted(v)} ; journal {x['journal']}", json.dumps(x, ensure_ascii=False))


def certificat_de_nationalite():
    x = dans_la_passerelle(f'sans_accord("BF-0003")' + chr(10) + demande("certificat-nationalite", "BF-0003") + """
confirmer(d, "BF-0003")
remise = suivre(d, "cle-demo-tribunal")
d2, r2 = demander("certificat-nationalite", "BF-0003", r["corps"].get("finalite") or %r, "cle-demo-tribunal")
resultat.update(attente=r["corps"]["statut"], remise=remise, seconde=r2["corps"]["statut"])
""" % FINALITES["certificat-nationalite"])
    v = {w["attribut"]: w.get("valeur") for w in x["remise"].get("volets", [])}
    ok = x["attente"] == "en_attente" and x["seconde"] == "remise" and v == {"naissance_filiation": {
        "date_naissance": "2012-05-20", "lieu_naissance": "Bobo-Dioulasso", "pere": "Boukary SAWADOGO", "mere": "Awa SAWADOGO"}}
    noter("3. Certificat de nationalité : naissance et filiation pour le tribunal, après accord ; accord valable -> 2e demande immédiate",
          ok, f"{x['attente']} -> {v} ; 2e demande : {x['seconde']}",
          json.dumps(x, ensure_ascii=False))


# --- Situations de l'épreuve ---

def citoyen_inconnu():
    x = dans_la_passerelle(demande("concours-direct", "BF-4242") + "resultat.update(r=r, journal=[(l['evenement'], l['motif']) for l in journal(d)])\n")
    ok = x["r"]["code"] == 404 and ["reponse-registre", "citoyen inconnu"] in x["journal"]
    noter("4. Citoyen inconnu -> 404, au journal", ok, f"HTTP {x['r']['code']} ; journal {x['journal'][-1]}", json.dumps(x))


def registre_en_panne(mode: str, titre: str):
    try:
        panne("etat-civil", mode)
        x = dans_la_passerelle(demande("concours-direct", "BF-0004") + "resultat.update(r=r, journal=[l['statut'] for l in journal(d)])\n")
    finally:
        panne("etat-civil", "normal")
    age = volets(x["r"]).get("majeur", {})
    ok = (x["r"]["code"] == 200 and age.get("statut") == "indisponible" and "indisponible" in x["journal"]
          and volets(x["r"])["casier_vierge"].get("valeur") is False)     # les autres registres répondent quand même
    noter(titre, ok, f"HTTP {x['r']['code']} en {x['r']['duree']} s ; âge : « {age.get('motif')} » ; casier : non vierge",
          json.dumps(x, ensure_ascii=False))


def tous_eteints():
    try:
        for registre in ("etat-civil", "nationalite", "casier"):
            panne(registre, "eteint")
        x = dans_la_passerelle(demande("concours-direct", "BF-0004") + "resultat.update(r=r)\n")
    finally:
        for registre in ("etat-civil", "nationalite", "casier"):
            panne(registre, "normal")
    c = x["r"]["corps"]
    ok = x["r"]["code"] == 503 and c.get("code") == "REGISTRE_INDISPONIBLE" and c.get("etat_demarche") == "en_attente"
    noter("7. Tous les registres éteints -> 503 REGISTRE_INDISPONIBLE, démarche « en attente »", ok,
          f"HTTP {x['r']['code']} {c.get('code')} {c.get('etat_demarche')}", json.dumps(x, ensure_ascii=False))


def non_conforme():
    try:
        panne("nationalite", "non_conforme")
        x = dans_la_passerelle(demande("concours-direct", "BF-0004") + "resultat.update(r=r, journal=[(l['evenement'], l['motif']) for l in journal(d)])\n")
    finally:
        panne("nationalite", "normal")
    nat = volets(x["r"]).get("nationalite_bf", {})
    alertes = [m for e, m in x["journal"] if e == "alerte" and "non conforme au contrat" in m]
    ok = nat.get("statut") == "refuse" and "valeur" not in nat and bool(alertes)
    noter("8. Réponse non conforme au contrat -> rejetée, alerte au journal", ok, f"journal : « {(alertes or [''])[0][:90]} »",
          json.dumps(x, ensure_ascii=False))


def hors_catalogue():
    x = dans_la_passerelle(demande("concours-direct", "BF-0004", attributs=["identite"]) +
                           "resultat.update(r=r, journal=[(l['statut'], l['motif']) for l in journal(d)])\n")
    ok = x["r"]["code"] == 403 and x["r"]["corps"].get("code") == "HORS_CATALOGUE" and x["journal"][0][0] == "refusée"
    noter("9. Attribut hors catalogue -> 403, au journal", ok, f"HTTP {x['r']['code']} ; journal {x['journal']}", json.dumps(x))


def nouvelle_url_par_configuration():
    """On change SEULEMENT l'URL de l'état civil dans annuaire.yaml (relu à chaud) : mauvaise adresse -> indisponible ;
    autre adresse du même registre (nom du conteneur) -> réponse. Le fichier est toujours rétabli."""
    annuaire = CATALOGUE / "annuaire.yaml"
    origine = annuaire.read_bytes()
    texte = origine.decode("utf-8")

    def essayer(url):
        annuaire.write_text(texte.replace("url: http://registre-etat-civil:8000", f"url: {url}"), encoding="utf-8")
        time.sleep(2)                         # la passerelle relit le fichier au plus une fois par seconde
        return dans_la_passerelle(demande("concours-direct", "BF-0004") + "resultat.update(r=r)\n")["r"]
    try:
        absente = essayer("http://registre-qui-n-existe-pas:8000")
        autre = essayer("http://griot-registre-etat-civil-1:8000")
    finally:
        annuaire.write_bytes(origine)
        time.sleep(2)
    ok = volets(absente)["majeur"]["statut"] == "indisponible" and volets(autre)["majeur"].get("valeur") is True
    noter("10. Nouvelle URL de registre par configuration seule (annuaire.yaml, sans redémarrage)", ok,
          f"adresse absente : {volets(absente)['majeur']['statut']} ; autre adresse : majeur = {volets(autre)['majeur'].get('valeur')}",
          json.dumps([absente, autre], ensure_ascii=False))


def registre_autre_equipe_sur_la_pile():
    """Le registre d'état civil d'une AUTRE équipe, sur une autre « machine » (ici l'hôte, vu depuis Docker), branché sur
    la passerelle qui tourne par configuration seule : son contrat copié dans contrats/, annuaire.yaml et
    correspondance.yaml (mêmes blocs que docs/brancher-un-registre.md). La passerelle le joint par « sortie-registres ».
    Les fichiers sont toujours rétablis."""
    import threading
    sys.path.insert(0, str(RACINE / "scripts"))
    sys.path.insert(0, str(RACINE / "scripts/autre_equipe"))
    import essai_a_blanc_autre_equipe as essai
    import faux_registre
    serveur = faux_registre.demarrer(0, "0.0.0.0")
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    fichiers = {CATALOGUE / "annuaire.yaml": None, CATALOGUE / "correspondance.yaml": None}
    for f in fichiers:
        fichiers[f] = f.read_bytes()
    contrat = CATALOGUE / "contrats/autre-equipe.yaml"
    contrat_existait = contrat.exists()
    try:
        contrat.parent.mkdir(exist_ok=True)
        contrat.write_bytes((RACINE / "scripts/autre_equipe/contrat-autre-equipe.yaml").read_bytes())
        essai.remplacer(CATALOGUE / "annuaire.yaml", essai.ANNUAIRE_AVANT,
                        essai.ANNUAIRE_APRES.format(port=port).replace("127.0.0.1", "host.docker.internal"))
        essai.remplacer(CATALOGUE / "correspondance.yaml", essai.CORRESPONDANCE_AVANT, essai.CORRESPONDANCE_APRES)
        time.sleep(2)                         # la passerelle relit ses fichiers au plus une fois par seconde
        appels = faux_registre.FauxRegistre.appels
        r = dans_la_passerelle(demande("concours-direct", "BF-0004") + "resultat.update(r=r)\n")["r"]
        appels = faux_registre.FauxRegistre.appels - appels
    finally:
        for f, contenu in fichiers.items():
            f.write_bytes(contenu)
        if not contrat_existait:
            contrat.unlink(missing_ok=True)
        serveur.shutdown()
        time.sleep(2)
    v = volets(r)
    ok = r["code"] == 200 and appels >= 1 and v["majeur"].get("valeur") is True and "date" not in json.dumps(v["majeur"])
    noter("13. Registre d'une autre équipe (autre machine du réseau) branché par configuration sur la pile", ok,
          f"http://host.docker.internal:{port}/api/v2/personnes/… appelé {appels} fois ; majeur = {v['majeur'].get('valeur')}",
          json.dumps(r, ensure_ascii=False))


def journal_modifie():
    r = subprocess.run([sys.executable, str(RACINE / "resilience/falsifier_journal.py"), "3"], cwd=RACINE,
                       capture_output=True, text=True, encoding="utf-8")
    sortie = r.stdout + r.stderr
    ok = "Journal intègre" in sortie and "Ligne 3 modifiée" in sortie.split("copie falsifiée")[-1]
    noter("11. Ligne du journal modifiée (dans une copie) -> détectée, ligne exacte", ok,
          "vrai journal intègre ; copie : « Ligne 3 modifiée »", sortie)


def agent_curieux():
    x = dans_la_passerelle("""
from pathlib import Path
fichier = Path("/donnees/limite_sujets")
fichier.write_text("3")                 # la limite (0 = désactivée par défaut) est activée le temps du scénario
statuts = []
try:
    for sujet in ("BF-0004", "BF-0005", "BF-0006", "BF-0007"):
        d, r = demander("certificat-nationalite", sujet, %r, "cle-demo-tribunal")
        statuts.append(r["corps"]["statut"])
finally:
    fichier.unlink(missing_ok=True)
resultat.update(statuts=statuts, alerte=[l["motif"] for l in historique("BF-0007") if l["evenement"] == "alerte"][:1])
for sujet in ("BF-0004", "BF-0005", "BF-0006"):         # referme les demandes en attente
    for a in httpx.get(f"{P}/usagers/{sujet}/en-attente", headers=CANAL).json():
        httpx.post(f"{P}/demandes/{a['id_demande']}/refuser", json={"sujet_ref": sujet}, headers=CANAL)
""" % FINALITES["certificat-nationalite"])
    # (les citoyens déjà consultés par le tribunal dans l'heure comptent aussi : le blocage peut venir plus tôt)
    ok = x["statuts"][0] == "en_attente" and x["statuts"][-1] == "bloquee" and bool(x["alerte"])
    noter("12. Administration qui consulte trop de citoyens -> bloquée, alerte dans l'historique (limite activée pour le banc)",
          ok, f"{x['statuts']} ; alerte : « {(x['alerte'] or [''])[0][:70]} »", json.dumps(x, ensure_ascii=False))


def main():
    print("Banc de pannes contre la pile qui tourne (registres selon le contrat, clés API de démonstration)\n", flush=True)
    for scenario in (concours_majeur_sans_la_date, carte_identite_oni, certificat_de_nationalite, citoyen_inconnu,
                     lambda: registre_en_panne("lent", "5. Registre lent -> délai dépassé (2 s + 1 réessai), « indisponible », rien deviné"),
                     lambda: registre_en_panne("eteint", "6. Registre éteint (503) -> « indisponible » pour lui seul"),
                     tous_eteints, non_conforme, hors_catalogue, nouvelle_url_par_configuration, journal_modifie,
                     agent_curieux, registre_autre_equipe_sur_la_pile):
        try:
            scenario()
        except Exception as e:                  # un scénario cassé n'arrête pas le banc
            noter(getattr(scenario, "__name__", "scénario"), False, "erreur pendant le scénario", repr(e))
    print(f"\n{sum(RESULTATS)}/{len(RESULTATS)} situations conformes. Ensuite : scripts/remise_a_zero.py avant une démonstration.")
    sys.exit(0 if all(RESULTATS) else 1)


if __name__ == "__main__":
    main()

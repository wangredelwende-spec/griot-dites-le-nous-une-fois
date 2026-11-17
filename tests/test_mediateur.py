"""Médiateur : catalogue, signature, délai, rejeu, finalité, consentement, journal."""
import asyncio
import importlib.util
import json
import sqlite3
import time

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from conftest import (CANAL, CHEMIN_JOURNAL, RACINE, URL_CASIER, URL_NATIONALITE, URL_REGISTRE, demande,
                      JETON_AGENT, jeton_registre, mediateur, refus_registre)


def registre_qui_signe(**modifs):
    """Faux registre : signe une réponse pour la demande reçue."""
    def repondre(requete):
        return httpx.Response(200, json={"jeton": jeton_registre(json.loads(requete.content), **modifs)})
    return repondre


def journal_de(id_demande_ignore=None):
    base = sqlite3.connect(CHEMIN_JOURNAL)
    base.row_factory = sqlite3.Row
    return [dict(l) for l in base.execute("SELECT * FROM journal ORDER BY n")]


@respx.mock
def test_signature_valide_acceptee(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "remise" and r["volets"][0]["jeton"]
    evenements = [l["evenement"] for l in journal_de()[-3:]]
    assert evenements == ["demande", "reponse-registre", "remise"]


@respx.mock
def test_signature_fausse_refusee(client):
    autre_cle = Ed25519PrivateKey.generate()
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe(cle=autre_cle))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and "signature invalide" in r["motif"] and "jeton" not in r["volets"][0]
    assert journal_de()[-1]["evenement"] == "alerte"


@respx.mock
def test_claims_modifies_refuses(client):
    # Le registre (ou quelqu'un sur le chemin) ajoute la date de naissance : refusé
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe(date_naissance="2001-03-14"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and "contenu inattendu" in r["motif"]


@respx.mock
def test_delai_depasse_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=httpx.ReadTimeout("trop lent"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "indisponible" and "rien n'a été deviné" in r["motif"]
    assert journal_de()[-1]["resultat"] == "indisponible"


@respx.mock
def test_registre_coupe_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=httpx.ConnectError("injoignable"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "indisponible" and "injoignable" in r["motif"]


def registre_qui_refuse(**modifs):
    def repondre(requete):
        return httpx.Response(200, json={"jeton": refus_registre(json.loads(requete.content), **modifs)})
    return repondre


@respx.mock
def test_refus_signe_transmis_sans_detail(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_refuse())
    r = client.post("/demandes", json=demande(sujet="BF-0007")).json()
    assert r["statut"] == "refuse" and r["motif"] == "réponse impossible, s'adresser à l'état civil"
    assert r["volets"][0]["jeton"]        # le refus signé part au guichet, qui en revérifie la signature
    assert "décéd" not in json.dumps(r, ensure_ascii=False)
    assert journal_de()[-1]["evenement"] == "reponse-registre"


@respx.mock
def test_refus_non_signe_rejete(client):
    # Un refus en clair pourrait être fabriqué par n'importe qui sur le chemin : alerte
    respx.post(URL_REGISTRE).mock(return_value=httpx.Response(200, json={"refus": "personne décédée"}))
    r = client.post("/demandes", json=demande(sujet="BF-0007")).json()
    assert r["statut"] == "refuse" and "mal formée" in r["motif"]
    assert journal_de()[-1]["evenement"] == "alerte"


@respx.mock
def test_refus_signe_par_une_autre_cle_rejete(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_refuse(cle=Ed25519PrivateKey.generate()))
    r = client.post("/demandes", json=demande()).json()
    assert "signature invalide" in r["motif"] and journal_de()[-1]["evenement"] == "alerte"


@respx.mock
def test_refus_qui_revele_un_detail_rejete(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_refuse(detail="décédée le 2024-06-01"))
    r = client.post("/demandes", json=demande()).json()
    assert "refus au contenu inattendu" in r["motif"] and journal_de()[-1]["evenement"] == "alerte"


class GoutteAGoutte(httpx.AsyncByteStream):
    """Registre qui répond un octet toutes les 0,2 s : chaque lecture est rapide, le total est interminable."""
    async def __aiter__(self):
        for _ in range(50):
            await asyncio.sleep(0.2)
            yield b" "


@respx.mock
def test_registre_goutte_a_goutte_coupe_au_delai_total(client):
    respx.post(URL_REGISTRE).mock(return_value=httpx.Response(200, stream=GoutteAGoutte()))
    debut = time.monotonic()
    r = client.post("/demandes", json=demande()).json()
    assert time.monotonic() - debut < 1.5                  # délai total des tests : 0,5 s (et non 10 s)
    assert r["statut"] == "indisponible" and "délai dépassé" in r["motif"]


@respx.mock
def test_rejeu_une_seule_execution(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande()
    premiere = client.post("/demandes", json=d).json()
    seconde = client.post("/demandes", json=d).json()
    assert route.call_count == 1
    assert premiere["statut"] == seconde["statut"] == "remise"
    assert "jeton" not in seconde["volets"][0]        # déjà remis : le médiateur l'a effacé


@respx.mock
def test_meme_id_pour_une_autre_demande_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande()
    client.post("/demandes", json=d)
    r = client.post("/demandes", json={**d, "sujet_ref": "BF-0002"})
    assert r.status_code == 409


@respx.mock
def test_mauvaise_finalite_refusee(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande(finalite="curiosité")).json()
    assert r["statut"] == "refuse" and r["motif"] == "finalité non autorisée"
    assert route.call_count == 0


@respx.mock
def test_demarche_d_un_autre_service_refusee(client):
    # Issa (concours) tente la démarche « bourse-nationale » : refusé, le service vient du jeton
    r = client.post("/demandes", json=demande(demarche="bourse-nationale")).json()
    assert r["statut"] == "refuse" and "non autorisée pour ce service" in r["motif"]


@respx.mock
def test_consentement_apercu_puis_confirmation(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse-nationale", sujet="BF-0012")
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    suivi = client.get(f"/demandes/{d['id_demande']}").json()
    assert suivi["statut"] == "en_attente" and "jeton" not in suivi["volets"][0]   # rien avant l'accord

    attente = client.get("/usagers/BF-0012/en-attente", headers=CANAL).json()
    assert attente[0]["apercu"] == "Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre."
    confirmation = client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0012"}, headers=CANAL)
    assert confirmation.json()["statut"] == "confirmee" and len(confirmation.json()["empreinte"]) == 64

    remise = client.get(f"/demandes/{d['id_demande']}").json()
    assert remise["statut"] == "remise" and remise["volets"][0]["jeton"]
    assert "jeton" not in client.get(f"/demandes/{d['id_demande']}").json()["volets"][0]   # remis une seule fois


@respx.mock
def test_refus_par_l_usager(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse-nationale", sujet="BF-0013")
    client.post("/demandes", json=d)
    client.post(f"/demandes/{d['id_demande']}/refuser", json={"sujet_ref": "BF-0013"}, headers=CANAL)
    r = client.get(f"/demandes/{d['id_demande']}").json()
    assert r["statut"] == "refuse" and "jeton" not in r["volets"][0]


@respx.mock
def test_un_autre_usager_ne_peut_pas_confirmer(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse-nationale", sujet="BF-0014")
    client.post("/demandes", json=d)
    r = client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0015"}, headers=CANAL)
    assert r.status_code == 404


@respx.mock
def test_consentement_expire(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse-nationale", sujet="BF-0016")
    client.post("/demandes", json=d)
    sqlite3.connect(CHEMIN_JOURNAL, isolation_level=None).execute(
        "UPDATE demandes SET expire_le = 0 WHERE id_demande = ?", (d["id_demande"],))
    r = client.get(f"/demandes/{d['id_demande']}").json()
    assert r["statut"] == "expiree" and "jeton" not in r["volets"][0]


def test_canal_usager_sans_secret_refuse(client):
    assert client.get("/usagers/BF-0001/en-attente").status_code == 401


@respx.mock
def test_historique_sans_la_valeur(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.post("/demandes", json=demande(sujet="BF-0018"))
    historique = client.get("/usagers/BF-0018/historique", headers=CANAL).json()
    assert [l["evenement"] for l in historique] == ["remise", "reponse-registre", "demande"]
    assert historique[0]["service"] == "La Direction des concours – ministère des Serviteurs du peuple"
    assert "012-2025" in historique[0]["texte_base"]
    assert historique[0]["attributs"] == [{"code": "age_entre", "libelle": "majeur (18 ans accomplis)",
                                           "parametres": {"min": 18, "date_reference": "aujourd'hui"}}]
    texte = json.dumps(historique, ensure_ascii=False)
    assert "true" not in texte and "= oui" not in texte and "BF-0018" not in texte


def test_journal_integre_puis_ligne_modifiee_detectee():
    spec = importlib.util.spec_from_file_location("verifier", RACINE / "journal/verifier.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    from app.journal import empreinte
    lignes = journal_de()
    assert all(verifier.empreinte(l) == empreinte(l) == l["hash"] for l in lignes)   # même calcul
    integre, message, _ = verifier.verifier(str(CHEMIN_JOURNAL))
    assert integre, message

    # Un administrateur modifie directement la ligne 2 dans le fichier SQLite
    base = sqlite3.connect(CHEMIN_JOURNAL, isolation_level=None)
    base.execute("DROP TRIGGER journal_sans_modification")
    base.execute("UPDATE journal SET demandeur = 'quelqu-un-d-autre' WHERE n = 3")
    integre, message, _ = verifier.verifier(str(CHEMIN_JOURNAL))
    assert not integre and message == "Ligne 3 modifiée"


def test_verifier_recu_avec_ou_sans_espaces():
    import subprocess
    import sys
    ligne = journal_de()[0]
    recu = ligne["hash"][:16]
    for forme in (recu, " ".join(recu[i:i + 4] for i in range(0, 16, 4))):
        r = subprocess.run([sys.executable, str(RACINE / "journal/verifier.py"), str(CHEMIN_JOURNAL), "--recu", forme],
                           capture_output=True, text=True, encoding="utf-8")
        assert f"Reçu retrouvé : ligne {ligne['n']}" in r.stdout, r.stdout + r.stderr
    trop_court = subprocess.run([sys.executable, str(RACINE / "journal/verifier.py"), str(CHEMIN_JOURNAL),
                                 "--recu", recu[:8]], capture_output=True, text=True, encoding="utf-8")
    assert trop_court.returncode != 0 and "16 caractères" in trop_court.stderr


def demande_casier(sujet="BF-0003"):
    """Le casier n'est demandé que par le concours direct : on coupe les deux autres registres."""
    respx.post(URL_NATIONALITE).mock(side_effect=httpx.ConnectError("hors sujet"))
    return demande("concours-adjoints", sujet)


def volet(reponse: dict, attribut: str) -> dict:
    return next(v for v in reponse["volets"] if v["attribut"] == attribut)


@respx.mock
def test_casier_absence_vierge_verifie_l_identite(client, monkeypatch):
    """Casier « absence: vierge » : identité non confirmée par l'état civil -> refus, casier jamais appelé."""
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT | {"absence_vierge": {"casier"}})
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_refuse())
    casier = respx.post(URL_CASIER).mock(return_value=httpx.Response(500))
    r = client.post("/demandes", json=demande_casier("BF-0099")).json()
    assert volet(r, "casier_judiciaire_vierge")["motif"] == "identité non confirmée par l'état civil"
    assert not casier.called


@respx.mock
def test_casier_absence_vierge_identite_confirmee(client, monkeypatch):
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT | {"absence_vierge": {"casier"}})
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    respx.post(URL_CASIER).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande_casier()).json()
    assert volet(r, "casier_judiciaire_vierge")["jeton"]
    attributs = [l["attribut"] for l in journal_de() if l["evenement"] == "reponse-registre"][-4:]
    assert "personne_connue" in attributs and "casier_judiciaire_vierge" in attributs


@respx.mock
def test_casier_absence_vierge_etat_civil_coupe(client, monkeypatch):
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT | {"absence_vierge": {"casier"}})
    respx.post(URL_REGISTRE).mock(side_effect=httpx.ConnectError("coupé"))
    r = client.post("/demandes", json=demande_casier()).json()
    v = volet(r, "casier_judiciaire_vierge")
    assert v["statut"] == "indisponible" and "rien n'a été deviné" in v["motif"]


# --- Catalogue et concours direct (3 registres en parallèle) ---

def tous_les_registres(etat_civil=None, nationalite=None, casier=None):
    respx.post(URL_REGISTRE).mock(side_effect=etat_civil or registre_qui_signe())
    respx.post(URL_NATIONALITE).mock(side_effect=nationalite or registre_qui_signe())
    respx.post(URL_CASIER).mock(side_effect=casier or registre_qui_signe())


@respx.mock
def test_concours_direct_trois_registres_une_demande(client):
    tous_les_registres()
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    assert r["statut"] == "remise"
    assert [v["attribut"] for v in r["volets"]] == ["age_entre", "nationalite_burkinabe", "casier_judiciaire_vierge"]
    assert all(v["jeton"] and v["statut"] == "ok" for v in r["volets"])
    # Les paramètres viennent du catalogue, jamais du guichet
    corps = json.loads(respx.calls[0].request.content)
    assert corps["parametres"] == {"min": 18, "max": 37, "date_reference": "2026-12-31"}
    evenements = [l["evenement"] for l in journal_de()[-5:]]
    assert evenements == ["demande", "reponse-registre", "reponse-registre", "reponse-registre", "remise"]
    assert journal_de()[-1]["attribut"] == "age_entre+nationalite_burkinabe+casier_judiciaire_vierge"


@respx.mock
def test_concours_direct_registres_appeles_en_parallele(client):
    async def lent(requete):
        await asyncio.sleep(0.3)
        return httpx.Response(200, json={"jeton": jeton_registre(json.loads(requete.content))})
    tous_les_registres(lent, lent, lent)
    debut = time.monotonic()
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    assert r["statut"] == "remise" and time.monotonic() - debut < 0.75     # 3 × 0,3 s en série = 0,9 s


@respx.mock
def test_concours_direct_un_registre_en_panne(client):
    """L'état civil est coupé : la nationalité et le casier s'affichent, l'âge est « indisponible »."""
    tous_les_registres(etat_civil=httpx.ConnectError("coupé"))
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    age = volet(r, "age_entre")
    assert age["statut"] == "indisponible" and "rien n'a été deviné" in age["motif"] and "jeton" not in age
    assert volet(r, "nationalite_burkinabe")["jeton"] and volet(r, "casier_judiciaire_vierge")["jeton"]


@respx.mock
def test_tous_les_registres_en_panne(client):
    coupe = httpx.ConnectError("coupé")
    tous_les_registres(coupe, coupe, coupe)
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    assert r["statut"] == "indisponible" and all(v["statut"] == "indisponible" for v in r["volets"])


@respx.mock
def test_date_de_reference_falsifiee_refusee(client):
    tous_les_registres(etat_civil=lambda req: httpx.Response(200, json={"jeton": jeton_registre(
        json.loads(req.content), date_reference="2030-01-01")}))
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    assert "date de référence" in volet(r, "age_entre")["motif"]


@respx.mock
def test_seuil_d_age_manquant_refuse(client):
    # Le registre ne répond que « 18 ans » : on ne peut pas conclure « 37 ans au plus »
    tous_les_registres(etat_civil=lambda req: httpx.Response(200, json={"jeton": jeton_registre(
        json.loads(req.content), age_equal_or_over={"18": True})}))
    r = client.post("/demandes", json=demande("concours-adjoints")).json()
    assert "seuils d'âge" in volet(r, "age_entre")["motif"]


@respx.mock
def test_majorite_date_du_jour(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.post("/demandes", json=demande())
    from datetime import datetime, timezone
    corps = json.loads(route.calls[0].request.content)
    assert corps["parametres"] == {"min": 18, "date_reference": datetime.now(timezone.utc).date().isoformat()}


@respx.mock
def test_attributs_en_plus_refuses(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande(attributs=["age_entre", "casier_judiciaire_vierge"])).json()
    assert r["statut"] == "refuse" and "attributs non autorisés" in r["motif"] and not route.called
    # Aucun champ libre (ex. « date_naissance ») : la demande est rejetée avant tout traitement
    assert client.post("/demandes", json=demande(date_naissance=True)).status_code == 422
    assert client.post("/demandes", json=demande(attributs=["age_entre"])).json()["statut"] == "remise"


@respx.mock
def test_consentement_plusieurs_attributs_un_apercu_une_confirmation(client, monkeypatch):
    demarches = mediateur.CAT["demarches"] | {"bourse-complete": {
        "libelle": "Bourse (test)", "services": ["service-bourses"], "finalite": "test", "base": "consentement",
        "attributs": [{"attribut": "age_entre", "parametres": {"min": 18, "date_reference": "aujourd'hui"},
                       "libelle": "majeur"},
                      {"attribut": "nationalite_burkinabe", "parametres": {}, "libelle": "nationalité burkinabè"}]}}
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT | {"demarches": demarches})
    client.agent["nom"] = "awa.ouedraogo"
    tous_les_registres()
    d = demande("verifier-majorite", sujet="BF-0002") | {"demarche": "bourse-complete", "finalite": "test"}
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    attente = client.get("/usagers/BF-0002/en-attente", headers=CANAL).json()
    assert len(attente) == 1
    assert attente[0]["apercu"] == "Le service des bourses recevra : majeur = oui ; nationalité burkinabè = oui. Rien d'autre."
    client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0002"}, headers=CANAL)
    r = client.get(f"/demandes/{d['id_demande']}").json()
    assert r["statut"] == "remise" and all(v["jeton"] for v in r["volets"])


def test_empreinte_du_catalogue_au_journal(client):
    import hashlib
    attendue = hashlib.sha256((RACINE / "catalogue/demarches.yaml").read_bytes()).hexdigest()
    lignes = [l for l in journal_de() if l["evenement"] == "catalogue"]
    assert lignes and lignes[0]["motif"].endswith(f"sha256 {attendue}") and lignes[0]["sujet"] == ""


def test_catalogue_invalide_refuse_de_demarrer():
    from app import catalogue
    attributs = {"age_entre": {"regle": "age_entre"}, "nationalite_burkinabe": {"regle": "egal"}}
    services = {"mairie": {}}
    bonne = {"libelle": "x", "services": ["mairie"], "finalite": "f", "base": "base_legale", "texte": "loi",
             "attributs": [{"attribut": "nationalite_burkinabe", "libelle": "n"}]}
    assert catalogue.valider({"ok": bonne}, services, attributs) == []
    cas = {
        "sans finalité": bonne | {"finalite": ""},
        "sans base": bonne | {"base": None},
        "base légale sans texte": bonne | {"texte": ""},
        "attribut inconnu": bonne | {"attributs": [{"attribut": "date_naissance", "libelle": "d"}]},
        "service inconnu": bonne | {"services": ["police"]},
        "âge sans min": bonne | {"attributs": [{"attribut": "age_entre", "libelle": "a",
                                                "parametres": {"date_reference": "2026-12-31"}}]},
        "max < min": bonne | {"attributs": [{"attribut": "age_entre", "libelle": "a",
                                             "parametres": {"min": 30, "max": 18, "date_reference": "aujourd'hui"}}]},
    }
    for nom, demarche in cas.items():
        assert catalogue.valider({"d": demarche}, services, attributs), f"{nom} : aurait dû être refusé"


# --- A. Le jeton de l'agent accompagne chaque demande au registre ---

@respx.mock
def test_jeton_de_l_agent_transmis_au_registre(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.post("/demandes", json=demande())
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {JETON_AGENT}"
    # Il n'est jamais stocké par le médiateur
    assert JETON_AGENT.encode() not in CHEMIN_JOURNAL.read_bytes()


@respx.mock
def test_refus_du_registre_faute_de_jeton_valide(client):
    """Le registre refuse (signé) un jeton d'agent qu'il ne peut pas vérifier : le guichet voit ce refus."""
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_refuse(motif="jeton d'agent invalide ou expiré"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and r["volets"][0]["motif"] == "jeton d'agent invalide ou expiré"
    assert r["volets"][0]["jeton"]


# --- B. Limite par (service, citoyen) ---

@respx.mock
def test_limite_par_service_et_par_citoyen(client, monkeypatch):
    monkeypatch.setattr(mediateur, "LIMITE_PAR_CITOYEN", 3)
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    statuts = [client.post("/demandes", json=demande(sujet="BF-0020")).json()["statut"] for _ in range(4)]
    assert statuts == ["remise", "remise", "remise", "bloquee"]
    assert route.call_count == 3                            # le registre n'est pas appelé la 4e fois
    # L'alerte apparaît dans l'historique du citoyen, avec son motif
    alerte = client.get("/usagers/BF-0020/historique", headers=CANAL).json()[0]
    assert alerte["evenement"] == "alerte" and "plus de 3 demandes du même service" in alerte["motif"]
    # Un AUTRE service peut toujours interroger cette personne ; le même service, une autre personne aussi
    client.agent["nom"] = "awa.ouedraogo"
    assert client.post("/demandes", json=demande(sujet="BF-0020")).json()["statut"] == "remise"
    client.agent["nom"] = "issa.sawadogo"
    assert client.post("/demandes", json=demande(sujet="BF-0016")).json()["statut"] == "remise"


@respx.mock
def test_comptes_de_test_exemptes_seulement_si_outils_test(client, monkeypatch):
    monkeypatch.setattr(mediateur, "LIMITE_PAR_CITOYEN", 1)
    monkeypatch.setattr(mediateur, "LIMITE_EXEMPTES", {"issa.sawadogo"})
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    monkeypatch.setattr(mediateur, "OUTILS_TEST", True)       # mode test : exemption active
    assert [client.post("/demandes", json=demande(sujet="BF-0014")).json()["statut"] for _ in range(3)] == ["remise"] * 3
    monkeypatch.setattr(mediateur, "OUTILS_TEST", False)      # démonstration : mêmes limites que tout le monde
    assert client.post("/demandes", json=demande(sujet="BF-0015")).json()["statut"] == "remise"
    assert client.post("/demandes", json=demande(sujet="BF-0015")).json()["statut"] == "bloquee"


# --- Retrait du consentement ---

def demande_confirmee(client, sujet: str, confirmer: bool = True) -> dict:
    client.agent["nom"] = "awa.ouedraogo"
    d = demande(demarche="bourse-nationale", sujet=sujet)
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    if confirmer:
        client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": sujet}, headers=CANAL)
    return d


@respx.mock
def test_retrait_avant_la_remise_rien_ne_part(client):
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande_confirmee(client, "BF-0010")
    accords = client.get("/usagers/BF-0010/accords", headers=CANAL).json()
    assert accords[0]["id_demande"] == d["id_demande"] and accords[0]["transmis"] is False
    r = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0010"}, headers=CANAL).json()
    assert r["statut"] == "retiree" and r["transmis"] is False and len(r["empreinte"]) == 64
    guichet = client.get(f"/demandes/{d['id_demande']}").json()       # l'agent actualise : rien
    assert guichet["statut"] == "retiree" and "jeton" not in guichet["volets"][0]
    assert journal_de()[-1]["evenement"] == "retrait"
    assert client.get("/usagers/BF-0010/accords", headers=CANAL).json() == []


@respx.mock
def test_retrait_avant_meme_la_confirmation(client):
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande_confirmee(client, "BF-0011", confirmer=False)
    r = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0011"}, headers=CANAL).json()
    assert r["statut"] == "retiree"


@respx.mock
def test_retrait_apres_la_remise_ecrit_au_journal(client):
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande_confirmee(client, "BF-0017")
    assert client.get(f"/demandes/{d['id_demande']}").json()["statut"] == "remise"
    assert client.get("/usagers/BF-0017/accords", headers=CANAL).json()[0]["transmis"] is True
    r = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0017"}, headers=CANAL).json()
    assert r["statut"] == "retiree_apres_remise" and r["transmis"] is True
    ligne = journal_de()[-1]
    assert ligne["evenement"] == "retrait" and "ne doit plus utiliser" in ligne["motif"]
    again = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0017"}, headers=CANAL)
    assert again.status_code == 409


@respx.mock
def test_retrait_impossible_en_base_legale_ou_pour_un_autre(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande(sujet="BF-0016")
    client.post("/demandes", json=d)
    r = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0016"}, headers=CANAL)
    assert r.status_code == 409 and "base légale" in r.json()["detail"]
    r = client.post(f"/demandes/{d['id_demande']}/retirer", json={"sujet_ref": "BF-0015"}, headers=CANAL)
    assert r.status_code == 404


# --- Limite par agent : trop de citoyens DIFFÉRENTS ---

@respx.mock
def test_agent_curieux_bloque_et_citoyens_alertes(client, monkeypatch):
    monkeypatch.setattr(mediateur, "LIMITE_SUJETS", 3)
    client.agent["nom"] = "agent.curieux"
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    statuts = [client.post("/demandes", json=demande(sujet=f"CUR-{i}")).json()["statut"] for i in range(1, 5)]
    assert statuts == ["remise", "remise", "remise", "bloquee"] and route.call_count == 3
    # Alerte dans l'historique de CHAQUE citoyen concerné (les 3 consultés + celui qui a déclenché le blocage)
    for i in range(1, 5):
        historique = client.get(f"/usagers/CUR-{i}/historique", headers=CANAL).json()
        assert historique[0]["evenement"] == "alerte" and "agent bloqué" in historique[0]["motif"], i
    # Reconsulter un citoyen déjà consulté reste possible ; un nouveau est encore bloqué, sans réalerter les autres
    assert client.post("/demandes", json=demande(sujet="CUR-1")).json()["statut"] == "remise"
    assert client.post("/demandes", json=demande(sujet="CUR-5")).json()["statut"] == "bloquee"
    alertes = [l for l in journal_de() if l["evenement"] == "alerte" and "agent bloqué" in l["motif"]]
    assert len(alertes) == 5


# --- Double trace : comparaison du journal et des traces des registres ---

def charger_verifier():
    spec = importlib.util.spec_from_file_location("verifier", RACINE / "journal/verifier.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ligne(id_demande, evenement="reponse-registre", resultat="ok", registre="etat-civil", ts="2026-11-16T15:00:00Z"):
    return {"id_demande": id_demande, "evenement": evenement, "resultat": resultat, "registre": registre,
            "attribut": "age_entre", "ts": ts}


def trace(*ids, debut="2026-11-16T14:00:00Z"):
    return {"debut": debut, "trace": [{"id_demande": i, "attribut": "age_entre", "ts": "2026-11-16T15:00:00Z",
                                       "jti": "j", "destinataire": "mairie", "statut": "ok"} for i in ids]}


def test_double_trace_concordante():
    verifier = charger_verifier()
    lignes = [ligne("", "catalogue", ts="2026-11-16T14:30:00Z"), ligne("d1"), ligne("d2", "alerte", "refuse"),
              ligne("d3", resultat="indisponible")]          # d3 : registre coupé, aucune trace : normal
    assert verifier.comparer({"etat-civil": trace("d1", "d2")}, lignes) == []


def test_double_trace_consultation_cachee_par_le_mediateur():
    """Le médiateur a supprimé la ligne de d2 et recalculé sa chaîne : le registre, lui, a gardé sa trace."""
    verifier = charger_verifier()
    ecarts = verifier.comparer({"etat-civil": trace("d1", "d2")}, [ligne("", "catalogue"), ligne("d1")])
    assert ecarts == ["etat-civil : réponse à la demande d2 (age_entre) ABSENTE du journal du médiateur"]


def test_double_trace_reponse_inventee():
    verifier = charger_verifier()
    ecarts = verifier.comparer({"etat-civil": trace("d1")}, [ligne("", "catalogue"), ligne("d1"), ligne("d9")])
    assert ecarts == ["etat-civil : le journal cite une réponse à la demande d9 (age_entre) que le registre n'a jamais émise"]


def test_double_trace_registre_illisible():
    verifier = charger_verifier()
    assert verifier.comparer({"casier": "trace illisible"}, []) == ["casier : trace illisible"]


@respx.mock
def test_les_lignes_du_journal_portent_l_id_de_demande(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande()
    client.post("/demandes", json=d)
    assert {l["id_demande"] for l in journal_de()[-3:]} == {d["id_demande"]}


# --- Contrôle (rôle « controleur », lecture seule) ---

def test_controle_exige_le_role_controleur(client, monkeypatch):
    from app import agents
    monkeypatch.setattr(agents, "infos_du_jeton", lambda _a: ("j", {"sub": "x", "roles": ["agent-guichet"]}))
    assert client.get("/controle", headers={"Authorization": "Bearer j"}).status_code == 403
    monkeypatch.setattr(agents, "infos_du_jeton", lambda _a: ("j", {"sub": "x", "roles": ["controleur"]}))
    assert agents.controleur_connecte("Bearer j") == "x"


@respx.mock
def test_controle_montre_les_alertes_sans_identifiant_de_citoyen(client):
    mediateur.app.dependency_overrides[mediateur.controleur_connecte] = lambda: "controle.cil"
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe(cle=Ed25519PrivateKey.generate()))  # corrompue
    respx.get("http://registre-etat-civil:8000/sante").mock(return_value=httpx.Response(200))
    respx.get("http://registre-nationalite:8000/sante").mock(side_effect=httpx.ConnectError("coupé"))
    respx.get("http://registre-casier:8000/sante").mock(return_value=httpx.Response(200))
    client.post("/demandes", json=demande(sujet="BF-0003"))
    r = client.get("/controle")
    assert r.status_code == 200
    c = r.json()
    assert c["comptes_de_test_actifs"] is False
    assert any("signature invalide" in a["motif"] for a in c["alertes"])
    assert {e["code"]: e["joignable"] for e in c["registres"]} == {"etat-civil": True, "nationalite": False,
                                                                   "casier": True}
    assert c["catalogue"]["empreinte"] == mediateur.CAT["empreinte"]
    # Ni l'identifiant du citoyen, ni son pseudonyme, ni l'identifiant de la demande
    assert "BF-0003" not in r.text and mediateur.pseudonyme("BF-0003") not in r.text
    assert '"sujet"' not in r.text and "id_demande" not in r.text


def test_controle_verifie_le_journal(client):
    mediateur.app.dependency_overrides[mediateur.controleur_connecte] = lambda: "controle.cil"
    r = client.get("/controle/verification").json()
    # Même verdict que journal/verifier.py (le journal de test a pu être falsifié exprès par un test précédent)
    spec = importlib.util.spec_from_file_location("verifier", RACINE / "journal/verifier.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    integre, message, _ = verifier.verifier(str(CHEMIN_JOURNAL))
    assert (r["integre"], r["message"]) == (integre, message)
    assert message.startswith("Journal intègre") or "modifiée" in message


def test_controle_ne_peut_rien_demander(client):
    """Aucune route d'écriture n'accepte le contrôleur : sans le rôle agent-guichet, POST /demandes est refusé."""
    mediateur.app.dependency_overrides.pop(mediateur.agent_connecte)
    from app import agents
    agents_infos = agents.infos_du_jeton
    try:
        agents.infos_du_jeton = lambda _a: ("j", {"sub": "x", "roles": ["controleur"]})
        r = client.post("/demandes", json=demande(), headers={"Authorization": "Bearer j"})
        assert r.status_code == 403
    finally:
        agents.infos_du_jeton = agents_infos



# --- Passeport (scénario principal) : consentement, deux registres (pas d'âge : l'ONI le connaît par la CNIB) ---

def reponses_passeport(interdiction=False):
    def repondre(requete):
        corps = json.loads(requete.content)
        valeurs = {"nationalite_burkinabe": {"nationalite_burkinabe": True},
                   "interdiction_sortie_territoire": {"interdiction_sortie_territoire": interdiction}}
        return httpx.Response(200, json={"jeton": jeton_registre(corps, **valeurs[corps["attribut"]])})
    return repondre


@respx.mock
def test_passeport_apercu_puis_confirmation(client):
    client.agent["nom"] = "moussa.kone"
    etat_civil = respx.post(URL_REGISTRE).mock(return_value=httpx.Response(500))
    for url in (URL_NATIONALITE, URL_CASIER):
        respx.post(url).mock(side_effect=reponses_passeport())
    d = demande(demarche="passeport-ordinaire", sujet="BF-0001")
    r = client.post("/demandes", json=d).json()
    assert r["statut"] == "en_attente" and all("jeton" not in v for v in r["volets"])     # rien ne part avant
    attente = client.get("/usagers/BF-0001/en-attente", headers=CANAL).json()
    assert attente[0]["apercu"] == ("L'ONI (passeports) recevra : burkinabè = oui ; "
                                    "interdiction de sortie du territoire = non. Rien d'autre.")
    assert not etat_civil.called            # l'état civil n'est jamais interrogé pour un passeport
    client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0001"}, headers=CANAL)
    remise = client.get(f"/demandes/{d['id_demande']}").json()
    assert remise["statut"] == "remise" and all(v["jeton"] for v in remise["volets"])


def test_passeport_ne_peut_pas_demander_l_age(client):
    """L'ONI ne peut pas ajouter « majeur » à sa demande : le catalogue ne le prévoit pas."""
    client.agent["nom"] = "moussa.kone"
    d = demande(demarche="passeport-ordinaire", sujet="BF-0001") | {
        "attributs": ["age_entre", "nationalite_burkinabe", "interdiction_sortie_territoire"]}
    r = client.post("/demandes", json=d).json()
    assert r["statut"] == "refuse" and r["motif"].startswith("attributs non autorisés")


def test_passeport_reserve_a_la_police(client):
    client.agent["nom"] = "awa.ouedraogo"       # service des bourses
    r = client.post("/demandes", json=demande(demarche="passeport-ordinaire", sujet="BF-0001")).json()
    assert r["statut"] == "refuse" and r["motif"] == "démarche non autorisée pour ce service"


# --- Format de l'identifiant réglable (annuaire.yaml) : clé composée des données du jury ---

def test_identifiant_au_mauvais_format_refuse(client):
    r = client.post("/demandes", json=demande(sujet="BF 0001 ; DROP"))
    assert r.status_code == 422 and "mauvais format" in r.json()["detail"]
    assert client.get("/usagers/BF%200001/en-attente", headers=CANAL).status_code == 422


@respx.mock
def test_cle_composee_de_bout_en_bout(client, monkeypatch):
    import re as re_
    monkeypatch.setattr(mediateur, "FORMAT_IDENTIFIANT", re_.compile(r"^[^|/]{1,60}\|[^|/]{1,80}\|\d{4}-\d{2}-\d{2}$"))
    cle = "KABORÉ|Aminata Rosine|2001-03-14"
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse-nationale", sujet=cle)
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    # La clé passe dans l'adresse (« | », espace, accent encodés), comme le fait l'USSD
    from urllib.parse import quote
    attente = client.get(f"/usagers/{quote(cle, safe='')}/en-attente", headers=CANAL).json()
    assert [a["id_demande"] for a in attente] == [d["id_demande"]]
    client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": cle}, headers=CANAL)
    assert client.get(f"/demandes/{d['id_demande']}").json()["statut"] == "remise"
    historique = client.get(f"/usagers/{quote(cle, safe='')}/historique", headers=CANAL).json()
    assert historique and cle not in json.dumps(historique)        # jamais l'identifiant en clair


@respx.mock
def test_base_et_texte_transmis_au_registre(client):
    """Le registre reçoit le mode (base légale) et le texte cité, pour vérifier lui-même qu'il les a déclarés."""
    recus = []

    def registre(requete):
        recus.append(json.loads(requete.content))
        return httpx.Response(200, json={"jeton": jeton_registre(recus[-1])})
    for url in (URL_REGISTRE, URL_NATIONALITE, URL_CASIER):
        respx.post(url).mock(side_effect=registre)
    client.post("/demandes", json=demande("concours-adjoints"))
    assert len(recus) == 3
    assert all(c["base"] == "base_legale" and "loi n°081-2015/CNT" in c["texte"] for c in recus)

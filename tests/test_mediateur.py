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
    assert historique[0]["service"] == "La direction des concours de la fonction publique"
    assert "012-2025" in historique[0]["texte_base"]
    assert historique[0]["attributs"] == [{"code": "age_entre", "libelle": "majeur (18 ans accomplis)"}]
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
def test_comptes_de_test_exemptes(client, monkeypatch):
    monkeypatch.setattr(mediateur, "LIMITE_PAR_CITOYEN", 1)
    monkeypatch.setattr(mediateur, "LIMITE_EXEMPTES", {"issa.sawadogo"})
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    assert [client.post("/demandes", json=demande(sujet="BF-0014")).json()["statut"] for _ in range(3)] == ["remise"] * 3
